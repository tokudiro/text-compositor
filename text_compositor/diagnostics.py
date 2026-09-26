"""診断（エラー・警告・ヒント・情報）の受け皿（#167）。

CLIは、従来どおり標準出力へ`[Error] ...`の形式で出す。Python API（`api.py`）は、`collect()`の
間だけ、標準出力へは何も出さず、`Diagnostic`のリストとして受け取る。GUIとの通信に標準入出力を
使う常駐ワーカーが、ビルド中の出力で汚れないようにするため、また、GUIが失敗や警告を、文字列の
解析なしに表示できるようにするためである。

GitHub Actions上のCLI実行では、加えて`::warning file=...,line=...::message`形式のワークフロー
コマンドも出す（#29）。GitHub側がこれをPull Requestの差分上へのアノテーションとして表示する。
"""
from __future__ import annotations

import contextlib
import contextvars
import os
from dataclasses import asdict, dataclass
from typing import Iterator, List, Optional

SEVERITIES = ("error", "warning", "hint", "info")

# CLIで標準出力へ出すときの見出し（従来の`[Error]`等と同じ）
_LABELS = {"error": "Error", "warning": "Warning", "hint": "Hint", "info": "Info"}

# GitHub Actionsのワークフローコマンドが持つ注釈の種類。hint/infoに対応する種類は無いため対象外
# （#29はissue本文どおり警告・エラーのみを対象にする）。
_GITHUB_ANNOTATION_KINDS = {"error": "error", "warning": "warning"}


@dataclass(frozen=True)
class Diagnostic:
    """1件の診断。fileとlineは、元のMarkdownの位置で、分かっている場合だけ入る。

    message: 人が読む1〜2行の要約。
    detail: 長い補足（Typstが整形したコンパイルエラー全文など）。無ければNone。
    """
    severity: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class Collector:
    """`collect()`の間に出された診断を、出た順に集める。"""

    def __init__(self) -> None:
        self.items: List[Diagnostic] = []

    def of(self, severity: str) -> List[Diagnostic]:
        return [d for d in self.items if d.severity == severity]

    @property
    def errors(self) -> List[Diagnostic]:
        return self.of("error")

    @property
    def warnings(self) -> List[Diagnostic]:
        return self.of("warning")


# 現在有効なCollector。contextvarsなので、スレッドや非同期処理をまたいでも混ざらない。
_collector: "contextvars.ContextVar[Optional[Collector]]" = contextvars.ContextVar(
    "text_compositor_diagnostics", default=None)


@contextlib.contextmanager
def collect() -> Iterator[Collector]:
    """この間に出された診断を、標準出力へ出さず、Collectorへ集める。入れ子にしてもよい。"""
    collector = Collector()
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


def active() -> bool:
    """`collect()`の中にいるか（診断を標準出力へ出さない状態か）。"""
    return _collector.get() is not None


def _github_escape(text: str, *, is_property: bool) -> str:
    """ワークフローコマンドの値のエスケープ（GitHub公式ドキュメント準拠。#29）。
    メッセージ本体は`%`/`\\r`/`\\n`のみ、`file=`等のプロパティ値はそれに加えて`,`/`:`もエスケープする。"""
    text = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    if is_property:
        text = text.replace(',', '%2C').replace(':', '%3A')
    return text


def _github_relative_path(file: str) -> Optional[str]:
    """GitHub Actionsのアノテーションは、`GITHUB_WORKSPACE`（チェックアウト先）相対のパスでないと
    Pull Requestの差分上に重ならない。このツールは原稿がリポジトリ外にあってもよい設計（3章）のため、
    `GITHUB_WORKSPACE`の外を指す場合はNoneを返し、呼び出し側でファイル指定なしにフォールバックする。"""
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return None
    rel = os.path.relpath(os.path.abspath(file), workspace)
    if rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


def _print_github_annotation(severity: str, message: str, file: Optional[str], line: Optional[int]) -> None:
    """`::warning file=...,line=...::message`形式のワークフローコマンドを標準出力へ出す（#29）。
    GitHub Actions実行時（`GITHUB_ACTIONS=true`）に限り、既存の`[Warning] ...`行へ追加で出す
    （既存のCLI出力自体は変えない）。"""
    kind = _GITHUB_ANNOTATION_KINDS.get(severity)
    if kind is None or os.environ.get("GITHUB_ACTIONS") != "true":
        return
    props = []
    rel_file = _github_relative_path(file) if file else None
    if rel_file:
        props.append(f"file={_github_escape(rel_file, is_property=True)}")
        if line:
            props.append(f"line={line}")
    prefix = f"::{kind} {','.join(props)}::" if props else f"::{kind}::"
    print(f"{prefix}{_github_escape(message, is_property=False)}")


def emit(severity: str, message: str, *, file: Optional[str] = None, line: Optional[int] = None,
         detail: Optional[str] = None, cli_text: Optional[str] = None) -> None:
    """診断を出す。`collect()`の中ならCollectorへ、外（CLI）なら`[Error] message`の形式で標準出力へ。

    cli_text: CLIでの表示を、messageとは別の文字列にしたいとき（既存の出力を変えないため）。
    """
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity: {severity!r}")
    collector = _collector.get()
    if collector is not None:
        collector.items.append(Diagnostic(severity, message, file, line, detail))
        return
    print(f"[{_LABELS[severity]}] {cli_text if cli_text is not None else message}")
    _print_github_annotation(severity, message, file, line)


def error(message: str, **kwargs) -> None:
    emit("error", message, **kwargs)


def warning(message: str, **kwargs) -> None:
    emit("warning", message, **kwargs)


def hint(message: str, **kwargs) -> None:
    emit("hint", message, **kwargs)


def info(message: str, **kwargs) -> None:
    emit("info", message, **kwargs)
