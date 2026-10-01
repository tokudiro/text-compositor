"""数式（LaTeX記法）を、Typstのパッケージ`mitex`で、SVGにする（#183）。

PDFと同じ経路（Typst + mitex）のため、PDF・HTML出力（Viewer）で、同じ数式になる。
LaTeXは、`sys.inputs.latex`で渡す（エスケープが要らず、原稿のLaTeXがTypstのコードとして解釈されない）。
"""
import re
from typing import Optional

from text_compositor.fonts import fonts_signature
from text_compositor.graphviz_render import compiler_for, wrapper_digest
from text_compositor.typst_runtime import typst_lib

# 使うmitexの版。`templates/_common.typ`の`@preview/mitex:...`・`viewer/scripts/build-dist.js`と、同じ値にする
# （tests/test_math_render.pyが、一致を確かめる）。
MITEX_VERSION = "0.2.7"

# inline/blockの正準な種類名（renderer_diagrams.pyのキャッシュパスと共通で使用する）。
KIND_INLINE = "math-inline"
KIND_BLOCK = "math-block"
KINDS = (KIND_INLINE, KIND_BLOCK)

_FUNCS = {
    KIND_INLINE: "mi",
    KIND_BLOCK: "mimath",
}


def kind_for(display_mode: bool) -> str:
    """display_modeの真偽値から、正準なkind文字列を返す。"""
    return KIND_BLOCK if display_mode else KIND_INLINE


def _html_wrapper(kind: str) -> str:
    """数式1つ分のTypstコード。余白なし・透明背景。フォントは、PDFのテンプレートと同じ`Noto Sans JP`。"""
    func = _FUNCS[kind]
    return (f'#import "@preview/mitex:{MITEX_VERSION}": {func}\n'
            '#set page(width: auto, height: auto, margin: 0pt, fill: none)\n'
            '#set text(font: "Noto Sans JP", size: 11pt)\n'
            f'#{func}(sys.inputs.latex)\n')


_WRAPPERS = {kind: _html_wrapper(kind) for kind in KINDS}


class MathRenderError(Exception):
    """数式を描画できなかった。"""

    def __init__(self, message: str):
        super().__init__(message)


def cache_version(kind: str = KIND_INLINE, display_mode: Optional[bool] = None) -> str:
    """数式のSVGのキャッシュキーに入れる、描画環境の版。"""
    if display_mode is not None:
        kind = kind_for(display_mode)
    wrapper = _WRAPPERS[kind]
    return f"mitex{MITEX_VERSION}+{kind}+typst{typst_lib.__version__}+w{wrapper_digest(wrapper)}{fonts_signature()}"


def render_svg(latex: str, kind: str = KIND_INLINE, display_mode: Optional[bool] = None) -> str:
    """LaTeX数式を、SVGの文字列にする。失敗時は`MathRenderError`。"""
    if display_mode is not None:
        kind = kind_for(display_mode)
    wrapper = _WRAPPERS[kind]
    compiler = compiler_for(wrapper, kind)
    try:
        svg = compiler.compile(format="svg", sys_inputs={"latex": latex})
    except typst_lib.TypstError as e:
        msg = getattr(e, "diagnostic", None) or str(e)
        m = re.search(r"error:\s*(.+)$", msg, re.MULTILINE)
        if m:
            raise MathRenderError(m.group(1).strip()) from e
        raise MathRenderError(msg.strip()) from e
    except Exception as e:
        raise MathRenderError(f"{type(e).__name__}: {e}") from e

    if isinstance(svg, (list, tuple)):
        svg = svg[0]
    return svg.decode("utf-8") if isinstance(svg, (bytes, bytearray)) else str(svg)
