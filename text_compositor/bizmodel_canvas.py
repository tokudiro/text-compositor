"""bizmodelの記法2（ビジネスモデルキャンバス）の、DSL → AST → レイアウト → SVG（#458）。

仕様は、doc/bizmodel-canvas-spec.md。`bizmodel_render`が、本文の冒頭の`type canvas`を見て、この
モジュールに委ねる（記法1と、フェンス・拡張子・設定のキーを共有する）。

出典の明示（Strategyzer.comの文字とライセンス）は、利用条件（CC BY-SA 3.0）の求めで、
**すべての図の下に、必ず入れる**。利用者が、消したり、変えたりできる口は、設けない。
"""
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from text_compositor import bizmodel_render as core
from text_compositor.bizmodel_render import BizModelError

# 枠: (キー, 略号, 見出し)。表示と、ASTのキーの順は、この並びに従う
BLOCKS = (
    ("partners", "KP", "パートナー"),
    ("activities", "KA", "主要活動"),
    ("resources", "KR", "リソース"),
    ("value", "VP", "価値提案"),
    ("relationships", "CR", "顧客との関係"),
    ("channels", "CH", "チャネル"),
    ("segments", "CS", "顧客セグメント"),
    ("costs", "C$", "コスト構造"),
    ("revenue", "R$", "収益の流れ"),
)
KEYS = tuple(b[0] for b in BLOCKS)
_INFO = {key: (abbr, label) for key, abbr, label in BLOCKS}

# 出典の表記。利用条件の求めで、すべての図の下に入れる（設定で消せない）
CREDIT = "Business Model Canvas: Strategyzer.com (CC BY-SA 3.0)"

# --- 寸法（px） ---
COL_W = 190
PAD = 10
HEAD_H = 30
BODY_SIZE = 12
HEAD_SIZE = 13
LINE_H = 17
BULLET_W = 12
MIN_ROW = 150
MIN_BOTTOM = 100
CREDIT_SIZE = 11   # 本文（12）の0.85倍以上
MARGIN = 24
STROKE = 1.5

_NO_LINE_START = set("、。，．,.）)」』】〕］｝〉》！？!?・：；ー々ゝゞぁぃぅぇぉっゃゅょァィゥェォッャュョ")


# ---------------------------------------------------------------------------
# 構文解析
# ---------------------------------------------------------------------------

_FLOW_WORDS = {"company", "person", "bundle", "timeline", "goods", "money"}


def parse(text):
    """DSLを、AST（JSONにできる辞書）にする。"""
    title = None
    blocks = {key: [] for key in KEYS}
    seen_statement = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        toks = core._tokenize(raw, lineno)
        if not toks:
            continue
        first = toks[0]
        if first.kind != "ident":
            raise BizModelError("E06", f"unexpected {first.value!r} at the start of a statement"
                                       + (" (flow notation statements do not belong to 'type canvas')"
                                          if first.kind in ("arrow", "lbrace", "rbrace") else ""),
                                lineno, first.col)
        word = first.value
        if word == "type":
            if seen_statement:
                raise BizModelError("E06", "'type' must come before any other statement", lineno, first.col)
            seen_statement = True
            if len(toks) != 2 or toks[1].kind != "ident" or toks[1].value != "canvas":
                raise BizModelError("E06", "expected 'type canvas'", lineno, first.col)
            continue
        seen_statement = True
        if word == "title":
            if title is not None:
                raise BizModelError("E06", "'title' can be written only once", lineno, first.col)
            if len(toks) != 2 or toks[1].kind != "string":
                raise BizModelError("E06", "'title' needs a quoted text (title \"...\")", lineno, first.col)
            title = toks[1].value
        elif word in KEYS:
            if len(toks) < 2 or toks[1].kind != "string":
                raise BizModelError("E06", f"'{word}' needs a quoted text ({word} \"...\")", lineno, first.col)
            if len(toks) > 2:
                raise BizModelError("E06", f"unexpected {toks[2].value!r} (one item per line)", lineno, toks[2].col)
            if toks[1].value.strip() == "":
                raise BizModelError("E02", f"'{word}' is empty", lineno, toks[1].col)
            blocks[word].append({"text": toks[1].value, "line": lineno})
        elif word in _FLOW_WORDS or (len(toks) > 1 and toks[1].kind == "arrow"):
            raise BizModelError("E06", f"{word!r} belongs to the flow notation, not to 'type canvas'", lineno, first.col)
        else:
            raise BizModelError("E06", f"unknown key {word!r} (keys: {', '.join(KEYS)})", lineno, first.col)
    if not any(blocks.values()):
        raise BizModelError("E08", "the canvas has no item")
    return {"type": "canvas", "title": title, "blocks": blocks}


# ---------------------------------------------------------------------------
# 文字の折り返し
# ---------------------------------------------------------------------------

def _is_wide(ch):
    return ord(ch) > 0x2E80


def _units(text):
    """折り返しの単位に分ける。全角の文字は、1文字ずつ。半角の語は、空白までを1つに。"""
    out, word = [], ""
    for ch in text:
        if _is_wide(ch):
            if word:
                out.append(word)
                word = ""
            out.append(ch)
        elif ch == " ":
            if word:
                out.append(word)
                word = ""
            out.append(" ")
        else:
            word += ch
    if word:
        out.append(word)
    return out


def wrap(text, size, width):
    """幅に収まるように、行に分ける（幅は、記法1と同じ見積もり）。行頭に、閉じ括弧・句読点・長音符を出さない。"""
    lines, cur = [], ""
    for unit in _units(text):
        if unit == " " and not cur:
            continue
        pieces = [unit]
        if len(unit) > 1 and not _is_wide(unit[0]) and core._text_width(unit, size) > width:
            pieces = list(unit)   # 1語が枠より長いときは、語の途中で切る
        for piece in pieces:
            if cur and core._text_width(cur + piece, size) > width and piece != " ":
                if piece[0] in _NO_LINE_START:
                    if _is_wide(piece[0]) and len(cur) >= 2:
                        # 全角の約物・長音符・小さい仮名は、行頭に出さない。直前の1文字を、次の行へ送る（追い出し）
                        lines.append(cur[:-1].rstrip())
                        cur = cur[-1] + piece
                    else:
                        cur += piece   # 半角の記号は、前の行に追い込む
                    continue
                lines.append(cur.rstrip())
                cur = piece
            else:
                cur += piece
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


# ---------------------------------------------------------------------------
# レイアウト
# ---------------------------------------------------------------------------

@dataclass
class CanvasLayout:
    kind: str = "canvas"
    width: float = 0
    height: float = 0
    title: str = None
    title_y: float = 0
    cells: list = field(default_factory=list)   # {'key','heading','x','y','w','h','lines':[(text, first)]}
    credit_y: float = 0


def _content_h(lines):
    return HEAD_H + len(lines) * LINE_H + PAD


def layout(ast):
    """ASTから、枠の座標と、折り返した行を決める。"""
    wrapped = {}   # キー -> 折り返した項目 [[行, ...], ...]
    def make(key, width):
        inner = width - 2 * PAD - BULLET_W
        wrapped[key] = [wrap(item["text"], BODY_SIZE, inner) for item in ast["blocks"][key]]
        return sum(len(it) for it in wrapped[key])

    half = COL_W * 2.5
    count = {k: make(k, COL_W) for k in KEYS if k not in ("costs", "revenue")}
    for k in ("costs", "revenue"):
        count[k] = make(k, half)
    h = {k: HEAD_H + count[k] * LINE_H + PAD for k in KEYS}

    r1 = max(MIN_ROW, h["activities"], h["relationships"])
    r2 = max(MIN_ROW, h["resources"], h["channels"])
    span = max(h["partners"], h["value"], h["segments"])
    if span > r1 + r2:
        extra = span - (r1 + r2)
        r1 += extra / 2
        r2 += extra / 2
    r3 = max(MIN_BOTTOM, h["costs"], h["revenue"])

    top = MARGIN + (core.TITLE_H if ast.get("title") else 0)
    x0 = MARGIN
    place = {   # キー: (x, y, w, h)
        "partners": (x0, top, COL_W, r1 + r2),
        "activities": (x0 + COL_W, top, COL_W, r1),
        "resources": (x0 + COL_W, top + r1, COL_W, r2),
        "value": (x0 + 2 * COL_W, top, COL_W, r1 + r2),
        "relationships": (x0 + 3 * COL_W, top, COL_W, r1),
        "channels": (x0 + 3 * COL_W, top + r1, COL_W, r2),
        "segments": (x0 + 4 * COL_W, top, COL_W, r1 + r2),
        "costs": (x0, top + r1 + r2, half, r3),
        "revenue": (x0 + half, top + r1 + r2, half, r3),
    }
    lay = CanvasLayout(title=ast.get("title"))
    for key in KEYS:
        x, y, w, hh = place[key]
        abbr, label = _INFO[key]
        lay.cells.append({"key": key, "heading": f"{label}（{abbr}）", "x": x, "y": y, "w": w, "h": hh,
                          "items": wrapped[key]})
    grid_bottom = top + r1 + r2 + r3
    lay.credit_y = grid_bottom + 24
    lay.width = x0 * 2 + 5 * COL_W
    lay.height = lay.credit_y + 14
    if lay.title:
        lay.title_y = MARGIN + 14
        lay.width = max(lay.width, core._text_width(lay.title, 16) + MARGIN * 2)
    return lay


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def to_svg(lay):
    parts = []
    if lay.title:
        parts.append(core._text(lay.width / 2, lay.title_y, lay.title, 16, bold=True))
    for c in lay.cells:
        f = core._fmt
        parts.append(f'<rect x="{f(c["x"])}" y="{f(c["y"])}" width="{f(c["w"])}" height="{f(c["h"])}" '
                     f'fill="#fff" stroke="{core.INK}" stroke-width="{STROKE}"/>')
        parts.append(core._text(c["x"] + PAD, c["y"] + 20, c["heading"], HEAD_SIZE, anchor="start", bold=True))
        y = c["y"] + HEAD_H + 14
        for item in c["items"]:
            parts.append(core._text(c["x"] + PAD, y, "・", BODY_SIZE, anchor="start"))
            for line in item:
                parts.append(core._text(c["x"] + PAD + BULLET_W, y, line, BODY_SIZE, anchor="start"))
                y += LINE_H
    parts.append(core._text(lay.width / 2, lay.credit_y, CREDIT, CREDIT_SIZE))
    w, h = core._fmt(lay.width), core._fmt(lay.height)
    label = escape(lay.title or "business model canvas")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
            f'<title>{label}</title>\n<rect width="100%" height="100%" fill="#fff"/>\n'
            + "\n".join(parts) + "\n</svg>\n")
