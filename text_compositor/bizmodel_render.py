"""bizmodel（モノ・カネの流れを描く図）の、DSL → AST → レイアウト → SVGの変換（#447）。

3層に分けてある（あとで別パッケージに切り出しやすくするため）。text-compositorの内部の型には依存しない。
- `parse(text)`: DSLを、JSONにできる辞書（AST）にする。構文・意味のエラーは、`BizModelError`（行・桁つき）。
- `layout(ast)`: ASTから、座標（`Layout`）を決める。
- `to_svg(layout)` / `render_svg(text)`: SVGの文字列にする。

仕様は、doc/bizmodel-notation-spec.md。最初の実装は、2者間（売り手1つ、買い手1つ以上）の取引だけを描く。
"""
import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

# 描画の見た目や、図の形を変えたとき、SVGのキャッシュを無効にするための版（呼び出し側が、キャッシュのキーに使う）
CACHE_VERSION = "3"

FONT_FAMILY = "'Noto Sans JP','Yu Gothic','Meiryo',sans-serif"

# --- 寸法（px） ---
INK = "#111"
STROKE = 2.2
MARGIN = 24
TITLE_H = 40
PAIR_H = 164          # 1取引（モノ・カネの2本1組）の高さ
RECT_W = 48           # 法人の長方形の幅
MIN_GAP = 190         # 矢印の最小の長さ
ARROW_LEAD = 24       # 長方形と矢印の端の間
BUYER_LEAD = 54       # 矢印の先端と、買い手の記号の中心の間
BRACE_LEAD = 16
BRACE_W = 26
PERSON_HALF = 24      # 人型の半幅の基準
LABEL_SIZE = 14
MONEY_SIZE = 13
CHAR_LINE = 17        # 長方形の中の、1文字ぶんの行の高さ

_RESERVED = {"type", "title", "company", "person", "bundle", "timeline", "goods", "money"}
_SUPPORTED_TYPES = ("flow",)


class BizModelError(Exception):
    """変換エラー。codeは、仕様書の7章のエラー番号（E01など）。"""

    def __init__(self, code, message, line=None, column=None):
        self.code = code
        self.message = message
        self.line = line
        self.column = column
        where = ""
        if line is not None:
            where = f" (line {line}" + (f", column {column})" if column is not None else ")")
        super().__init__(f"{code}: {message}{where}")


# ---------------------------------------------------------------------------
# 字句解析
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'''
    (?P<ws>[ \t\r]+)
  | (?P<comment>\#.*)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<arrow>->)
  | (?P<colon>:)
  | (?P<slash>/)
  | (?P<lbrace>\{)
  | (?P<rbrace>\})
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
''', re.VERBOSE)


@dataclass
class _Tok:
    kind: str
    value: str
    col: int


def _unescape(s):
    return re.sub(r'\\(["\\])', r'\1', s)


def _tokenize(line, lineno):
    toks = []
    pos = 0
    while pos < len(line):
        m = _TOKEN_RE.match(line, pos)
        if not m:
            ch = line[pos]
            if ch == '"':
                raise BizModelError("E06", "unterminated string", lineno, pos + 1)
            raise BizModelError("E06", f"unexpected character {ch!r} "
                                       "(identifiers use A-Z, a-z, 0-9 and _; put Japanese text in a quoted label)",
                                lineno, pos + 1)
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            value = m.group()
            if kind == "string":
                value = _unescape(value[1:-1])
            toks.append(_Tok(kind, value, pos + 1))
        pos = m.end()
    return toks


# ---------------------------------------------------------------------------
# 構文解析（AST）
# ---------------------------------------------------------------------------

def parse(text):
    """DSLを、AST（JSONにできる辞書）にする。"""
    actors = []
    groups = []
    title = None
    seen_statement = False
    block = None   # 開いているbundle/timelineの、{'kind','line','trades'}

    for lineno, raw in enumerate(text.splitlines(), start=1):
        toks = _tokenize(raw, lineno)
        if not toks:
            continue
        first = toks[0]

        if first.kind == "rbrace":
            _expect_end(toks, 1, lineno)
            if block is None:
                raise BizModelError("E06", "unexpected '}' (no open bundle/timeline block)", lineno, first.col)
            _check_block(block, lineno)
            groups.append({"kind": block["kind"], "trades": block["trades"], "line": block["line"]})
            block = None
            continue

        if first.kind != "ident":
            raise BizModelError("E06", f"unexpected {first.value!r} at the start of a statement", lineno, first.col)

        word = first.value
        if word == "type":
            if seen_statement:
                raise BizModelError("E06", "'type' must come before any other statement", lineno, first.col)
            if len(toks) < 2 or toks[1].kind != "ident":
                raise BizModelError("E06", "'type' needs a name (type flow)", lineno, first.col)
            if toks[1].value not in _SUPPORTED_TYPES:
                raise BizModelError("E06", f"unsupported type {toks[1].value!r} (supported: {', '.join(_SUPPORTED_TYPES)})",
                                    lineno, toks[1].col)
            _expect_end(toks, 2, lineno)
            seen_statement = True
            continue
        seen_statement = True

        if word == "title":
            if title is not None:
                raise BizModelError("E06", "'title' can be written only once", lineno, first.col)
            if len(toks) < 2 or toks[1].kind != "string":
                raise BizModelError("E06", "'title' needs a quoted text (title \"...\")", lineno, first.col)
            _expect_end(toks, 2, lineno)
            title = toks[1].value
        elif word in ("company", "person"):
            if block is not None:
                raise BizModelError("E06", f"'{word}' cannot be declared inside a block", lineno, first.col)
            if len(toks) < 3 or toks[1].kind != "ident" or toks[2].kind != "string":
                raise BizModelError("E06", f"'{word}' needs an id and a quoted label ({word} ID \"label\")", lineno, first.col)
            if toks[1].value in _RESERVED:
                raise BizModelError("E06", f"{toks[1].value!r} is a reserved word and cannot be used as an id", lineno, toks[1].col)
            if any(a["id"] == toks[1].value for a in actors):
                raise BizModelError("E07", f"id {toks[1].value!r} is declared twice", lineno, toks[1].col)
            _expect_end(toks, 3, lineno)
            actors.append({"id": toks[1].value, "kind": word, "label": toks[2].value, "line": lineno})
        elif word in ("bundle", "timeline"):
            if block is not None:
                raise BizModelError("E06", "blocks cannot be nested", lineno, first.col)
            if len(toks) != 2 or toks[1].kind != "lbrace":
                raise BizModelError("E06", f"'{word}' must be followed by '{{' ({word} {{ ... }})", lineno, first.col)
            block = {"kind": word, "line": lineno, "trades": []}
        elif toks[1:2] and toks[1].kind == "arrow":
            trade = _parse_trade(toks, lineno)
            if block is not None:
                block["trades"].append(trade)
            else:
                groups.append({"kind": "single", "trades": [trade], "line": lineno})
        else:
            raise BizModelError("E06", f"unknown statement {word!r}", lineno, first.col)

    if block is not None:
        raise BizModelError("E06", f"'{block['kind']} {{' is not closed", block["line"])

    ids = {a["id"] for a in actors}
    for g in groups:
        for t in g["trades"]:
            for role in ("seller", "buyer"):
                if t[role] not in ids:
                    raise BizModelError("E03", f"{t[role]!r} is not declared (use company/person)", t["line"], t[role + "_col"])
            if t["seller"] == t["buyer"]:
                raise BizModelError("E04", "the seller and the buyer are the same", t["line"], t["seller_col"])
    if not groups:
        raise BizModelError("E08", "the diagram has no trade")

    for g in groups:
        for t in g["trades"]:
            del t["seller_col"], t["buyer_col"]
    return {"type": "flow", "title": title, "actors": actors, "groups": groups}


def _expect_end(toks, index, lineno):
    if len(toks) > index:
        raise BizModelError("E06", f"unexpected {toks[index].value!r}", lineno, toks[index].col)


def _parse_trade(toks, lineno):
    # ID -> ID : goods "..." / money "..."
    if toks[0].kind != "ident" or len(toks) < 3 or toks[2].kind != "ident":
        raise BizModelError("E06", "a trade is written as: SELLER -> BUYER : goods \"...\" / money \"...\"", lineno, toks[0].col)
    seller, buyer = toks[0], toks[2]
    if len(toks) < 4 or toks[3].kind != "colon":
        raise BizModelError("E01", "a trade needs both goods and money (SELLER -> BUYER : goods \"...\" / money \"...\")",
                            lineno, seller.col)
    values = {}
    i = 4
    while i < len(toks):
        if toks[i].kind != "ident" or toks[i].value not in ("goods", "money"):
            raise BizModelError("E06", f"expected 'goods' or 'money', found {toks[i].value!r}", lineno, toks[i].col)
        key = toks[i].value
        if key in values:
            raise BizModelError("E06", f"'{key}' is written twice", lineno, toks[i].col)
        if i + 1 >= len(toks) or toks[i + 1].kind != "string":
            raise BizModelError("E06", f"'{key}' needs a quoted text ({key} \"...\")", lineno, toks[i].col)
        if toks[i + 1].value.strip() == "":
            raise BizModelError("E02", f"'{key}' is empty (write \"？\" if it is unknown, \"0円\" if it is free)",
                                lineno, toks[i + 1].col)
        values[key] = toks[i + 1].value
        i += 2
        if i < len(toks):
            if toks[i].kind != "slash":
                raise BizModelError("E06", f"expected '/', found {toks[i].value!r}", lineno, toks[i].col)
            i += 1
            if i >= len(toks):
                raise BizModelError("E06", "'/' must be followed by goods or money", lineno, toks[i - 1].col)
    for key in ("goods", "money"):
        if key not in values:
            raise BizModelError("E01", f"a trade needs both goods and money ('{key}' is missing)", lineno, seller.col)
    return {"seller": seller.value, "buyer": buyer.value, "goods": values["goods"], "money": values["money"],
            "line": lineno, "seller_col": seller.col, "buyer_col": buyer.col}


def _check_block(block, lineno):
    trades = block["trades"]
    kind = block["kind"]
    if len(trades) < 2:
        raise BizModelError("E05", f"a {kind} block needs two or more trades", block["line"])
    pairs = {(t["seller"], t["buyer"]) for t in trades}
    if len(pairs) > 1:
        raise BizModelError("E05", f"all trades in a {kind} block must have the same seller and buyer", block["line"])


# ---------------------------------------------------------------------------
# レイアウト
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    width: float = 0
    height: float = 0
    title: str = None
    title_y: float = 0
    actors: list = field(default_factory=list)      # {'id','kind','label','x','y','w','h','cx','cy'}
    pairs: list = field(default_factory=list)       # {'x1','x2','y','goods','money'}
    braces: list = field(default_factory=list)      # {'x','top','bottom'}
    timelines: list = field(default_factory=list)   # {'x','y_from','y_to'}


def _text_width(s, size):
    # 全角は1em、半角は0.55emで、見積もる（フォントを測らず、決まった結果にするため）
    return sum(size if ord(ch) > 0x2E80 else size * 0.55 for ch in s)


def layout(ast):
    """ASTから、座標を決める。最初の実装は、売り手が1つの2者間の取引（買い手は複数可）だけを扱う。"""
    actors = {a["id"]: a for a in ast["actors"]}
    trades = [t for g in ast["groups"] for t in g["trades"]]
    sellers = []
    for t in trades:
        if t["seller"] not in sellers:
            sellers.append(t["seller"])
    if len(sellers) != 1:
        raise BizModelError("E09", "only one seller is supported for now (three or more parties come later)",
                            trades[0]["line"])
    seller_id = sellers[0]
    buyers = []   # 初出の順
    blocks = {}   # 買い手のid -> {'kind','trades'}
    for g in ast["groups"]:
        buyer = g["trades"][0]["buyer"]
        if buyer == seller_id or any(t["seller"] == buyer for t in trades):
            raise BizModelError("E09", f"{buyer!r} is both a seller and a buyer (three or more parties come later)",
                                g["trades"][0]["line"])
        if buyer not in blocks:
            buyers.append(buyer)
            blocks[buyer] = {"kind": g["kind"], "trades": list(g["trades"]), "groups": 1}
        else:
            b = blocks[buyer]
            if g["kind"] != "single" or b["kind"] != "single":
                raise BizModelError("E09", f"buyer {buyer!r} appears in several groups with bundle/timeline "
                                           "(not supported yet)", g["line"])
            b["trades"].extend(g["trades"])
            b["groups"] += 1

    lay = Layout(title=ast.get("title"))
    top = MARGIN + (TITLE_H if lay.title else 0)
    total_rows = sum(len(blocks[b]["trades"]) for b in buyers)

    gap = MIN_GAP
    for t in trades:
        gap = max(gap, _text_width(t["goods"], LABEL_SIZE) + 16, _text_width(t["money"], MONEY_SIZE) + 16)

    seller = actors[seller_id]
    seller_half = max(PERSON_HALF, _text_width(seller["label"], MONEY_SIZE) / 2) if seller["kind"] == "person" else RECT_W / 2
    seller_cx = MARGIN + seller_half
    x1 = seller_cx + RECT_W / 2 + ARROW_LEAD
    x2 = x1 + gap

    has_bundle = any(blocks[b]["kind"] == "bundle" for b in buyers)
    has_timeline = any(blocks[b]["kind"] == "timeline" for b in buyers)
    buyer_cx = x2 + BUYER_LEAD
    brace_x = x2 + BRACE_LEAD
    if has_bundle:
        buyer_cx = brace_x + BRACE_W + 40

    # 売り手の記号は、全体の高さに合わせる
    _add_actor(lay, seller, seller_cx, top, total_rows * PAIR_H, single_row=False)

    right = buyer_cx + RECT_W / 2
    row = 0
    for buyer_id in buyers:
        b = blocks[buyer_id]
        n = len(b["trades"])
        b_top = top + row * PAIR_H
        b_bottom = b_top + n * PAIR_H
        for i, t in enumerate(b["trades"]):
            lay.pairs.append({"x1": x1, "x2": x2, "y": b_top + i * PAIR_H, "goods": t["goods"], "money": t["money"]})
        buyer = actors[buyer_id]
        if b["kind"] == "bundle":
            bt, bb = b_top + 62, b_bottom - 40
            lay.braces.append({"x": brace_x, "top": bt, "bottom": bb})
            _add_actor(lay, buyer, buyer_cx, b_top, n * PAIR_H, single_row=False, center_y=(bt + bb) / 2)
        elif b["kind"] == "timeline":
            sym = _add_actor(lay, buyer, buyer_cx, b_top, PAIR_H, single_row=True)
            lay.timelines.append({"x": buyer_cx, "y_from": sym["bottom"] + 8, "y_to": b_bottom + 10})
        elif n == 1:
            _add_actor(lay, buyer, buyer_cx, b_top, PAIR_H, single_row=True)
        else:
            _add_actor(lay, buyer, buyer_cx, b_top, n * PAIR_H, single_row=False)
        right = max(right, buyer_cx + max(PERSON_HALF, _text_width(buyer["label"], MONEY_SIZE) / 2))
        row += n

    if has_timeline:
        right = max(right, buyer_cx + 34)
    lay.width = right + MARGIN
    lay.height = top + total_rows * PAIR_H + MARGIN - 10
    if lay.title:
        lay.width = max(lay.width, _text_width(lay.title, 16) + MARGIN * 2)
        lay.title_y = MARGIN + 14
    return lay


def _add_actor(lay, actor, cx, block_top, block_h, single_row, center_y=None):
    """法人は縦長の長方形（高さは、取引の行に合わせる）、個人は人型。bottomは、記号と名前の下端。"""
    if actor["kind"] == "company":
        h = (PAIR_H if single_row else block_h) - 20
        item = {"id": actor["id"], "kind": "company", "label": actor["label"],
                "x": cx - RECT_W / 2, "y": block_top + 10, "w": RECT_W, "h": h, "cx": cx, "cy": block_top + 10 + h / 2}
        item["bottom"] = item["y"] + h
    else:
        if center_y is not None:
            cy = center_y
        elif single_row:
            cy = block_top + 62
        else:
            cy = block_top + block_h / 2 - 10
        item = {"id": actor["id"], "kind": "person", "label": actor["label"],
                "x": cx - 22, "y": cy - 39, "w": 44, "h": 71, "cx": cx, "cy": cy, "bottom": cy + 60}
    lay.actors.append(item)
    return item


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def _fmt(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _text(x, y, s, size=LABEL_SIZE, anchor="middle", bold=False):
    weight = ' font-weight="bold"' if bold else ""
    return (f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-family="{FONT_FAMILY}" font-size="{_fmt(size)}" '
            f'text-anchor="{anchor}"{weight} fill="{INK}">{escape(s)}</text>')


def _svg_company(a):
    out = [f'<rect x="{_fmt(a["x"])}" y="{_fmt(a["y"])}" width="{_fmt(a["w"])}" height="{_fmt(a["h"])}" '
           f'fill="#fff" stroke="{INK}" stroke-width="{STROKE}"/>']
    # 名前は、縦書き（writing-mode）で、長方形の中央に置く。括弧・長音符・句読点が、縦書きの形になる
    # （PDF（Typst）・resvg・ブラウザで、同じに表示されることを確認してある）。長い名前は、収まるまで、文字を小さくする
    size = LABEL_SIZE
    while size > 8 and _text_width(a["label"], size) > a["h"] - 16:
        size -= 1
    out.append(f'<text x="{_fmt(a["cx"])}" y="{_fmt(a["cy"])}" writing-mode="tb" font-family="{FONT_FAMILY}" '
               f'font-size="{_fmt(size)}" text-anchor="middle" fill="{INK}">{escape(a["label"])}</text>')
    return "\n".join(out)


def _svg_person(a):
    cx, cy = a["cx"], a["cy"]
    return "\n".join([
        f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy - 26)}" r="13" fill="#fff" stroke="{INK}" stroke-width="{STROKE}"/>',
        f'<path d="M {_fmt(cx - 22)} {_fmt(cy + 32)} L {_fmt(cx - 22)} {_fmt(cy + 8)} Q {_fmt(cx - 22)} {_fmt(cy - 8)} '
        f'{_fmt(cx)} {_fmt(cy - 8)} Q {_fmt(cx + 22)} {_fmt(cy - 8)} {_fmt(cx + 22)} {_fmt(cy + 8)} '
        f'L {_fmt(cx + 22)} {_fmt(cy + 32)} Z" fill="#fff" stroke="{INK}" stroke-width="{STROKE}"/>',
        _text(cx, cy + 52, a["label"], MONEY_SIZE),
    ])


def _svg_pair(p):
    x1, x2, y0 = p["x1"], p["x2"], p["y"]
    mid = (x1 + x2) / 2
    ya, yb = y0 + 72, y0 + 92
    return "\n".join([
        _text(mid, y0 + 18, p["goods"], LABEL_SIZE),
        f'<circle cx="{_fmt(mid)}" cy="{_fmt(y0 + 42)}" r="10" fill="#fff" stroke="{INK}" stroke-width="{STROKE}"/>',
        # 販売（モノの流れ）: 右向き。先端を塗りつぶす
        f'<line x1="{_fmt(x1)}" y1="{_fmt(ya)}" x2="{_fmt(x2 - 12)}" y2="{_fmt(ya)}" stroke="{INK}" stroke-width="{STROKE}"/>',
        f'<polygon points="{_fmt(x2)},{_fmt(ya)} {_fmt(x2 - 16)},{_fmt(ya - 8)} {_fmt(x2 - 16)},{_fmt(ya + 8)}" fill="{INK}"/>',
        # 支払（カネの流れ）: 左向き。先端が開いた標準的な矢印
        f'<line x1="{_fmt(x2)}" y1="{_fmt(yb)}" x2="{_fmt(x1)}" y2="{_fmt(yb)}" stroke="{INK}" stroke-width="{STROKE}"/>',
        f'<polyline points="{_fmt(x1 + 12)},{_fmt(yb - 7)} {_fmt(x1)},{_fmt(yb)} {_fmt(x1 + 12)},{_fmt(yb + 7)}" '
        f'fill="none" stroke="{INK}" stroke-width="{STROKE}"/>',
        _text(mid, y0 + 120, "¥", 20),
        _text(mid, y0 + 140, p["money"], MONEY_SIZE),
    ])


def _svg_brace(b):
    x, top, bottom = b["x"], b["top"], b["bottom"]
    m = (top + bottom) / 2
    d = (f"M {_fmt(x)} {_fmt(top)} Q {_fmt(x + 14)} {_fmt(top)} {_fmt(x + 14)} {_fmt(top + 14)} "
         f"L {_fmt(x + 14)} {_fmt(m - 10)} Q {_fmt(x + 14)} {_fmt(m)} {_fmt(x + 26)} {_fmt(m)} "
         f"Q {_fmt(x + 14)} {_fmt(m)} {_fmt(x + 14)} {_fmt(m + 10)} L {_fmt(x + 14)} {_fmt(bottom - 14)} "
         f"Q {_fmt(x + 14)} {_fmt(bottom)} {_fmt(x)} {_fmt(bottom)}")
    return f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{STROKE}"/>'


def _svg_timeline(t):
    x, y0, y1 = t["x"], t["y_from"], t["y_to"]
    return "\n".join([
        f'<line x1="{_fmt(x)}" y1="{_fmt(y0)}" x2="{_fmt(x)}" y2="{_fmt(y1 - 12)}" stroke="{INK}" stroke-width="{STROKE}"/>',
        f'<polygon points="{_fmt(x)},{_fmt(y1)} {_fmt(x - 7)},{_fmt(y1 - 14)} {_fmt(x + 7)},{_fmt(y1 - 14)}" fill="{INK}"/>',
        _text(x + 14, y1 - 6, "T", 14, anchor="start", bold=True),
    ])


def to_svg(lay):
    """Layoutを、SVGの文字列にする。"""
    parts = []
    if lay.title:
        parts.append(_text(lay.width / 2, lay.title_y, lay.title, 16, bold=True))
    for a in lay.actors:
        parts.append(_svg_company(a) if a["kind"] == "company" else _svg_person(a))
    for p in lay.pairs:
        parts.append(_svg_pair(p))
    for b in lay.braces:
        parts.append(_svg_brace(b))
    for t in lay.timelines:
        parts.append(_svg_timeline(t))
    w, h = _fmt(lay.width), _fmt(lay.height)
    label = escape(lay.title or "business model diagram")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
            f'<title>{label}</title>\n<rect width="100%" height="100%" fill="#fff"/>\n'
            + "\n".join(parts) + "\n</svg>\n")


def render_svg(text):
    """DSLのテキストから、SVGの文字列を返す。構文・意味のエラーは、`BizModelError`。"""
    return to_svg(layout(parse(text)))
