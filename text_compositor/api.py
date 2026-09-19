"""Python API（#167）: 単一のMarkdownファイルを、config.yamlなしでPDFにする。

GUI版Viewer（常駐サブプロセス、`worker.py`）から、繰り返し呼ばれる使い方を主に想定している。

    from text_compositor import Session

    with Session() as session:            # 常駐する間、使い回す（Mermaidのブラウザ・Typstコンパイラ）
        result = session.build("doc.md", "out/doc.pdf")
        if result.ok:
            print(result.pdf_path)
        for d in result.diagnostics:      # 警告・エラー・ヒント（file/lineは、分かる場合だけ）
            print(d.severity, d.message, d.file, d.line)

1回だけなら、`build_markdown("doc.md", "out/doc.pdf")`。

- 標準出力へは何も出さない（診断は`BuildResult.diagnostics`で返す）。失敗しても例外を出さず、`ok=False`で返す。
- 設定は既定値で動き、`template`・`plugins`・`document`・`variables`・`config`で上書きできる。
- 原稿の隣に、作業用の`.text-compositor/`（図表のキャッシュ・中間ファイル）を作る。`outputs/`は作らない。
- PDFは、一時ファイルへ書いてから置き換える（読む側が、書きかけのPDFを見ない）。Windowsでは、開いたままの
  PDFへは置き換えられない。読む側は、全体を読んで閉じるか、ビルドごとに別の出力先を指定する。
"""
from __future__ import annotations

import contextlib
import copy
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from text_compositor import diagnostics
from text_compositor.diagnostics import Diagnostic


@dataclass
class BuildResult:
    """1回のビルドの結果。

    ok: PDFを生成できたか。
    pdf_path: 生成したPDFの絶対パス（失敗時はNone）。
    diagnostics: 出た順の診断（エラー・警告・ヒント・情報）。
    timings_ms: 所要時間（ミリ秒）。total（全体）・render（Markdown→Typstコード。図表の描画を含む）・
        compile（Typstコンパイル、PDFの書き出し、中間ファイルの削除）。失敗した段階以降は入らない。
    """
    ok: bool
    pdf_path: Optional[str] = None
    diagnostics: List[Diagnostic] = field(default_factory=list)
    timings_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "pdf": self.pdf_path,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
        }


# Sessionのbuild()が受け取れる、文書の設定の上書き。config全体（deep_updateで重ねる）も渡せる。
def _single_markdown_config(markdown_path: str, template: str, plugins: Optional[Mapping[str, Any]],
                            document: Optional[Mapping[str, Any]], variables: Optional[Mapping[str, Any]],
                            overrides: Optional[Mapping[str, Any]]) -> dict:
    """単一のMarkdownを1章とする、configを組み立てる。

    既定の`document.cover`は`markdown`（テンプレートの表紙を出さず、Markdownの先頭をそのまま出す）。
    CLIの既定（`none`）は、先頭のタイトルを落とすため、プレビューには向かない。タイトルは、ファイル名。
    """
    from text_compositor import build as _build

    stem = os.path.splitext(os.path.basename(markdown_path))[0]
    config = _build.default_config()
    config["document"].update({
        "title": stem, "subtitle": "", "author": "", "date": "", "cover": "markdown", "toc": False,
    })
    config["output"] = {"filename": "preview.pdf", "dir": "."}
    config["inputs"] = {"dir": ".", "files": None}
    config["template"] = {"path": template}
    config["chapters"] = [os.path.basename(markdown_path)]
    if plugins:
        config["plugins"] = dict(plugins)
    if variables:
        config["variables"] = dict(variables)
    if document:
        _build.deep_update(config["document"], copy.deepcopy(dict(document)))
    if overrides:
        _build.deep_update(config, copy.deepcopy(dict(overrides)))
    return config


class Session:
    """常駐して、繰り返しビルドするためのもの。呼び出しをまたいで、次を使い回す。

    - Mermaid用のヘッドレスブラウザ（図1つあたり、約1.3秒 → 約18 ms）
    - typst.Compiler（コンパイルが、約23 ms → 約7 ms）

    スレッドセーフだが、ビルドは1つずつ直列に実行する。使い終わったら、`close()`する（`with`も可）。
    """

    def __init__(self, *, font_dir: Optional[str] = None) -> None:
        self._font_dir = font_dir
        self._mermaid = None
        self._compilers: dict = {}
        self._lock = threading.Lock()
        self._closed = False

    # -- 公開 ------------------------------------------------------------

    def build(self, markdown_path: str, output_pdf: Optional[str] = None, *,
              template: str = "template",
              plugins: Optional[Mapping[str, Any]] = None,
              document: Optional[Mapping[str, Any]] = None,
              variables: Optional[Mapping[str, Any]] = None,
              config: Optional[Mapping[str, Any]] = None,
              keep_temp: bool = False) -> BuildResult:
        """Markdownファイルを、PDFにする。失敗しても例外は出さず、`ok=False`の結果を返す。

        markdown_path: 対象のMarkdownファイル。画像等の相対パスは、このファイルの場所が基準。
        output_pdf: 出力先。省略時は、原稿の隣の`.text-compositor/preview.pdf`。
        template: 同梱テンプレートの名前（`template`・`slide`・`paper`）、または`.typ`ファイルのパス。
        plugins: 図表プラグインの上書き。例: `{"mermaid": False, "plantuml": False}`。
        document: `document:`の上書き。例: `{"toc": True, "title": "仕様書"}`。
        variables: `{{KEY}}`の置換表（config.yamlの`variables:`と同じ形式）。
        config: config全体への上書き（上の引数より後に重ねる）。上級者向け。
        keep_temp: 成功時も、中間ファイル（`temp_build.typ`等）を残す（デバッグ用）。
        """
        started = time.perf_counter()
        timings: Dict[str, float] = {}
        with self._lock, diagnostics.collect() as collected:
            ok, pdf_path = self._build_locked(
                markdown_path, output_pdf, template, plugins, document, variables, config, keep_temp, timings)
        timings["total"] = (time.perf_counter() - started) * 1000.0
        return BuildResult(ok=ok, pdf_path=pdf_path if ok else None, diagnostics=list(collected.items),
                           timings_ms=timings)

    def close(self) -> None:
        """使い回している資源（Mermaidのブラウザ）を片付ける。何度呼んでもよい。"""
        with self._lock:
            if self._mermaid is not None:
                self._mermaid.close()
            self._compilers.clear()
            self._closed = True

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 内部 ------------------------------------------------------------

    def _build_locked(self, markdown_path, output_pdf, template, plugins, document, variables, overrides,
                      keep_temp, timings):
        from text_compositor import build as _build

        if self._closed:
            diagnostics.error("The session is closed.")
            return False, None
        md_path = os.path.abspath(markdown_path)
        if not os.path.isfile(md_path):
            diagnostics.error(f"Markdown file not found: {md_path}", file=md_path)
            return False, None

        project_dir = os.path.dirname(md_path)
        out_pdf = os.path.abspath(output_pdf) if output_pdf else os.path.join(
            project_dir, ".text-compositor", "preview.pdf")
        tool_dir = os.path.dirname(os.path.abspath(_build.__file__))
        repo_root = os.path.dirname(tool_dir)

        try:
            # ビルド中の標準出力への書き込み（ライブラリや外部プロセスの出力）は、標準エラーへ回す。
            # 標準入出力で通信する常駐ワーカーの、通信路を壊さないため。
            with contextlib.redirect_stdout(sys.stderr):
                config = _single_markdown_config(md_path, template, plugins, document, variables, overrides)
                if self._font_dir is None:
                    self._font_dir = _build.ensure_fonts()
                if self._mermaid is None:
                    self._mermaid = _build.MermaidBrowser()
                _build._build_project(
                    tool_dir, repo_root, self._font_dir, project_dir, config, config["chapters"],
                    keep_temp=keep_temp, mermaid_browser=self._mermaid, compiler_cache=self._compilers,
                    out_pdf=out_pdf, timings=timings)
            return True, out_pdf
        except SystemExit as e:
            # 既存のビルド処理は、エラーを出した後に、sys.exit(1)で止まる。エラーは、診断に入っている。
            if not diagnostics_has_error():
                diagnostics.error(f"The build was aborted (exit code {e.code}).")
            return False, None
        except Exception as e:  # 想定外の例外でも、常駐プロセスを落とさない
            diagnostics.error(f"Unexpected error: {type(e).__name__}: {e}", detail=traceback.format_exc())
            return False, None
        finally:
            # ブラウザの起動に失敗した等で、途中の状態が残っていれば、片付けて次回に備える
            if self._mermaid is not None and self._mermaid.page is None:
                self._mermaid.close()


def diagnostics_has_error() -> bool:
    """現在の`collect()`に、エラーが入っているか。"""
    collector = diagnostics._collector.get()
    return bool(collector and collector.errors)


def build_markdown(markdown_path: str, output_pdf: Optional[str] = None, **options: Any) -> BuildResult:
    """Markdownファイルを1回だけPDFにする（内部で、使い捨てのSessionを作る）。引数は、`Session.build`と同じ。"""
    with Session() as session:
        return session.build(markdown_path, output_pdf, **options)
