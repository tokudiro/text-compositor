"""追加のフォント（#376）と、フォントに無い文字の検出。

PDFは、Noto Sans JP（初回のビルドで取得する）と、Typst内蔵のフォントだけを使う（システムのフォントは、使わない。#71。環境で、見た目が
変わらないようにするため）。そのため、韓国語（ハングル）・絵文字・簡体字だけにある字などは、どのフォントにもなく、
警告なしに、空の四角（□）で出ていた。

- `config.yaml`の`fonts.dir`に、フォントのフォルダ（`config.yaml`の場所が基準。複数も可）を書くと、そのフォルダの
  `.ttf`・`.otf`・`.ttc`・`.otc`を、Typstのフォントに足す。テンプレートの変更は、要らない。Typstは、指定したフォント
  （`"Noto Sans JP"`）に、その文字がないとき、使えるフォントの全体から、その文字を持つものを、自動で探して使うため。
- 原稿の文字のうち、どのフォントにもないものは、`ファイル名:行`つきの警告にする。
"""
from __future__ import annotations

import hashlib
import os
import struct
from typing import Dict, FrozenSet, Iterable, List, Sequence, Tuple

from text_compositor import diagnostics

FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")

# 警告の対象は、Typst内蔵のフォント（Libertinus Serif・DejaVu Sans Mono・New Computer Modern）が、まず持たない文字に絞る。
# 内蔵のフォントが持つ記号（例: `☐`）まで警告すると、誤警告になるため。ハングル・CJKの漢字・絵文字が、対象。
_HANGUL = ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7FF))
_CJK = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FFFF))
_EMOJI = ((0x1F000, 0x1FAFF),)
# 基本多言語面（U+FFFF以下）の、絵文字の表示が既定の文字（Emoji_Presentation）
_BMP_EMOJI = (
    (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3), (0x25FD, 0x25FE), (0x2614, 0x2615),
    (0x2648, 0x2653), (0x267F, 0x267F), (0x2693, 0x2693), (0x26A1, 0x26A1), (0x26AA, 0x26AB), (0x26BD, 0x26BE),
    (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4), (0x26EA, 0x26EA), (0x26F2, 0x26F3), (0x26F5, 0x26F5),
    (0x26FA, 0x26FA), (0x26FD, 0x26FD), (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C),
    (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797), (0x27B0, 0x27B0), (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
)
# 種類（警告のまとめ方）ごとの範囲
_CATEGORIES = (("Hangul", _HANGUL), ("CJK ideograph", _CJK), ("emoji", _EMOJI + _BMP_EMOJI))

# 追加のフォントのフォルダ（絶対パス）。ビルドの始めに、`set_extra_font_dirs`で、そのプロジェクトのものにする。
_extra_dirs: Tuple[str, ...] = ()
# フォントファイルごとの、文字の一覧のキャッシュ: (パス, 大きさ, 更新日時) → 文字の集合
_codepoint_cache: Dict[Tuple[str, int, int], FrozenSet[int]] = {}


def set_extra_font_dirs(dirs: Iterable[str]) -> None:
    global _extra_dirs
    _extra_dirs = tuple(dirs)


def extra_font_dirs() -> Tuple[str, ...]:
    return _extra_dirs


def font_paths(font_dir) -> List[str]:
    """Typstの`font_paths`。同梱のフォントのフォルダに、追加のフォントのフォルダを足す。`font_dir`は、文字列でも、リストでもよい。"""
    base = [font_dir] if isinstance(font_dir, str) else list(font_dir)
    return base + [d for d in _extra_dirs if d not in base]


def _font_files(directory: str) -> List[str]:
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [os.path.join(directory, n) for n in names if n.lower().endswith(FONT_EXTENSIONS)]


def fonts_signature() -> str:
    """追加のフォントの、目印（図のSVGのキャッシュキーに入れる）。追加のフォントが無いときは、空（従来のキーを変えない）。
    フォントを足す・入れ替えると、キーが変わり、図（□で描いたSVGのキャッシュ）が、描き直される。"""
    if not _extra_dirs:
        return ""
    parts = []
    for directory in _extra_dirs:
        for path in _font_files(directory):
            try:
                parts.append(f"{os.path.basename(path)}:{os.stat(path).st_size}")
            except OSError:
                continue
    return "+f" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:8]


def resolve_extra_font_dirs(config: dict, project_dir: str) -> List[str]:
    """`config.yaml`の`fonts.dir`（文字列、または、文字列のリスト）を、絶対パスのリストにする。無いフォルダは、警告して外す。"""
    fonts = (config or {}).get("fonts") or {}
    value = fonts.get("dir") if isinstance(fonts, dict) else None
    if value is None:
        return []
    entries = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else []
    result = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        path = os.path.normpath(os.path.join(project_dir, entry))
        if not os.path.isdir(path):
            diagnostics.warning(f"fonts.dir: the folder is not found: {path}")
            continue
        if not _font_files(path):
            diagnostics.warning(f"fonts.dir: no font file ({', '.join(FONT_EXTENSIONS)}) in {path}")
        result.append(path)
    return result


# -- フォントの、文字の一覧（cmap）を読む -----------------------------------------------------
# OpenType（.otf・.ttf）と、コレクション（.ttc・.otc）の、`cmap`テーブル（形式4・12）を、標準ライブラリだけで読む。

def _cmap_codepoints(data: bytes, font_offset: int) -> FrozenSet[int]:
    num_tables = struct.unpack(">H", data[font_offset + 4: font_offset + 6])[0]
    cmap_off = None
    for i in range(num_tables):
        record = font_offset + 12 + 16 * i
        tag, _checksum, offset, _length = struct.unpack(">4sIII", data[record: record + 16])
        if tag == b"cmap":
            cmap_off = offset
    if cmap_off is None:
        return frozenset()
    count = struct.unpack(">H", data[cmap_off + 2: cmap_off + 4])[0]
    chars = set()
    for i in range(count):
        platform, encoding, sub_off = struct.unpack(">HHI", data[cmap_off + 4 + 8 * i: cmap_off + 12 + 8 * i])
        if (platform, encoding) not in ((3, 1), (3, 10), (0, 3), (0, 4)):
            continue
        base = cmap_off + sub_off
        fmt = struct.unpack(">H", data[base: base + 2])[0]
        if fmt == 4:
            seg2 = struct.unpack(">H", data[base + 6: base + 8])[0]
            seg = seg2 // 2
            ends = struct.unpack(f">{seg}H", data[base + 14: base + 14 + seg2])
            starts = struct.unpack(f">{seg}H", data[base + 16 + seg2: base + 16 + 2 * seg2])
            for start, end in zip(starts, ends):
                if start != 0xFFFF:
                    chars.update(range(start, end + 1))
        elif fmt == 12:
            groups = struct.unpack(">I", data[base + 12: base + 16])[0]
            for g in range(groups):
                start, end, _gid = struct.unpack(">III", data[base + 16 + 12 * g: base + 28 + 12 * g])
                chars.update(range(start, end + 1))
    return frozenset(chars)


def font_codepoints(path: str) -> FrozenSet[int]:
    """フォントファイルが持つ文字（コードポイント）の集合。読めないファイルは、空。"""
    try:
        stat = os.stat(path)
    except OSError:
        return frozenset()
    key = (path, stat.st_size, int(stat.st_mtime))
    if key in _codepoint_cache:
        return _codepoint_cache[key]
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data[:4] == b"ttcf":
            count = struct.unpack(">I", data[8:12])[0]
            offsets = struct.unpack(f">{count}I", data[12: 12 + 4 * count])
            result = frozenset().union(*(_cmap_codepoints(data, off) for off in offsets))
        else:
            result = _cmap_codepoints(data, 0)
    except (OSError, struct.error, ValueError):
        result = frozenset()
    _codepoint_cache[key] = result
    return result


def covered_codepoints(font_dir) -> FrozenSet[int]:
    """同梱のフォントと、追加のフォントが、持つ文字の、和集合。"""
    chars = set()
    for directory in font_paths(font_dir):
        for path in _font_files(directory):
            chars |= font_codepoints(path)
    return frozenset(chars)


# -- フォントに無い文字の検出 ------------------------------------------------------------------

def _in_ranges(cp: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _category(cp: int):
    for name, ranges in _CATEGORIES:
        if _in_ranges(cp, ranges):
            return name
    return None


def find_missing_glyphs(text: str, covered: FrozenSet[int]) -> List[Tuple[int, str, str]]:
    """原稿の文字のうち、どのフォントにもないものを、文字ごとに、(最初の行（1始まり）, 文字, 種類)で返す（出た順）。
    対象は、ハングル・CJKの漢字・絵文字（上の範囲）だけ。"""
    seen = set()
    found = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ch in line:
            cp = ord(ch)
            if cp < 0x80 or ch in seen or cp in covered:
                continue
            category = _category(cp)
            if category is None:
                continue
            seen.add(ch)
            found.append((line_no, ch, category))
    return found


MAX_EXAMPLES = 5


def warn_missing_glyphs(text: str, path: str, font_dir=None) -> None:
    """原稿（Markdown）の、フォントに無い文字を、`ファイル名:行`つきの警告にする。種類（ハングル・漢字・絵文字）ごとに、
    1つの警告にまとめる（最初の行と、例の文字つき）。"""
    if font_dir is None:
        from text_compositor.deps import ensure_fonts
        font_dir = ensure_fonts()
    groups: Dict[str, List[Tuple[int, str]]] = {}
    for line_no, ch, category in find_missing_glyphs(text, covered_codepoints(font_dir)):
        groups.setdefault(category, []).append((line_no, ch))
    for category, items in groups.items():
        examples = ", ".join(f"'{ch}' (U+{ord(ch):04X})" for _, ch in items[:MAX_EXAMPLES])
        more = f" and {len(items) - MAX_EXAMPLES} more" if len(items) > MAX_EXAMPLES else ""
        first_line = min(line for line, _ in items)
        diagnostics.warning(
            f"{len(items)} {category} character(s) are not in any font, so the PDF shows an empty box: {examples}{more}. "
            "Put a font that has them in the folder set by fonts.dir in config.yaml.",
            file=path, line=first_line)
