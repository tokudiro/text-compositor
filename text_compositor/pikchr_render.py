"""PikchrのコードをSVGにする。Typstのパッケージ`kip`（PikchrのWASM）を使う（#213）。PDF・HTML出力が、同じSVGを使う（#474）。

PDFと同じ経路（`kip`のプラグイン）のため、Obunzu・PDF・CLI（Python API）で、同じ図になる。Graphviz（graphviz_render.py）と
同じ仕組みで、Typstのコンパイラを使い回す。コードは、`sys.inputs`で渡す（Typstのコードとして解釈されない）。

`kip`の`kip()`関数は、Pikchrの構文エラー（HTMLで返る）をSVGとして読もうとして、`failed to parse SVG`という、原因の分からない
エラーになる。そこで、`kip`が公開するプラグイン（`pikchr-plugin`）を直接呼び、返り値がSVGでなければ、その内容（Pikchr自身の
エラー: 行・位置・原因）を、`panic`で、そのまま出す（templates/_common.typの`render-pikchr`と同じ処理）。
"""
import base64
import html
import re
from typing import Optional

from text_compositor.fonts import fonts_signature
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


# SVGの形の版。v2: Typstが書き出した「入れ物」のSVG（Pikchrの図を、画像として入れ子にしたもの）ではなく、中のPikchrのSVGそのものを返す（#474）。
# 入れ子のSVGの文字は、TypstがPDFへ埋め込むときに描かれない（箱だけが残る）ため。
_SVG_FORM = "v2"


def cache_version() -> str:
    """図のSVGのキャッシュキーに入れる、描画環境の版。kip・Typst・上のTypstコード・SVGの形のどれかが変われば、別のキーになる。"""
    return f"kip{KIP_VERSION}+typst{typst_lib.__version__}+w{wrapper_digest(_WRAPPER)}+{_SVG_FORM}{fonts_signature()}"


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


_WRAPPER_TAG_RE = re.compile(r'<svg ([^>]*)>')
_IMAGE_RE = re.compile(r'<image [^>]*xlink:href="data:image/svg\+xml;base64,([^"]+)"')


def _pikchr_svg(wrapped: str) -> str:
    """Typstが書き出したSVG（Pikchrの図を、base64の画像として入れ子にしたもの）から、中のPikchrのSVGを取り出す。
    中のSVGは、viewBoxだけで、幅・高さを持たない。入れ物のSVGが持つ幅・高さ（pt）を、そのまま付ける（図の大きさを変えないため）。"""
    tag = _WRAPPER_TAG_RE.match(wrapped)
    image = _IMAGE_RE.search(wrapped)
    size = tag and (re.search(r'\swidth="([^"]+)"', tag.group(1)), re.search(r'\sheight="([^"]+)"', tag.group(1)))
    if not (image and size and size[0] and size[1]):
        raise PikchrRenderError("Unexpected SVG from kip: the Pikchr drawing could not be found in it.")
    inner = base64.b64decode(image.group(1)).decode('utf-8')
    if not inner.lstrip().startswith('<svg'):
        raise PikchrRenderError("Unexpected SVG from kip: the embedded drawing is not an SVG.")
    return inner.replace('<svg', f'<svg width="{size[0].group(1)}" height="{size[1].group(1)}"', 1)


def render_svg(code: str) -> str:
    """Pikchrのコードを、SVGの文字列にする。失敗は、`PikchrRenderError`（構文エラーは、Pikchrのコードの行つき）。"""
    try:
        svg = compiler_for(_WRAPPER, "pikchr").compile(format="svg", sys_inputs={"code": code})
    except typst_lib.TypstError as e:
        raise _parse_error(str(e)) from e
    if isinstance(svg, (list, tuple)):
        svg = svg[0]
    return _pikchr_svg(svg.decode('utf-8') if isinstance(svg, (bytes, bytearray)) else str(svg))
