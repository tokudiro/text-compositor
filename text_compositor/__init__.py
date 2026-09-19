"""text-compositor: 複数のテキストファイルを、1つのPDFにまとめるツール。

公開API（#167）は、次の名前を`text_compositor`から直接importできる。読み込みは、使うまで遅延させる
（`import text_compositor`自体は軽く、markdown-itやtypstを読み込まない）。

    from text_compositor import Session, build_markdown, BuildResult, Diagnostic
"""
import importlib.metadata as _metadata

try:
    __version__ = _metadata.version("text-compositor")
except _metadata.PackageNotFoundError:  # pipインストールせず、クローンして直接使っている場合
    __version__ = "0+unknown"

_API_NAMES = {"Session": "api", "build_markdown": "api", "BuildResult": "api", "Diagnostic": "diagnostics"}

__all__ = sorted(_API_NAMES) + ["__version__"]


def __getattr__(name):
    module_name = _API_NAMES.get(name)
    if module_name is None:
        raise AttributeError(f"module 'text_compositor' has no attribute {name!r}")
    import importlib
    return getattr(importlib.import_module(f"text_compositor.{module_name}"), name)
