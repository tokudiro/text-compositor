"""TypstコードのPDFへのコンパイルと、Typstのエラー位置の、元ファイルの行への対応づけ（#167など）。"""
import os
import re
import sys
import bisect
import time
import tempfile
from text_compositor.document import COMMON_TEMPLATE_NAME
from text_compositor.env_check import _check_typst_env
from text_compositor.log import _error, _hint, _log_info, _log_success, _warn
from text_compositor.renderer import TypstRenderer

# PyPIの typst パッケージ(typst-py)はコンパイラ本体をプラットフォーム別ホイールに同梱しているため、
# tools/typst.exe のような実行バイナリをリポジトリに持たずに済む（pipがOSごとに正しい版を入れてくれる）。
# PDFを作るとき（Typstのコンパイル）にだけ必要なため、初めて使うときに読み込む（#168）。HTML出力（render_html）と、
# それを使うViewerは、typstを入れなくても動く。


class _LazyTypst:
    """`typst`モジュールの代わり。属性に初めて触れたときに、importする。"""

    def __getattr__(self, name):
        try:
            import typst
        except ImportError as e:
            raise ImportError("The 'typst' package is required to build PDFs (pip install typst==0.15.0). "
                              "It is not needed for HTML output.") from e
        return getattr(typst, name)


typst_lib = _LazyTypst()

# 呼び出し元が、同梱したTypstのパッケージ（`preview/<名前>/<版>/`の形）のフォルダを教える環境変数（#263）。ViewerのZIPは、
# テンプレートが使うパッケージを同梱しており、Electronが、この変数で、ワーカーに教える。あれば、`package_cache_path`に
# 渡し、初回のダウンロードなしで、`@preview/...`のimportが解決できる。CLIは、この変数を使わない（従来どおり、取得して、キャッシュする）。
TYPST_PACKAGES_ENV = "TEXT_COMPOSITOR_TYPST_PACKAGES"


def typst_package_options():
    """`typst.compile`・`typst.Compiler`に渡す、パッケージの置き場所の引数。環境変数が、存在するフォルダを指すときだけ、値がある。"""
    path = os.environ.get(TYPST_PACKAGES_ENV)
    return {"package_cache_path": path} if path and os.path.isdir(path) else {}

# TypstRenderer._emit_srcmapが生成コードへ挿し込む目印行（`// @srcmap {mdファイル}:{md行番号}`）
# を検出する正規表現（#27）。ファイルパス自体にコロンを含みうる（Windowsの絶対パス`C:\...`）ため、
# 末尾の数字グループのみを行番号として貪欲マッチさせ、残り全体をファイルパスとして扱う。
SRCMAP_LINE_RE = re.compile(re.escape(TypstRenderer.SRCMAP_PREFIX) + r'(.+):(\d+)$', re.MULTILINE)
# typst_lib.TypstErrorのメッセージ（codespan_reportingが整形する`┌─ temp_build.typ:12:5`形式）
# から、コンパイル対象ファイル内の行:列を検出する正規表現。
TYPST_ERROR_LOC_RE = re.compile(r'temp_build\.typ:(\d+):\d+')

def _build_srcmap(typst_code):
    """typst_code全体から`// @srcmap`の目印行を集め、[(typstコード上の行番号, mdファイル, md行番号), ...]
    をtypst行番号の昇順で返す（#27）。line_mapping: "off"（既定はblock）で目印が無い場合は空リスト。"""
    return [
        (typst_code.count('\n', 0, m.start()) + 1, m.group(1), int(m.group(2)))
        for m in SRCMAP_LINE_RE.finditer(typst_code)
    ]

def _resolve_srcmap(src_map, typst_line):
    """typst_line以前にある直近の目印から、対応する元のMarkdownの(ファイル, 行番号)を引く（#27）。
    目印より前（テンプレートのpreambleなど）の行はNoneを返す。"""
    linenos = [s[0] for s in src_map]
    idx = bisect.bisect_right(linenos, typst_line) - 1
    return (src_map[idx][1], src_map[idx][2]) if idx >= 0 else None

def _annotate_typst_error(error_text, src_map):
    """Typstのコンパイルエラーメッセージ中の`temp_build.typ:行:列`を#27のsrc_mapで元のMarkdownの
    (ファイル, 行番号)へ逆引きし、ヒントとして追記する。src_mapが空（line_mapping: off、または
    該当行が目印より前）の場合は元のメッセージのまま返す。"""
    hints = []
    seen = set()
    for m in TYPST_ERROR_LOC_RE.finditer(error_text):
        typst_line = int(m.group(1))
        if typst_line in seen:
            continue
        seen.add(typst_line)
        resolved = _resolve_srcmap(src_map, typst_line)
        if resolved:
            md_file, md_line = resolved
            hints.append(f"[Hint] temp_build.typ:{typst_line} corresponds to around {md_file}:{md_line}")
    return error_text + "\n" + "\n".join(hints) if hints else error_text

def _first_error_location(error_text, src_map):
    """Typstの診断中の最初の`temp_build.typ:行:列`を、#27のsrc_mapで元のMarkdownの(ファイル, 行番号)へ
    逆引きする。分からなければNone（Python APIが、診断にfile/lineを付けるために使う。#167）。"""
    for m in TYPST_ERROR_LOC_RE.finditer(error_text):
        resolved = _resolve_srcmap(src_map, int(m.group(1)))
        if resolved:
            return resolved
    return None

def _write_pdf_atomically(out_pdf, data):
    """PDFを、同じディレクトリの一時ファイルへ書いてから置き換える。読む側（GUI）が、書きかけの
    PDFを見ないようにするため（#167）。Windowsでは、読み込み中のファイルへの置き換えが失敗する
    ことがあるため、短く再試行してから、PermissionErrorを返す。"""
    out_dir = os.path.dirname(os.path.abspath(out_pdf))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".pdf", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        for attempt in range(10):
            try:
                os.replace(tmp_path, out_pdf)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.1)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def _compile_with_reused_compiler(temp_typ_path, out_pdf, typst_root, font_dir, compiler_cache, src_map):
    """typst.Compilerを使い回してコンパイルし、Typstの警告を診断として出す（Python API、#167）。
    コンパイラは、(コンパイル対象, --root, フォント)ごとに作り、compiler_cacheへ残す。同じ
    temp_build.typを毎回書き換えてコンパイルしても、内容の変更は反映される（実測）。コンパイル自体は、
    毎回`typst.compile()`を呼ぶ場合の約23 msが、約7 msになる。"""
    key = (temp_typ_path, typst_root, font_dir)
    compiler = compiler_cache.get(key)
    if compiler is None:
        compiler = typst_lib.Compiler(temp_typ_path, root=typst_root, font_paths=[font_dir],
                                       ignore_system_fonts=True, **typst_package_options())
        compiler_cache[key] = compiler
    pdf_bytes, warnings = compiler.compile_with_warnings(format="pdf")
    for w in warnings:
        text = getattr(w, "diagnostic", None) or str(w)
        location = _first_error_location(text, src_map)
        _warn(f"Typst: {getattr(w, 'message', None) or w}",
              file=location[0] if location else None, line=location[1] if location else None,
              detail=_annotate_typst_error(text, src_map))
    _write_pdf_atomically(out_pdf, pdf_bytes)

def _compile_and_cleanup(typst_code, work_dir, outputs_dir, config, typst_root, font_dir, template_copy_path, repo_root,
                          keep_temp=False, *, compiler_cache=None, out_pdf=None):
    """temp_build.typへ書き出してtypstコンパイルし、成功時は使い捨ての中間ファイルを削除する。
    keep_temp=True（--keep-temp、#52）なら成功時も削除せず残す（失敗時は元々常に残る）。
    compiler_cache（Python API、#167）を渡すと、typst.Compilerを使い回し、PDFを原子的に書き出す。
    out_pdfを渡すと、出力先をそこにする（省略時は、config.output.dir/filename）。"""
    temp_typ_path = os.path.join(work_dir, "temp_build.typ")
    with open(temp_typ_path, "w", encoding="utf-8") as f:
        f.write(typst_code)

    # コンパイル失敗時にTypst側の行番号を元のMarkdownへ逆引きするための対応表（#27）。
    src_map = _build_srcmap(typst_code)

    if out_pdf is None:
        out_pdf = os.path.join(outputs_dir, config["output"]["filename"])

    try:
        # ignore_system_fonts=True（#71）。テンプレート（template.typ/slide.typ）は本文フォントを
        # 一貫して"Noto Sans JP"（font_dirに同梱・キャッシュ済み）のみ指定しているため、システム
        # フォントを混ぜる必要が無い。付けないと、テンプレート指定フォントがカバーしない文字
        # （絵文字等）のフォールバック先がOSごとに異なる system フォント構成に左右され、同一入力
        # からでも環境ごとに出力（フォールバックフォントの選択）が変わり得る（9章の決定論的出力の
        # 前提が崩れる）。デフォルトで常に有効にし、config.yaml側に設定項目は設けない（このツールの
        # 「明示性優先」方針に合わせ、フォントを変えたい場合は独自テンプレート（template.path）で
        # 対応する）。
        if compiler_cache is None:
            typst_lib.compile(temp_typ_path, output=out_pdf, root=typst_root, font_paths=[font_dir],
                               ignore_system_fonts=True, **typst_package_options())
        else:
            _compile_with_reused_compiler(temp_typ_path, out_pdf, typst_root, font_dir, compiler_cache, src_map)
        _log_success(f"Generated PDF: {out_pdf}")
    except typst_lib.TypstError as e:
        # str(e)はe.message（例: "unknown variable: foo"）のみで位置情報を持たない。
        # ファイル:行:列を含む整形済み診断（`┌─ temp_build.typ:32:1`形式）はe.diagnosticに
        # 別途入っている（実機確認で判明。#27の行番号マッピングはこちらが無いと機能しない）。
        diagnostic_text = getattr(e, "diagnostic", None) or str(e)
        annotated = _annotate_typst_error(diagnostic_text, src_map)
        location = _first_error_location(diagnostic_text, src_map)
        _error(f"Compile failed: {e}", file=location[0] if location else None,
               line=location[1] if location else None, detail=annotated,
               cli_text=f"Compile failed:\n{annotated}")
        sys.exit(1)
    except PermissionError as e:
        _error(f"Cannot write the PDF (is it open in another program?): {out_pdf} ({e})")
        sys.exit(1)
    except Exception as e:
        _error(f"Execution failed: {e}")
        # 原因が記述ミスではなく環境不備（typstのバージョン不一致等）の可能性があるため、
        # 関連するチェックだけを再実行して診断ヒントを出す（#37。全項目は--check-env参照）。
        diag = _check_typst_env(repo_root)
        if diag.status != "OK":
            _hint(f"[{diag.status}] {diag.name}: {diag.message}")
        sys.exit(1)

    # ビルド成功後、使い捨ての中間ファイルを削除する（12章、#20）。
    # mermaidキャッシュ(cache/)は次回以降のビルドで再利用するため対象外。
    # 失敗時は温存し、生成されたTypstコードをそのままデバッグに使えるようにする。
    if keep_temp:
        _log_info(f"--keep-temp: keeping intermediate files ({temp_typ_path}, {template_copy_path})")
    else:
        os.remove(temp_typ_path)
        os.remove(template_copy_path)
        os.remove(os.path.join(work_dir, COMMON_TEMPLATE_NAME))
