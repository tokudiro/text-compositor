"""ログの詳細度（-q/-v）と、エラー・警告・ヒント・情報の出し口。

プロセスグローバルな状態（詳細度）を1か所に閉じ込めるための、依存の最下層。"""
from text_compositor import diagnostics

# ログの詳細度（#52）。CLIの-q/-vで一度だけ設定するプロセスグローバルな状態。config.yamlに
# 書くべき文書内容ではなく実行時の振る舞いのため、CLIオプションのみで制御する（config.yaml側の
# 設定項目は設けない）。--config-listで複数ビルドをまとめて実行する場合もCLI全体で1つの
# 詳細度に統一される。既定は[Info]まで表示、[Warning]/[Error]/[Success]は常に表示する。
_QUIET = False
_VERBOSE = False

# エラー・警告・ヒント。text_compositor.diagnostics.collect()の外（CLI）では、従来どおり
# `[Error] ...`等を標準出力へ出す。中（Python API）では、標準出力へは出さず、構造化して集める（#167）。
_error = diagnostics.error
_warn = diagnostics.warning
_hint = diagnostics.hint

def set_verbosity(quiet, verbose):
    """CLI起動時に、-q/-vをプロセスグローバルへ反映する。他のモジュールは、_QUIET/_VERBOSEを直接書き換えない。"""
    global _QUIET, _VERBOSE
    _QUIET = quiet
    _VERBOSE = verbose

def _log_info(msg):
    # APIは、-qの影響を受けず、常に集める（呼び出し側が重大度で絞れる）
    if diagnostics.active() or not _QUIET:
        diagnostics.info(msg)

def _log_verbose(msg):
    if _VERBOSE and not diagnostics.active():
        print(f"[Verbose] {msg}")

def _log_success(msg):
    """CLI専用の完了表示。Python APIは、結果オブジェクト（BuildResult）で成否を返すため出さない。"""
    if not diagnostics.active():
        print(f"[Success] {msg}")
