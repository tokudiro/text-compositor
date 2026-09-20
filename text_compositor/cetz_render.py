"""```cetz・```fletcherフェンスを、Typstのパッケージ`cetz`・`fletcher`で描く（#236）。

原稿に書かれたコードは、Typstのコードである。そのまま実行すると、原稿が、任意のファイルの読み込み（`read`・`import`など）や、
ネットワーク越しのパッケージの取得をできてしまう。AIが書いた原稿を、レビューなしで入れる事故を防ぐため、コードを、`eval`に
文字列として渡し、次の3つで制限する（`typst-exec`と違い、`reviewed/`配下には限らない。仕様書8章）。

1. `eval`の`scope`で、ファイルを読む関数（`read`・`json`・`csv`・`yaml`・`toml`・`xml`・`cbor`・`bibliography`・`plugin`・`pdf.embed`）と、
   `eval`・`std`を、エラーにする（`std.read`で、迂回されないように）。
2. `import`・`include`は、文字列・コメントを除いて検出し、実行の前にエラーにする（`check_code`）。
3. Typstの`--root`で、原稿のフォルダの外は、読めない。HTML出力は、空のフォルダを`--root`にする。

図の描画のコード（PDFのフェンスと、HTML出力）は、同じ`figure_body`から作る。HTML出力は、Graphviz・Pikchrと同じ仕組み
（`graphviz_render.compiler_for`）で、同梱のTypstで、SVGにする。コードは、`sys.inputs`で渡す。
"""
import re
from typing import List, Optional, Tuple

from text_compositor.graphviz_render import compiler_for, wrapper_digest
from text_compositor.typst_literal import _typst_multiline_literal
from text_compositor.typst_runtime import typst_lib

# 使う版。`viewer/scripts/build-dist.js`と、同じ値にする（tests/test_cetz_render.pyが、一致を確かめる）。
# fletcherは、内部で、cetz 0.3.4とoxifmtに依存する（推移的な依存も、同梱する。build-dist.js）。
CETZ_VERSION = "0.5.2"
FLETCHER_VERSION = "0.5.8"

KINDS = ("cetz", "fletcher")
LABELS = {"cetz": "CeTZ", "fletcher": "Fletcher"}

# 実行を禁じる関数。呼ぶと、原因の分かるエラー（`panic`）になる。
_DENIED = ("read", "json", "csv", "yaml", "toml", "xml", "cbor", "eval", "plugin", "bibliography")


def figure_body(kind: str, code_expr: str) -> str:
    """図を`fig`に束ねる、Typstのコード（コードモードの文の並び）。`code_expr`は、原稿のコードを表す、Typstの式
    （PDF: 文字列リテラル。HTML出力: `sys.inputs.code`）。"""
    label = LABELS[kind]
    denied = ", ".join(f'"{name}"' for name in _DENIED)
    head = (f'let deny(name) = (..args) => panic(name + "() is not available in {label} figures")\n'
            f'let denied = ({denied}).map(name => (name, deny(name))).to-dict()\n'
            'let blocked = (..denied, pdf: (embed: deny("pdf.embed")), std: denied)\n')
    if kind == "cetz":
        return (f'import "@preview/cetz:{CETZ_VERSION}"\n{head}'
                'let scope = (..dictionary(cetz.draw), cetz: cetz, ..blocked)\n'
                f'let fig = cetz.canvas({{ eval({code_expr}, mode: "code", scope: scope) }})\n')
    # fletcherは、コードを、`diagram(...)`の引数として書く（`node(...)`・`edge(...)`・`spacing: 3em`など）。
    # 末尾の行コメントが、閉じ括弧を巻き込まないように、改行で挟む。
    return (f'import "@preview/fletcher:{FLETCHER_VERSION}" as fletcher: diagram, node, edge\n{head}'
            'let scope = (diagram: diagram, node: node, edge: edge, shapes: fletcher.shapes, fletcher: fletcher, ..blocked)\n'
            f'let fig = eval("diagram(\\n" + {code_expr} + "\\n)", mode: "code", scope: scope)\n')


def _html_wrapper(kind: str) -> str:
    """図1つ分のTypstコード。余白は少し（線の端が欠けないように）・背景なし・大きさは図に合わせる。
    フォントは、PDFのテンプレートと同じ`Noto Sans JP`。文字の大きさは、PDFの本文に近い値にした。"""
    return ('#set page(width: auto, height: auto, margin: 4pt, fill: none)\n'
            '#set text(font: "Noto Sans JP", size: 11pt)\n'
            f'#{{\n{figure_body(kind, "sys.inputs.code")}fig\n}}\n')


_WRAPPERS = {kind: _html_wrapper(kind) for kind in KINDS}


def cache_version(kind: str) -> str:
    """図のSVGのキャッシュキーに入れる、描画環境の版。パッケージ・Typst・上のTypstコードのどれかが変われば、別のキーになる。"""
    version = CETZ_VERSION if kind == "cetz" else f"{FLETCHER_VERSION}+cetz{CETZ_VERSION}"
    return f"{kind}{version}+typst{typst_lib.__version__}+w{wrapper_digest(_WRAPPERS[kind])}"


def pdf_source(kind: str, code: str, width: Optional[str] = None, height: Optional[str] = None) -> str:
    """PDFに埋め込む、図のTypstコード。図が、行の幅より広ければ、幅に合わせて縮小する（拡大はしない。Graphvizの`render-graph()`と同じ）。
    width・heightを指定したら、その大きさに合わせて、拡大・縮小する（縦横比は保つ。両方なら、その枠に収まる大きさ。文字が歪むため、引き伸ばさない）。
    テンプレートの補助関数にしない: 生成コードが読み込むテンプレートの公開名を増やすと、既存のカスタムテンプレートが壊れるため。"""
    body = figure_body(kind, _typst_multiline_literal(code))
    if width or height:
        # 割合（`50%`）は、幅の基準を行の幅、高さの基準を残りの高さにする
        w = f'({_relative(width, "size.width")})' if width else "none"
        h = f'({_relative(height, "size.height")})' if height else "none"
        fit = (f'let (w, h) = ({w}, {h})\n'
               '  let m = measure(fig)\n'
               '  let s = if w != none and h != none { calc.min(w / m.width, h / m.height) }\n'
               '    else if w != none { w / m.width } else { h / m.height }\n'
               '  scale(s * 100%, reflow: true, fig)')
    else:
        fit = ('let m = measure(fig)\n'
               '  if m.width > size.width { scale(size.width / m.width * 100%, reflow: true, fig) } else { fig }')
    body = "\n".join("  " + line if line else line for line in body.splitlines())
    return (f'#align(center)[#{{\n{body}\n'
            f'  layout(size => context {{\n  {fit}\n  }})\n'
            '}]\n\n')


def _relative(value: str, base: str) -> str:
    """フェンスの`width=`・`height=`の値（`8cm`・`50%`）を、Typstの長さの式にする。"""
    value = value.strip()
    return f'{value[:-1]} * 1% * {base}' if value.endswith('%') else value


class FigureCodeError(Exception):
    """原稿のコードに、使えない記法がある。`code_line`は、コードの中の行（1始まり）。"""

    def __init__(self, message: str, code_line: Optional[int] = None):
        super().__init__(message)
        self.code_line = code_line


_IDENT_RE = re.compile(r'[^\W\d][\w-]*')
_FORBIDDEN = ("import", "include")


def check_code(code: str) -> None:
    """`import`・`include`を含む原稿を、`FigureCodeError`にする。
    Typstを、コード・マークアップ・文字列・コメントに分けて読み、コードの中の予約語だけを見る（文字列・コメント・rawの中と、
    `[include]`のようなマークアップの本文の語は、対象外）。マークアップの中で`#`が現れたら、その`[...]`の終わりまでを、
    コードとして読む（`#f({ import "x" })`のような、括弧の中のコードを、見逃さないため）。判断に迷う書き方は、エラー側に倒す。"""
    n, i, line = len(code), 0, 1
    # 各段は、'code'・'markup'（`[...]`の中）・'hash'（`#`を見た後の`[...]`）。closersは、その段を閉じる文字
    stack: List[str] = ["code"]
    closers: List[str] = [""]

    def fail(word: str, at: int) -> None:
        raise FigureCodeError(
            f"'{word}' cannot be used in a cetz/fletcher figure: the drawing functions are already available, "
            "and files and packages cannot be loaded.", at)

    while i < n:
        c = code[i]
        scanning = stack[-1] != "markup"
        if c == '\n':
            line += 1
            i += 1
        elif code.startswith('//', i):
            end = code.find('\n', i)
            i = n if end < 0 else end
        elif code.startswith('/*', i):
            depth, j = 1, i + 2
            while j < n and depth:
                if code.startswith('/*', j):
                    depth, j = depth + 1, j + 2
                elif code.startswith('*/', j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            line += code.count('\n', i, j)
            i = j
        elif c == '"' and scanning:
            j = i + 1
            while j < n and code[j] != '"':
                j += 2 if code[j] == '\\' else 1
            line += code.count('\n', i, j)
            i = j + 1
        elif c == '`':
            # rawブロック（```で囲むものを含む）。中身は、コードではない
            ticks = len(re.match(r'`+', code[i:]).group(0))
            end = code.find('`' * ticks, i + ticks)
            end = n if end < 0 else end + ticks
            line += code.count('\n', i, end)
            i = end
        elif c == '\\' and not scanning:
            i += 2
        elif c == '#' and not scanning:
            stack[-1] = "hash"
            i += 1
        elif c == '[':
            stack.append("markup")
            closers.append("]")
            i += 1
        elif c in "({" and scanning:
            stack.append("code")
            closers.append(')' if c == '(' else '}')
            i += 1
        elif c == closers[-1] and len(stack) > 1:
            stack.pop()
            closers.pop()
            i += 1
        elif scanning:
            m = _IDENT_RE.match(code, i)
            if m:
                if m.group(0) in _FORBIDDEN:
                    fail(m.group(0), line)
                i = m.end()
            else:
                i += 1
        else:
            i += 1


class FigureRenderError(Exception):
    """図にできなかった。"""


_HINT_RE = re.compile(r'^\s*=\s*hint:\s*(.+)$', re.MULTILINE)


def render_svg(kind: str, code: str) -> str:
    """コードを、SVGの文字列にする。失敗は、`FigureCodeError`（使えない記法）・`FigureRenderError`（Typstのエラー）。
    Typstのエラーは、`eval`の中の位置を含まないため、メッセージ（と、あれば、ヒント）だけを出す。"""
    check_code(code)
    try:
        svg = compiler_for(_WRAPPERS[kind], kind).compile(format="svg", sys_inputs={"code": code})
    except typst_lib.TypstError as e:
        message = str(e).strip()
        hints = _HINT_RE.findall(getattr(e, "diagnostic", None) or "")
        raise FigureRenderError("\n".join([message, *(f"hint: {h.strip()}" for h in hints)])) from e
    if isinstance(svg, (list, tuple)):   # 複数ページには、ならない（ページの大きさは、図に合わせる）。念のため
        svg = svg[0]
    return svg.decode('utf-8') if isinstance(svg, (bytes, bytearray)) else str(svg)
