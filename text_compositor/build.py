"""コマンドライン（`text-compositor`）のエントリーポイント。引数の解析と、`--clean`・`--watch`。

ビルドの本体は`project.py`、他の機能は同じパッケージの各モジュールにある。"""
import os
import sys
import shutil
import argparse
import time
from text_compositor.changes import _watch_snapshot, _watch_targets
from text_compositor.config import _load_project_config, _output_pdf_path, _read_config_list, find_config_in_cwd
from text_compositor.deps import ensure_fonts
from text_compositor.document import COMMON_TEMPLATE_NAME
from text_compositor.env_check import check_typst_version, run_env_check
from text_compositor import log
from text_compositor.log import _error, _log_info, _log_success
from text_compositor.project import _build_one

def parse_args():
    parser = argparse.ArgumentParser(description="Markdown -> Typst -> PDF ドキュメントビルダー")
    parser.add_argument("--config", help="設定ファイル(yaml/json)へのパス。省略時はカレントディレクトリの text-compositor.config.yaml/.json を探す。")
    parser.add_argument("--config-list", help="ビルド対象のconfigファイルパスを1行1件で列挙したテキストファイル。空行と'#'で始まる行は無視される。--configとは同時指定できない。相対パスはこのファイル自身の置き場所が基準。")
    parser.add_argument("--check-env", action="store_true",
                         help="ビルドを実行せず、実行環境の前提（依存パッケージ・Typstバージョン・"
                              "フォントキャッシュ・mermaid/plantumlに必要なツール）を確認して終了する（#37）。"
                              "--configと併用するとそのplugins設定を反映する。NGが1件でもあればexit code 1。")
    # 実行時の振る舞い系オプション（#52）。文書の内容（出力先・用紙設定等）に関わる上書きオプションは
    # 「config.yamlが単一の正」という方針とやや相性が悪いため見送り、ログレベルと中間ファイルの
    # 扱いのみをCLIオプション化した（Issue本文で見送りが推奨されていた）。
    parser.add_argument("-q", "--quiet", action="store_true",
                         help="[Info]レベルのログを抑制する（[Warning]/[Error]/[Success]は常に表示）。-vとは同時指定できない。")
    parser.add_argument("-v", "--verbose", action="store_true",
                         help="[Info]に加え、処理中の章やキャッシュ再利用状況など[Verbose]レベルの詳細なログも表示する。-qとは同時指定できない。")
    parser.add_argument("--keep-temp", action="store_true",
                         help="ビルド成功時も中間ファイル（temp_build.typ等、.text-compositor/配下）を削除せずに残す。"
                              "既定ではビルド失敗時のみ残る（デバッグ用）。")
    parser.add_argument("--watch", action="store_true",
                         help="初回ビルド後も終了せず、config・入力ファイル・テンプレートの保存を検知して自動で再ビルドする（#30）。"
                              "ビルドが失敗しても終了せず、次の保存を待つ。Ctrl+Cで終了する。--check-envとは同時指定できない。")
    parser.add_argument("--if-changed", action="store_true",
                         help="出力PDFが、config・入力ファイル・テンプレート・ツール自身のいずれよりも新しい場合はビルドをスキップする"
                              "（makeと同様の更新日時による判定、#151）。既定は従来どおり常に再生成する。"
                              "--clean/--watchとは同時指定できない。")
    parser.add_argument("--clean", action="store_true",
                         help="ビルドせず、生成物を削除して終了する（#151）。削除対象は出力PDFと、"
                              ".text-compositor/配下の中間ファイル（temp_build.typ・_template.typ・_common.typ）。"
                              "図表キャッシュ（.text-compositor/cache/）は残す（--clean-cacheで削除）。")
    parser.add_argument("--clean-cache", action="store_true",
                         help="--cleanの削除対象に、図表キャッシュ（.text-compositor/cache/）も加える。"
                              "単独で指定しても--cleanを含む。再生成コストが高いため別オプションにしている。")
    args = parser.parse_args()
    if args.clean_cache:
        args.clean = True
    if args.quiet and args.verbose:
        parser.error("-q/--quiet と -v/--verbose は同時に指定できません。")
    if args.config and args.config_list:
        parser.error("--config と --config-list は同時に指定できません。")
    if args.check_env and args.config_list:
        parser.error("--check-env と --config-list は同時に指定できません。")
    if args.check_env and args.watch:
        parser.error("--check-env と --watch は同時に指定できません。")
    if args.clean and (args.check_env or args.watch or args.if_changed):
        parser.error("--clean/--clean-cache は --check-env・--watch・--if-changed と同時に指定できません。")
    if args.if_changed and args.watch:
        parser.error("--if-changed と --watch は同時に指定できません。")
    return args

def _config_paths_from_args(args):
    """--config-list/--config/カレントディレクトリ探索から、対象のconfigパス（未指定ならNone）のリストを返す。"""
    if args.config_list:
        config_paths = _read_config_list(args.config_list)
        if not config_paths:
            _error(f"--config-list {args.config_list} に有効なconfigパスがありません。")
            sys.exit(1)
        return config_paths
    return [args.config]

def _clean_one(config_path, include_cache):
    """1つのconfigの生成物を削除する。出力PDFと.text-compositor/直下の中間ファイル（temp_build.typ・
    _template.*）が対象。include_cacheなら図表キャッシュ（.text-compositor/cache/）も削除する。
    パスはビルド時と同じくconfigの置き場所（project_dir）基準で解決する。存在しないものは無視する。"""
    project_dir, config, _ = _load_project_config(config_path)
    work_dir = os.path.join(project_dir, ".text-compositor")
    targets = [_output_pdf_path(project_dir, config), os.path.join(work_dir, "temp_build.typ")]
    if os.path.isdir(work_dir):
        targets += [os.path.join(work_dir, n) for n in sorted(os.listdir(work_dir)) if n.startswith("_template.") or n == COMMON_TEMPLATE_NAME]
    removed = 0
    for path in targets:
        if os.path.isfile(path):
            os.remove(path)
            _log_info(f"Removed: {path}")
            removed += 1
    cache_dir = os.path.join(work_dir, "cache")
    if include_cache and os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        _log_info(f"Removed: {cache_dir}")
        removed += 1
    # 空になった作業ディレクトリは残さない（他のファイルがあれば削除されない）
    try:
        os.rmdir(work_dir)
    except OSError:
        pass
    _log_success(f"Cleaned {removed} item(s): {project_dir}")

def _clean_all(config_paths, include_cache):
    for config_path in config_paths:
        _clean_one(config_path, include_cache)

def build():
    # tool_dir: ツール自身に同梱されたリソース（templates/）の場所。パッケージ化後は
    # text_compositor/ パッケージのディレクトリを指す（#111）。
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    # repo_root: 「クローンして直接叩く」場合のリポジトリルート。requirements.txt探索にのみ使う。
    # pipインストール後はrequirements.txtが同梱されないため、自然に「見つからない」扱いになる。
    repo_root = os.path.dirname(tool_dir)
    args = parse_args()

    # ログの詳細度（#52）。CLI起動時に一度だけプロセスグローバルへ反映する。
    log.set_verbosity(args.quiet, args.verbose)

    if args.check_env:
        sys.exit(run_env_check(repo_root, args.config))

    # cleanは削除のみで、Typstやフォントを必要としない。環境不備やフォントのダウンロードで妨げない。
    if args.clean:
        _clean_all(_config_paths_from_args(args), include_cache=args.clean_cache)
        return

    check_typst_version(repo_root)
    font_dir = ensure_fonts()

    if args.config_list:
        config_paths = _read_config_list(args.config_list)
        if not config_paths:
            _error(f"--config-list {args.config_list} に有効なconfigパスがありません。")
            sys.exit(1)
        if args.watch:
            _watch(tool_dir, repo_root, font_dir, config_paths, keep_temp=args.keep_temp)
            return
        # いずれかのビルドが失敗した時点でsys.exit(1)により停止する（_load_project_config等が担う）。
        for config_path in config_paths:
            print(f"[Build] {config_path}")
            _build_one(tool_dir, repo_root, font_dir, config_path, keep_temp=args.keep_temp,
                       if_changed=args.if_changed)
    elif args.watch:
        config_path = os.path.abspath(args.config) if args.config else find_config_in_cwd()
        if not config_path:
            _error("--config not specified, and no text-compositor.config.yaml/.json found in the current directory.")
            sys.exit(1)
        _watch(tool_dir, repo_root, font_dir, [config_path], keep_temp=args.keep_temp)
    else:
        _build_one(tool_dir, repo_root, font_dir, args.config, keep_temp=args.keep_temp,
                   if_changed=args.if_changed)

# --watch（#30）。watchdog等のファイル監視ライブラリは追加せず、標準ライブラリだけでmtime/サイズを
# ポーリングする（2章の「依存・ダウンロードは最小限」方針。対象は手書きの文書プロジェクトで
# ファイル数が少なく、0.5秒間隔の走査で十分軽いため、OS依存のイベントAPIを持ち込む利点が薄い）。
_WATCH_POLL_SECONDS = 0.5
# エディタの保存は「一時ファイルへ書いてからリネーム」等で複数の変更に分かれることがある。
# 変更検知後、この間隔で走査し直して変化が止まるのを待ってからビルドする。
_WATCH_SETTLE_SECONDS = 0.3

def _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp):
    """1回のビルドを実行し、成否を返す。ビルド内部のエラー終了（sys.exit(1)）や想定外の例外で
    ウォッチ全体を止めないよう握りつぶす（エラー内容は呼び出し先が出力済み）。"""
    try:
        _build_one(tool_dir, repo_root, font_dir, config_path, keep_temp=keep_temp)
        return True
    except SystemExit as e:
        return e.code in (0, None)
    except Exception as e:
        _error(f"Build crashed: {e}")
        return False

def _watch(tool_dir, repo_root, font_dir, config_paths, keep_temp=False):
    """全configを初回ビルドした後、保存を検知したconfigだけを再ビルドし続ける。失敗しても終了せず、
    次の保存を待つ（編集→保存→結果確認の試行を繰り返す用途のため）。Ctrl+Cで終了する。"""
    watched = {}
    try:
        for config_path in config_paths:
            # 走査はビルドの前に行う。ビルド中の保存を取りこぼさず、次のループで検知するため。
            targets = _watch_targets(tool_dir, config_path)
            watched[config_path] = (targets, _watch_snapshot(*targets))
            print(f"[Build] {config_path}")
            _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp)
        _log_info("Watching for changes... (Ctrl+C to stop)")

        while True:
            time.sleep(_WATCH_POLL_SECONDS)
            for config_path in config_paths:
                targets, baseline = watched[config_path]
                current = _watch_snapshot(*targets)
                if current == baseline:
                    continue
                while True:
                    time.sleep(_WATCH_SETTLE_SECONDS)
                    settled = _watch_snapshot(*targets)
                    if settled == current:
                        break
                    current = settled
                changed = sorted(p for p in current if baseline.get(p) != current[p]) + \
                          sorted(p for p in baseline if p not in current)
                shown = ", ".join(os.path.basename(p) for p in changed[:3])
                _log_info(f"Change detected ({shown}{', ...' if len(changed) > 3 else ''}); rebuilding...")
                # configの変更でinputs.dir等が変わり得るため、再ビルドのたびに監視対象を解決し直す
                targets = _watch_targets(tool_dir, config_path)
                watched[config_path] = (targets, _watch_snapshot(*targets))
                print(f"[Build] {config_path}")
                _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp)
                _log_info("Watching for changes... (Ctrl+C to stop)")
    except KeyboardInterrupt:
        _log_info("Watch stopped.")


if __name__ == "__main__":
    build()
