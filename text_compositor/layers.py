"""`::: layers`ブロック（画像や図を重ねて1つの部品にする。#560）の解析。

ここでは、ブロックの中身を部品の並びに分けるだけで、描画はしない（PDF・HTMLの描画は、別の手順）。
描画に依存しない純粋な関数にしておくと、PDFとHTMLの両方が同じ解析結果を使え、単体でテストできる。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .renderer_layout import LayoutMixin

# 画像は、単独行の`![alt|x=40|y=20](src)`。フェンスは、図の種類の後ろに`{x=240 y=140}`を書く。
# どちらも、layout-*が使う正規表現を再利用する。図の種類を足したとき、layersにも自動で効く。
_PART_RE = LayoutMixin.DIAGRAM_OR_IMAGE_RE
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)\n]+)\)')
_FENCE_ATTR_RE = LayoutMixin.FENCE_ATTR_RE
_INT_RE = re.compile(r'-?\d+$')

# layersでは、部品を原寸で置く（拡大縮小はしない）。大きさや寄せを決める属性は、効かない。
_IGNORED_KEYS = ('width', 'height', 'align')


@dataclass
class LayerPart:
    """重ねる部品1つ。`x`・`y`は、原点（左上）からのずれ（ピクセル）。"""
    kind: str                      # 'image' または 'fence'
    x: int = 0
    y: int = 0
    src: str = ''                  # 画像: ファイルのパス
    alt: str = ''                  # 画像: `|`より前の説明（読み上げには使わない）
    lang: str = ''                 # フェンス: 図の種類（mermaid・svgなど）
    code: str = ''                 # フェンス: 中身
    attrs: str = ''                # フェンス: x・yを除いた`{...}`（なければ空）


@dataclass
class LayersBlock:
    alt: str                       # 重ね全体の代替テキスト（見出し行の文字列）
    parts: List[LayerPart] = field(default_factory=list)   # 先に書いた順（下から上）
    warnings: List[str] = field(default_factory=list)      # 呼び出し側が、警告として出す


def _read_offset(key: str, value: str, warnings: List[str]) -> int:
    """`x=`・`y=`の値を整数（ピクセル）にする。数値でなければ警告して0にする。"""
    if _INT_RE.match(value):
        return int(value)
    warnings.append(f"Ignoring invalid {key} {value!r} in layers; expected an integer number of pixels.")
    return 0


def _parse_image(alt_text: str, src: str, warnings: List[str]) -> LayerPart:
    """画像のaltを、既存の画像と同じく`|`で分ける。最初が説明、残りが`key=値`。"""
    pieces = alt_text.split('|')
    part = LayerPart(kind='image', src=src.strip(), alt=pieces[0])
    for piece in pieces[1:]:
        key, sep, value = piece.strip().partition('=')
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key in ('x', 'y'):
            setattr(part, key, _read_offset(key, value, warnings))
        elif key in _IGNORED_KEYS:
            warnings.append(f"Ignoring {key} of an image in layers; parts are placed at their natural size.")
    return part


def _parse_fence(lang: str, attrs: Optional[str], code: str, warnings: List[str]) -> LayerPart:
    """フェンスの`{...}`から、x・yを取り出す。残りの属性（`trim=`など）は、そのまま残す。"""
    part = LayerPart(kind='fence', lang=lang, code=code)
    kept = []
    for key, value in _FENCE_ATTR_RE.findall(attrs or ''):
        if key in ('x', 'y'):
            setattr(part, key, _read_offset(key, value, warnings))
        elif key in _IGNORED_KEYS:
            warnings.append(f"Ignoring {key} of a {lang} fence in layers; parts are placed at their natural size.")
        else:
            kept.append(f'{key}={value}')
    part.attrs = '{' + ' '.join(kept) + '}' if kept else ''
    return part


def parse_layers_block(header: str, body: str) -> LayersBlock:
    """`::: layers <header>`の見出し行の文字列と、ブロックの中身を、部品の並びに分ける。

    部品の間の地の文は、重ねる対象ではないので、警告にして捨てる。"""
    block = LayersBlock(alt=(header or '').strip())
    pos = 0
    stray = False
    for m in _PART_RE.finditer(body):
        if body[pos:m.start()].strip():
            stray = True
        pos = m.end()
        if m.group('lang'):
            block.parts.append(_parse_fence(m.group('lang'), m.group('attrs'), m.group('code'), block.warnings))
        else:
            image = _IMAGE_RE.match(m.group('image'))
            block.parts.append(_parse_image(image.group(1), image.group(2), block.warnings))
    if body[pos:].strip():
        stray = True
    if stray:
        block.warnings.append("Ignoring text in layers outside images and diagram fences.")
    return block
