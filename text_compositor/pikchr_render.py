"""HTML出力のPikchrを、Typstのパッケージ`kip`（PikchrのWASM）で、SVGにする（#213）。

PDFと同じ経路（`kip`のプラグイン）のため、Obunzu・PDF・CLI（Python API）で、同じ図になる。Graphviz（graphviz_render.py）と
同じ仕組みで、Typstのコンパイラを使い回す。コードは、`sys.inputs`で渡す（Typstのコードとして解釈されない）。

`kip`の`kip()`関数は、Pikchrの構文エラー（HTMLで返る）をSVGとして読もうとして、`failed to parse SVG`という、原因の分からない
エラーになる。そこで、`kip`が公開するプラグイン（`pikchr-plugin`）を直接呼び、返り値がSVGでなければ、その内容（Pikchr自身の
エラー: 行・位置・原因）を、`panic`で、そのまま出す（templates/_common.typの`render-pikchr`と同じ処理）。
"""
import html
import re
from typing import Optional

from text_compositor.graphviz_render import compiler_for, wrapper_digest
from text_compositor.typst_runtime import typst_lib

# 使うkipの版。`templates/_common.typ`の`@preview/kip:...`・`viewer/scripts/build-dist.js`と、同じ値にする
# （tests/test_pikchr_render.pyが、一致を確かめる）。
KIP_VERSION = "0.1.0"

# 図1つ分のTypstコード。余白なし・背景なし・大きさは図に合わせる。
_WRAPPER = f'''#import "@preview/kip:{KIP_VERSION}": pikchr-plugin
#set page(width: auto, height: auto, margin: 0pt, fill: none)
#let out = str(pikchr-plugin.typst_pikchr(bytes(sys.inputs.code)))
#if not out.trim().starts-with("<svg") {{ panic("Pikchr error: " + out) }}
#image(bytes(out), format: "svg")
'''


class PikchrRenderError(Exception):
    """図にできなかった。`code_line`は、Pikchrのコードの中の行（1始まり）で、分かる場合だけ入る。"""

    def __init__(self, message: str, code_line: Optional[int] = None):
        super().__init__(message)
        self.code_line = code_line


def cache_version() -> str:
    """図のSVGのキャッシュキーに入れる、描画環境の版。kip・Typst・上のTypstコードのどれかが変われば、別のキーになる。"""
    return f"kip{KIP_VERSION}+typst{typst_lib.__version__}+w{wrapper_digest(_WRAPPER)}"


_PANIC_RE = re.compile(r'Pikchr error:\s*(.*)', re.DOTALL)
_PRE_RE = re.compile(r'<pre>\n?(.*?)</pre>', re.DOTALL)
_LINE_RE = re.compile(r'/\*\s*(\d+)\s*\*/')


def _parse_error(text: str) -> PikchrRenderError:
    """Typstのエラー（`panicked with: Pikchr error: <div><pre>...</pre></div>`）から、Pikchrのメッセージと行を取り出す。"""
    m = _PANIC_RE.search(text)
    if not m:
        return PikchrRenderError(text.strip())
    body = m.group(1)
    pre = _PRE_RE.search(body)
    message = html.unescape(pre.group(1) if pre else body).strip()
    # Pikchrは、エラーの前の数行（文脈）を`/*    N */`の形で並べ、最後の行が、エラーの行である
    lines = _LINE_RE.findall(message)
    return PikchrRenderError(message, int(lines[-1]) if lines else None)


def render_svg(code: str) -> str:
    """Pikchrのコードを、SVGの文字列にする。失敗は、`PikchrRenderError`（構文エラーは、Pikchrのコードの行つき）。"""
    try:
        svg = compiler_for(_WRAPPER, "pikchr").compile(format="svg", sys_inputs={"code": code})
    except typst_lib.TypstError as e:
        raise _parse_error(str(e)) from e
    if isinstance(svg, (list, tuple)):
        svg = svg[0]
    return svg.decode('utf-8') if isinstance(svg, (bytes, bytearray)) else str(svg)
