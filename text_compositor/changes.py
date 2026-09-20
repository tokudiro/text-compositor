"""ファイルの変更検出。`--watch`と`--if-changed`で共用する。"""
import os
import io
import contextlib
import glob
from text_compositor.config import _output_pdf_path, load_config_file, resolve_template_path
from text_compositor.document import _common_template_path

def _tool_source_files(tool_dir):
    """ツール自身のソース（tool_dir直下の.py）。ビルド本体は複数のモジュールに分かれている（#157）ため、
    build.pyだけでなく全部を、依存物として見る。"""
    return sorted(glob.glob(os.path.join(tool_dir, "*.py")))

# --if-changed（#151）。判定は更新日時のみ（make方式）で、内容ハッシュは採用しない。ハッシュ方式は
# 全入力を毎回読む必要があり、しかもCIではactions/checkoutが全ファイルの更新日時を更新するため、
# 更新日時方式は出力PDFを復元しない限り常に再生成になる。CIで使う場合は出力先をactions/cacheで
# 復元し、復元したPDFが入力より新しくなる運用が必要（仕様書4章）。
def _is_up_to_date(tool_dir, config_path, project_dir, config):
    """(出力PDFが依存物のどれよりも新しいか, 出力PDFパス)を返す。出力PDFが無ければ古い扱い。
    依存物は--watchと同じ解決結果（config・project_dir配下・inputs.dir・.typテンプレート）に、ツール自身
    （text_compositor/直下の.py）と同梱テンプレートを加えたもの。ツールの更新（pip upgrade等）で出力が変わり得るため。
    Typst自体のバージョンは判定に含めない（更新日時では検出できない。再生成したいときは--if-changedを外す）。"""
    out_pdf = _output_pdf_path(project_dir, config)
    try:
        out_mtime = os.stat(out_pdf).st_mtime_ns
    except OSError:
        return False, out_pdf
    roots, ignore, files = _watch_targets(tool_dir, config_path)
    files = files + _tool_source_files(tool_dir) + [
        _common_template_path(tool_dir), resolve_template_path(config["template"]["path"], tool_dir, project_dir)]
    explicit = {os.path.normcase(os.path.normpath(f)) for f in files}
    snapshot = _watch_snapshot(roots, ignore, files)
    # 同じproject_dirを共有する別configのPDFを入力とみなすと、--config-listで互いのPDFの更新を
    # 検知し合い、常に再生成になる。PDFはTypstの入力にならないため、個別指定の依存物以外は除外する。
    newest = max((mtime for path, (mtime, _) in snapshot.items()
                  if not path.lower().endswith(".pdf") or os.path.normcase(os.path.normpath(path)) in explicit),
                 default=0)
    return out_mtime > newest, out_pdf

def _watch_targets(tool_dir, config_path):
    """configから監視対象を解決し、(監視ルートのリスト, 無視するパスのリスト, 個別監視ファイルのリスト)を返す。
    ルートはproject_dirとinputs.dir、個別ファイルはconfig自身と（.typパス指定の場合のみ）テンプレート。
    ツール同梱テンプレート（名前指定）は利用者が編集しないため対象外。出力先は、ビルド自身が
    書き込むPDFを「変更」と誤検知して無限に再ビルドしないよう無視する。config自体が壊れている
    最中でも監視を続けたいので、読めなければconfigとproject_dirだけを対象にする。"""
    project_dir = os.path.dirname(config_path)
    roots, ignore, files = [project_dir], [], [config_path]
    try:
        # load_config_fileは失敗時に[Error]を出力してsys.exit(1)する。ビルド側で既に報告されるため、
        # ここでの二重表示を避ける。
        with contextlib.redirect_stdout(io.StringIO()):
            config = load_config_file(config_path)
        inputs_dir = os.path.normpath(os.path.join(project_dir, config.get("inputs", {}).get("dir") or "inputs"))
        outputs_dir = os.path.normpath(os.path.join(project_dir, config["output"]["dir"]))
        roots.append(inputs_dir)
        ignore.append(os.path.join(outputs_dir, config["output"]["filename"]))
        # output.dirが監視ルート自身（"."等）や祖先のときにディレクトリごと無視すると何も監視できなくなる
        if not any(r == outputs_dir or r.startswith(outputs_dir + os.sep) for r in roots):
            ignore.append(outputs_dir)
        template_value = config["template"]["path"]
        if template_value.endswith(".typ"):
            files.append(resolve_template_path(template_value, tool_dir, project_dir))
    except (Exception, SystemExit):
        pass
    return roots, ignore, files

def _watch_snapshot(roots, ignore, files):
    """監視対象の{パス: (mtime_ns, サイズ)}を返す。.始まりのディレクトリ・ファイル（.git、
    .text-compositor、エディタのスワップファイル等）と末尾~のバックアップは対象外。"""
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    ignored = {norm(p) for p in ignore}
    state = {}

    def record(path):
        try:
            st = os.stat(path)
        except OSError:
            return
        state[path] = (st.st_mtime_ns, st.st_size)

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d != "node_modules"
                           and norm(os.path.join(dirpath, d)) not in ignored]
            for name in filenames:
                path = os.path.join(dirpath, name)
                if name.startswith(".") or name.endswith("~") or norm(path) in ignored:
                    continue
                record(path)
    for path in files:
        record(path)
    return state
