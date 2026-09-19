"""診断（エラー・警告・ヒント・情報）の受け皿（#167）。

CLIは、従来どおり標準出力へ`[Error] ...`の形式で出す。Python API（`api.py`）は、`collect()`の
間だけ、標準出力へは何も出さず、`Diagnostic`のリストとして受け取る。GUIとの通信に標準入出力を
使う常駐ワーカーが、ビルド中の出力で汚れないようにするため、また、GUIが失敗や警告を、文字列の
解析なしに表示できるようにするためである。
"""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import asdict, dataclass
from typing import Iterator, List, Optional

SEVERITIES = ("error", "warning", "hint", "info")

# CLIで標準出力へ出すときの見出し（従来の`[Error]`等と同じ）
_LABELS = {"error": "Error", "warning": "Warning", "hint": "Hint", "info": "Info"}


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


def error(message: str, **kwargs) -> None:
    emit("error", message, **kwargs)


def warning(message: str, **kwargs) -> None:
    emit("warning", message, **kwargs)


def hint(message: str, **kwargs) -> None:
    emit("hint", message, **kwargs)


def info(message: str, **kwargs) -> None:
    emit("info", message, **kwargs)
