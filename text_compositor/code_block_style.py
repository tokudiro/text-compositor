"""PDFのコードブロックの装飾（#511）。

コードブロック（Typstの`raw`の`block: true`）を、背景つきの枠で包む。包む処理は、テンプレートのshowルールではなく、
ここ（Pythonが、Typstのコードを出すとき）で行う。理由: Typstのshowルールは、重ねがけされる（外側と内側の
`show raw.where(block: true)`が、両方効く。実測）。章ごとの上書きを、章の中のshowルールで実現すると、テンプレートの
ルールと重なって、背景が二重になる。Pythonで包めば、どのテンプレート（独自テンプレートを含む）でも、同じに動く。
"""

import re
import sys
from dataclasses import dataclass
from typing import Optional

from text_compositor.log import _error

# コードの等幅フォント。Noto Sans Mono CJK JP（deps.pyが取得する）は、コードの中の日本語も、半角の2倍の幅に揃える。
# 取得できなかったときのために、Typst内蔵のDejaVu Sans Monoを、2番目に置く。
# 同梱テンプレートの`_common.typ`の`code-font`と、同じ値（tests/test_code_block_style.pyが確かめる）。
CODE_FONTS = ("Noto Sans Mono CJK JP", "DejaVu Sans Mono")

# 背景は、HTML出力の`--code-bg`（ライトテーマ）と同じ。枠線は、既定では付けない（HTML出力と同じ）。
BACKGROUND = "#f6f8fa"
INSET = "0.6em"
RADIUS = "3pt"

# 枠線の既定値（`border: true`と、`color`・`width`の片方だけを書いたとき）。色は、HTML出力の罫線の色（`--line`）、
# 太さは、CSSの`1px`に相当する。
DEFAULT_BORDER_COLOR = "#d1d9e0"
DEFAULT_BORDER_WIDTH = "0.75pt"

# 設定`code_block`（#511）。`document:`・section・章（`chapters[]`）に書け、優先順位は「章 ＞ section ＞ `document:`」。
#   code_block: false            # この範囲では、装飾しない（すでにコードを装飾しているテンプレートなどのため）
#   code_block:
#     font_size: 8pt             # コードの大きさ（数値＋pt）。省略時は、Typstの既定（本文の0.8倍）
#     border: true               # 既定の色・太さの枠線。`false`で、枠線なし（既定）
#     border: {color: "#d1d9e0", width: 0.75pt}   # 片方だけを書くと、もう片方は既定値
# 誤りは、エラーにして止める（`csv_header`・aggregateの`font_size`と同じ）。
_KEYS = ("border", "font_size")
_BORDER_KEYS = ("color", "width")
_LENGTH_RE = re.compile(r"\d+(\.\d+)?pt")   # front-matterの`font_size`・aggregateの`font_size`と同じ書式
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
# Typstの色の名前（`rgb()`に包まず、そのまま渡せるもの。`TypstRenderer._color_to_typst`と同じ扱い）。
TYPST_COLOR_NAMES = frozenset(
    "black gray silver white navy blue aqua teal eastern purple fuchsia maroon red orange yellow olive green lime".split())


@dataclass(frozen=True)
class CodeBlockStyle:
    """ある章に効く、コードブロックの装飾の実効値。`border_color`・`border_width`は、枠線がないとき`None`。"""
    enabled: bool = True
    border_color: Optional[str] = None
    border_width: Optional[str] = None
    font_size: Optional[str] = None


def _fail(message):
    _error(message)
    sys.exit(1)


def _parse_length(value, where, key):
    if not isinstance(value, str) or not _LENGTH_RE.fullmatch(value):
        _fail(f"{where}: {key} must look like '8pt' or '0.75pt' (got {value!r}).")
    return value


def _parse_border(value, where):
    """`border`の値を、検証して返す。`false`は`False`（枠線なし）、`true`は`{}`（既定の色・太さ）、
    マッピングは、書かれたキーだけの辞書。"""
    if isinstance(value, bool):
        return {} if value else False
    if not isinstance(value, dict):
        _fail(f"{where}: border must be true, false or a mapping with 'color' and 'width' (got {value!r}).")
    unknown = sorted(str(k) for k in value if k not in _BORDER_KEYS)
    if unknown:
        _fail(f"{where}: border has unknown key(s) {', '.join(unknown)}. Allowed keys: {', '.join(_BORDER_KEYS)}.")
    border = {}
    if "color" in value:
        color = value["color"]
        if not isinstance(color, str) or not (_HEX_COLOR_RE.fullmatch(color) or color in TYPST_COLOR_NAMES):
            _fail(f"{where}: border color must be a color like '#d1d9e0' or a Typst color name such as 'gray' (got {color!r}).")
        border["color"] = color
    if "width" in value:
        border["width"] = _parse_length(value["width"], where, "border width")
    return border


def parse_code_block(value, where):
    """設定`code_block`の1つの階層の値を検証して、書かれた項目だけの辞書にする。省略（`None`）は`{}`。
    `false`は`{"enabled": False}`。`true`・マッピングは、`enabled: True`を含む（上の階層で`false`でも、
    この階層では有効にする）。`border`は、`False`か、書かれたキーだけの辞書。"""
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"enabled": value}
    if not isinstance(value, dict):
        _fail(f"{where}: code_block must be true, false or a mapping (got {value!r}).")
    unknown = sorted(str(k) for k in value if k not in _KEYS)
    if unknown:
        _fail(f"{where}: code_block has unknown key(s) {', '.join(unknown)}. Allowed keys: {', '.join(_KEYS)}.")
    spec = {"enabled": True}
    if "font_size" in value:
        spec["font_size"] = _parse_length(value["font_size"], where, "font_size")
    if "border" in value:
        spec["border"] = _parse_border(value["border"], where)
    return spec


def merge_code_block(base, override):
    """上の階層（base）に、下の階層（override）を、キー単位で重ねる（`table_header`と同じ）。`border`は、どちらも
    マッピングのとき、色・太さも、キー単位で重ねる（`border: true`は、上の階層の色・太さを、そのまま残す）。"""
    merged = dict(base)
    for key in ("enabled", "font_size"):
        if key in override:
            merged[key] = override[key]
    if "border" in override:
        below, above = override["border"], base.get("border")
        merged["border"] = {**above, **below} if isinstance(below, dict) and isinstance(above, dict) else below
    return merged


def resolve_code_block(spec):
    """重ねた結果（`parse_code_block`・`merge_code_block`の辞書）から、既定値を補って、実効値にする。"""
    border = spec.get("border")
    has_border = isinstance(border, dict)
    return CodeBlockStyle(
        enabled=spec.get("enabled", True),
        border_color=border.get("color", DEFAULT_BORDER_COLOR) if has_border else None,
        border_width=border.get("width", DEFAULT_BORDER_WIDTH) if has_border else None,
        font_size=spec.get("font_size"),
    )


def _typst_color(value):
    """設定の色（`#rgb`などの16進、またはTypstの色の名前）を、Typstの色の式にする。"""
    return f'rgb("{value}")' if value.startswith("#") else value


def wrap_code_block(raw_typst, style=None):
    """`#raw(..., block: true)`のTypstコードを、背景つきの枠と、等幅フォントで包んだコードにする。
    style: その章のコードブロックの実効値（`CodeBlockStyle`。省略時は、既定）。`enabled`が偽なら、包まない。
    `raw`の既定のフォントは、要素の組み込みの指定のため、外側の`text(font: ...)`では上書きできない。
    そのため、`show raw: set text(font: ..., size: ...)`を置く（`set`は、重ねがけの問題がない）。
    枠は、`block(...)`でrawを包むのではなく、内容のブロックの中の、局所のshowルールで付ける。`block`で包むと、
    枠の高さが2.5 pt大きくなる（実測）ため。局所のshowルールは、同梱テンプレートに、同じルールがないため、重ならない
    （独自テンプレートが、`raw`のブロックにshowルールを持つときは、重なる。その場合は、`code_block: false`で無効にする）。"""
    style = style or CodeBlockStyle()
    if not style.enabled:
        return raw_typst + '\n\n'
    fonts = ", ".join(f'"{name}"' for name in CODE_FONTS)
    text_args = f'font: ({fonts})' + (f', size: {style.font_size}' if style.font_size else '')
    block_args = f'width: 100%, fill: rgb("{BACKGROUND}"), inset: {INSET}, radius: {RADIUS}'
    if style.border_color:
        block_args += f', stroke: {style.border_width} + {_typst_color(style.border_color)}'
    return (
        f'#[\n'
        f'#show raw: set text({text_args})\n'
        f'#show raw.where(block: true): it => block({block_args}, it)\n'
        f'{raw_typst}\n'
        f']\n\n'
    )
