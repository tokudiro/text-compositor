"""数式（LaTeX記法）を、Typstのパッケージ`mitex`で、SVGにする（#183）。

PDFと同じ経路（Typst + mitex）のため、PDF・HTML出力（Viewer）で、同じ数式になる。
LaTeXは、`sys.inputs.latex`で渡す（エスケープが要らず、原稿のLaTeXがTypstのコードとして解釈されない）。
"""
import os
import re

from text_compositor.graphviz_render import compiler_for, wrapper_digest
from text_compositor.typst_runtime import typst_lib

# 使うmitexの版。`templates/_common.typ`の`@preview/mitex:...`・`viewer/scripts/build-dist.js`と、同じ値にする
# （tests/test_math_render.pyが、一致を確かめる）。
MITEX_VERSION = "0.2.7"

# 図1つ分のTypstコード。余白なし・透明背景。フォントは、PDFのテンプレートと同じ`Noto Sans JP`。
_WRAPPER_INLINE = f'''#import "@preview/mitex:{MITEX_VERSION}": mi
#set page(width: auto, height: auto, margin: 0pt, fill: none)
#set text(font: "Noto Sans JP", size: 11pt)
#mi(sys.inputs.latex)
'''

_WRAPPER_BLOCK = f'''#import "@preview/mitex:{MITEX_VERSION}": mimath
#set page(width: auto, height: auto, margin: 0pt, fill: none)
#set text(font: "Noto Sans JP", size: 11pt)
#mimath(sys.inputs.latex)
'''


class MathRenderError(Exception):
    """数式を描画できなかった。"""

    def __init__(self, message: str):
        super().__init__(message)


def cache_version(display_mode: bool = False) -> str:
    """数式のSVGのキャッシュキーに入れる、描画環境の版。"""
    wrapper = _WRAPPER_BLOCK if display_mode else _WRAPPER_INLINE
    mode_str = "block" if display_mode else "inline"
    return f"mitex{MITEX_VERSION}+{mode_str}+typst{typst_lib.__version__}+w{wrapper_digest(wrapper)}"


def render_svg(latex: str, display_mode: bool = False) -> str:
    """LaTeX数式を、SVGの文字列にする。失敗時は`MathRenderError`。"""
    wrapper = _WRAPPER_BLOCK if display_mode else _WRAPPER_INLINE
    kind = "mitex_block" if display_mode else "mitex_inline"
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
