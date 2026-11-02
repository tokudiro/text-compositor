"""画像ファイルの原寸（ピクセル）を、ファイルの先頭から読む（#560）。

`layers`は、部品を原寸で置き、全部品を包む長方形を求めるため、部品の大きさを先に知る必要がある。
画像を読み込む外部ライブラリには頼らず（Pillowは任意の依存のため）、PNG・JPEG・GIF・SVGだけを読む。
読めない形式は、Noneを返す。呼び出し側が、警告にする。
"""
import re
import struct
from typing import Optional, Tuple

_SVG_ROOT_RE = re.compile(r'<svg\b[^>]*>', re.IGNORECASE | re.DOTALL)
_ATTR_RE = r'\b{name}\s*=\s*(?:"([^"]*)"|\'([^\']*)\')'
_LENGTH_RE = re.compile(r'^\s*([0-9]*\.?[0-9]+)\s*(px|pt|pc|mm|cm|in)?\s*$')
# CSSの絶対単位を、ピクセル（1in=96px）に換算する比率。%やemなどは、原寸にならないため、扱わない
_TO_PX = {None: 1.0, 'px': 1.0, 'pt': 96 / 72, 'pc': 16.0, 'mm': 96 / 25.4, 'cm': 96 / 2.54, 'in': 96.0}

Size = Tuple[float, float]


def natural_size(path: str) -> Optional[Size]:
    """pathの画像の(幅, 高さ)をピクセルで返す。読めなければ、None。"""
    try:
        with open(path, 'rb') as f:
            head = f.read(64 * 1024)   # 大きな画像でも、先頭だけで足りる（JPEGのSOFも、通常は先頭付近）
    except OSError:
        return None
    if head.startswith(b'\x89PNG\r\n\x1a\n') and len(head) >= 24:
        return struct.unpack('>II', head[16:24])
    if head[:6] in (b'GIF87a', b'GIF89a') and len(head) >= 10:
        return struct.unpack('<HH', head[6:10])
    if head.startswith(b'\xff\xd8'):
        return _jpeg_size(head)
    return _svg_size(head.decode('utf-8', errors='ignore'))


def _jpeg_size(data: bytes) -> Optional[Size]:
    """JPEGのマーカーをたどり、SOF（フレーム開始）から、幅と高さを読む。"""
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            pos += 2 if marker != 0xFF else 1
            continue
        length = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack('>HH', data[pos + 5:pos + 9])
            return (width, height) if width and height else None
        pos += 2 + length
    return None


def _attr(tag: str, name: str) -> Optional[str]:
    m = re.search(_ATTR_RE.format(name=name), tag)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else None


def _length_px(value: Optional[str]) -> Optional[float]:
    m = _LENGTH_RE.match(value) if value else None
    return float(m.group(1)) * _TO_PX[m.group(2)] if m else None


def _svg_size(text: str) -> Optional[Size]:
    """SVGの原寸。ブラウザの`<img>`と同じく、絶対単位のwidth・heightを優先し、なければviewBoxの大きさにする。"""
    m = _SVG_ROOT_RE.search(text)
    if not m:
        return None
    tag = m.group(0)
    width, height = _length_px(_attr(tag, 'width')), _length_px(_attr(tag, 'height'))
    if width and height:
        return (width, height)
    box = _attr(tag, 'viewBox')
    if box:
        nums = re.split(r'[\s,]+', box.strip())
        if len(nums) == 4:
            try:
                vb_w, vb_h = float(nums[2]), float(nums[3])
            except ValueError:
                return None
            if vb_w > 0 and vb_h > 0:
                return (vb_w, vb_h)
    return None
