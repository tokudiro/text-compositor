"""Mermaidのフローチャート（`flowchart`・`graph`）の、自作の変換器（#532。親は#474）。

ブラウザ（Chrome/Edge）を使わず、SVGにする。記法は、Mermaidのままで、対応する範囲だけを描く。対応しない書き方は、
`FlowchartUnsupported`で知らせる（呼び出し側が、従来のMermaid（ブラウザ）に任せるための、描画の前の宣言的な判定。設計書3.3）。

3つの層に分けている。
1. 解析（`parse`）: 文字を、ノード・矢印・向きにする。
2. 配置（`layout`）: 文字の大きさをTypstで測り、Graphvizの`dot`（`diagraph-layout`）で、位置と矢印の曲線を求める。
   Mermaid（dagre）より、矢印の交差が少ない傾向がある（#532の比較）。
3. 描画（`render_svg`）: 位置から、SVGを自分で描く。配色・文字・折り返しを、文書にそろえられる。

Typstは、文字の幅を測ることと、`dot`の配置を呼ぶことだけに使い、見た目には関わらない。
"""
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from text_compositor.deps import ensure_fonts
from text_compositor.fonts import font_paths, fonts_signature
from text_compositor.typst_runtime import typst_lib, typst_package_options

DIAGRAPH_LAYOUT_VERSION = "0.0.1"
FLOWCHART_VERSION = "1"

# --- 見た目（文書の白黒に合わせる。ブラウザ・Typstのどちらでも、同じに描けるよう、固定の色にする） ---
FONT_FAMILY = "'Noto Sans JP', sans-serif"
NODE_FONT_SIZE = 11.0
EDGE_FONT_SIZE = 9.5
STROKE = "#333333"
NODE_FILL = "#ffffff"
LINE_HEIGHT = 1.4
MAX_TEXT_WIDTH = 150.0     # 箱の中の文字の、折り返す幅（pt）。これを超えるなら、折り返す
DIAMOND_TEXT_WIDTH = 100.0  # ひし形の中の文字の、折り返す幅（pt）
SLANT = 0.3                # 平行四辺形・台形・六角形の、傾き（箱の高さに対する割合）
SUBROUTINE_BAR = 8.0       # 定義済み処理の、左右の縦線の位置（辺からの距離）
CYLINDER_CAP = 6.0         # データベースの、上下の楕円の、縦の半径
PAD_X, PAD_Y = 12.0, 8.0   # 箱の内側の余白
MARGIN = 8.0               # 図の外側の余白
ARROW_LENGTH, ARROW_HALF_WIDTH = 8.0, 3.2


class FlowchartError(Exception):
    """図にできなかった（解析の誤りなど）。`line`は、コードの中の行（1始まり）で、分かる場合だけ入る。"""

    def __init__(self, message: str, line: Optional[int] = None):
        super().__init__(message)
        self.line = line


class FlowchartUnsupported(FlowchartError):
    """この変換器が、まだ対応していない書き方。従来のMermaidへ任せる（描画の前の判定。失敗ではない）。"""


@dataclass
class Node:
    id: str
    label: str
    shape: str = "rect"      # rect | round | stadium | circle | diamond ほか。独自記法（flowchart_notation.py）は、document・loop_start・loop_endも使う
    condition: str = ""      # ループ端の、終了条件（名前は`label`）。ほかの形では使わない


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    line: str = "solid"      # solid | dotted | thick
    arrow: bool = True


@dataclass
class Flowchart:
    direction: str = "TB"    # TB | BT | LR | RL
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# 1. 解析
# ---------------------------------------------------------------------------------------------

_HEADER_RE = re.compile(r'^(?:flowchart|graph)(?:\s+(TB|TD|BT|RL|LR))?\s*$')
_ID_RE = re.compile(r'[A-Za-z_][\w\-]*|[0-9]+|[^\W\d_][\w\-]*')   # 英数字・日本語。`-`を含むidは、矢印と区別するため、あとで調べる
_UNSUPPORTED_WORDS = ('subgraph', 'end', 'style', 'classDef', 'class', 'click', 'linkStyle', 'direction', 'accTitle', 'accDescr')

# 矢印。長い書き方から先に試す。(正規表現, 線, 矢じり)
_EDGE_PATTERNS = [
    (re.compile(r'-\.+->'), 'dotted', True),
    (re.compile(r'-\.+-(?!>)'), 'dotted', False),
    (re.compile(r'==+>'), 'thick', True),
    (re.compile(r'===+'), 'thick', False),
    (re.compile(r'--+>'), 'solid', True),
    (re.compile(r'---+'), 'solid', False),
]
# 文字つきの矢印: `-- 文字 -->`・`-. 文字 .->`・`== 文字 ==>`
_TEXT_EDGE_PATTERNS = [
    (re.compile(r'--\s+(.+?)\s+--+>'), 'solid', True),
    (re.compile(r'--\s+(.+?)\s+---+'), 'solid', False),
    (re.compile(r'-\.\s+(.+?)\s+\.+->'), 'dotted', True),
    (re.compile(r'==\s+(.+?)\s+==+>'), 'thick', True),
]

# 箱の形。(開き, {閉じ: 形})。長い開きから先に試す。
# 流れ図の定番の対応: 端子=stadium、処理=rect、判断=diamond、入出力=parallelogram、ループ端・準備=hexagon、
# 定義済み処理=subroutine、データベース=cylinder。
_SHAPES = [
    ('(((', {')))': 'doublecircle'}),
    ('((', {'))': 'circle'}),
    ('([', {'])': 'stadium'}),
    ('[(', {')]': 'cylinder'}),
    ('[[', {']]': 'subroutine'}),
    ('{{', {'}}': 'hexagon'}),
    ('[/', {'/]': 'parallelogram', '\\]': 'trapezoid'}),
    ('[\\', {'\\]': 'parallelogram_alt', '/]': 'trapezoid_alt'}),
    ('{', {'}': 'diamond'}),
    ('(', {')': 'round'}),
    ('[', {']': 'rect'}),
]
_UNSUPPORTED_SHAPE_OPENERS = ('>',)


def _clean_label(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    if re.search(r'<[A-Za-z/][^>]*>', text) or '&' in text:
        raise FlowchartUnsupported("HTML in a label is not supported.")
    return text.strip()


class _Statement:
    """1つの文（`A --> B & C -->|文字| D`）を、前から読む。"""

    def __init__(self, text: str, line: int):
        self.s = text
        self.i = 0
        self.line = line

    def skip_space(self):
        while self.i < len(self.s) and self.s[self.i] in ' \t':
            self.i += 1

    def at_end(self) -> bool:
        self.skip_space()
        return self.i >= len(self.s)

    def node(self) -> Node:
        self.skip_space()
        m = _ID_RE.match(self.s, self.i)
        if not m:
            raise FlowchartError(f"Unexpected text: {self.s[self.i:self.i + 20]!r}", self.line)
        ident = m.group(0)
        # idの末尾の`-`は、矢印の始まり（`A-->B`）。矢印を食べない
        while ident.endswith('-'):
            ident = ident[:-1]
        self.i += len(ident)
        if not ident:
            raise FlowchartError(f"Unexpected text: {self.s[self.i:self.i + 20]!r}", self.line)
        if ident in _UNSUPPORTED_WORDS:
            raise FlowchartUnsupported(f"'{ident}' is not supported.", self.line)
        rest = self.s[self.i:]
        if rest.startswith(':::'):
            raise FlowchartUnsupported("Class shorthand (:::) is not supported.", self.line)
        if rest.startswith('@{'):
            raise FlowchartUnsupported("Node attributes (@{...}) are not supported.", self.line)
        for opener in _UNSUPPORTED_SHAPE_OPENERS:
            if rest.startswith(opener):
                raise FlowchartUnsupported(f"The node shape starting with '{opener}' is not supported.", self.line)
        for opener, closers in _SHAPES:
            if rest.startswith(opener):
                end, closer = self._find_closer(rest, len(opener), tuple(closers))
                label = _clean_label(rest[len(opener):end])
                self.i += end + len(closer)
                return Node(ident, label, closers[closer])
        return Node(ident, '', 'rect')

    def _find_closer(self, rest: str, start: int, closers: Tuple[str, ...]) -> Tuple[int, str]:
        """引用符の外で、最初に現れる閉じを探す。戻りは (位置, 見つかった閉じ)。"""
        in_quote = False
        for k in range(start, len(rest)):
            if rest[k] == '"':
                in_quote = not in_quote
            elif not in_quote:
                for closer in closers:
                    if rest.startswith(closer, k):
                        return k, closer
        raise FlowchartError(f"The closing '{' or '.join(closers)}' is missing.", self.line)

    def edge(self) -> Optional[Tuple[str, str, bool, str]]:
        """矢印を読む。なければNone。戻りは (線, 文字, 矢じり)。"""
        self.skip_space()
        rest = self.s[self.i:]
        for pattern, line, arrow in _TEXT_EDGE_PATTERNS:
            m = pattern.match(rest)
            if m:
                self.i += m.end()
                return line, _clean_label(m.group(1)), arrow
        for pattern, line, arrow in _EDGE_PATTERNS:
            m = pattern.match(rest)
            if m:
                self.i += m.end()
                label = ''
                after = self.s[self.i:]
                if after.startswith('|'):
                    end = after.find('|', 1)
                    if end < 0:
                        raise FlowchartError("The closing '|' of the edge label is missing.", self.line)
                    label = _clean_label(after[1:end])
                    self.i += end + 1
                return line, label, arrow
        if rest.startswith(('<-', '<=', '<.', 'o--', 'x--', '--o', '--x', '~~~')):
            raise FlowchartUnsupported("This arrow form is not supported.", self.line)
        return None


def parse(code: str) -> Flowchart:
    """Mermaidのフローチャートを読む。対応しない書き方は`FlowchartUnsupported`、誤りは`FlowchartError`（行つき）。"""
    chart = Flowchart()
    header_seen = False
    for number, raw in enumerate(code.splitlines(), start=1):
        text = raw.split('%%', 1)[0].strip()
        if not text:
            continue
        if not header_seen:
            m = _HEADER_RE.match(text)
            if not m:
                raise FlowchartUnsupported("Not a flowchart or graph diagram.", number)
            chart.direction = {'TD': 'TB'}.get(m.group(1), m.group(1)) if m.group(1) else 'TB'
            header_seen = True
            continue
        for part in _split_statements(text):
            _parse_statement(chart, part, number)
    if not header_seen:
        raise FlowchartError("The diagram is empty.")
    if not chart.nodes:
        raise FlowchartError("The diagram has no nodes.")
    return chart


def _split_statements(text: str) -> List[str]:
    """`;`で区切る。ただし、引用符・括弧の中の`;`は、区切りにしない。"""
    parts, depth, quote, start = [], 0, False, 0
    for i, ch in enumerate(text):
        if ch == '"':
            quote = not quote
        elif not quote and ch in '([{':
            depth += 1
        elif not quote and ch in ')]}':
            depth -= 1
        elif not quote and depth <= 0 and ch == ';':
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _register(chart: Flowchart, node: Node):
    """ノードを登録する。2回目以降に、文字つきで書かれたら、その文字・形を採る（Mermaidと同じ）。"""
    known = chart.nodes.get(node.id)
    if known is None:
        chart.nodes[node.id] = node
    elif node.label or node.shape != 'rect':
        chart.nodes[node.id] = Node(node.id, node.label or known.label, node.shape if (node.label or node.shape != 'rect') else known.shape)


def _parse_statement(chart: Flowchart, text: str, line: int):
    st = _Statement(text, line)
    groups: List[List[Node]] = []
    links: List[Tuple[str, str, bool]] = []
    while True:
        group = [st.node()]
        while True:
            st.skip_space()
            if st.s.startswith('&', st.i):
                st.i += 1
                group.append(st.node())
            else:
                break
        groups.append(group)
        for node in group:
            _register(chart, node)
        if st.at_end():
            break
        edge = st.edge()
        if edge is None:
            raise FlowchartError(f"Unexpected text: {st.s[st.i:st.i + 20]!r}", line)
        links.append(edge)
        if st.at_end():
            raise FlowchartError("The arrow has no target node.", line)
    for (style, label, arrow), before, after in zip(links, groups, groups[1:]):
        for source in before:
            for target in after:
                chart.edges.append(Edge(source.id, target.id, label, style, arrow))


def supports(code: str) -> Tuple[bool, str]:
    """描画の前の、宣言的な判定。対応しない書き方があれば、(False, 理由)。構文の誤りは、ここでは「対応」とみなす（描画が、行つきで報告する）。"""
    try:
        parse(code)
    except FlowchartUnsupported as e:
        return False, str(e)
    except FlowchartError:
        return True, ''
    return True, ''


# ---------------------------------------------------------------------------------------------
# 2. 配置
# ---------------------------------------------------------------------------------------------

_MEASURE_WRAPPER = '''#set text(font: "Noto Sans JP", size: 11pt)
#let units = json(bytes(sys.inputs.units))
#context [#metadata(units.map(u => (u, measure(text(u)).width.pt()))) <widths>]
'''

_LAYOUT_WRAPPER = f'''#import "@preview/diagraph-layout:{DIAGRAPH_LAYOUT_VERSION}": layout-graph, node, edge
#let spec = json(bytes(sys.inputs.spec))
#let nodes = spec.nodes.map(n => node(n.id, width: n.w * 1pt, height: n.h * 1pt))
#let edges = spec.edges.map(e => edge(e.source, e.target, label: if e.lw != none {{ (width: e.lw * 1pt, height: e.lh * 1pt) }} else {{ none }}))
#let result = layout-graph(directed: true, engine: "dot", rankdir: spec.rankdir, nodesep: spec.nodesep, ranksep: spec.ranksep, ..nodes, ..edges)
#metadata(result) <layout>
'''

_width_cache: Dict[str, float] = {}
_CJK_NO_LINE_START = set('、。，．・：；？！）」』】〕〉》ゝゞー々ぁぃぅぇぉっゃゅょァィゥェォッャュョ)]},.:;?!')
_CJK_NO_LINE_END = set('（「『【〔〈《([{')


def cache_version() -> str:
    """図のSVGのキャッシュキーに入れる版。このモジュールの形・diagraph-layout・Typst・フォントのどれかが変われば、別のキーになる。"""
    return f"flowchart{FLOWCHART_VERSION}+layout{DIAGRAPH_LAYOUT_VERSION}+typst{typst_lib.__version__}{fonts_signature()}"


def _query(source: str, label: str, inputs: Dict[str, str]):
    """Typstのコードを、`sys.inputs`つきで実行し、`metadata`の値を、JSONで受け取る。"""
    directory = tempfile.mkdtemp(prefix="flowchart-")
    try:
        path = os.path.join(directory, "w.typ")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(source)
        out = typst_lib.query(path, label, field="value", one=True, format="json", root=directory,
                              font_paths=font_paths(ensure_fonts()), ignore_system_fonts=True, sys_inputs=inputs,
                              **typst_package_options())
        return json.loads(out)
    except typst_lib.TypstError as e:
        raise FlowchartError(f"Layout failed: {str(e).strip().splitlines()[0] if str(e).strip() else e}") from e
    finally:
        for name in os.listdir(directory):
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass
        try:
            os.rmdir(directory)
        except OSError:
            pass


def _is_word_char(ch: str) -> bool:
    """単語の途中では折らない文字。英数字（空白までの続き）と、カタカナの続き（長音・中点を含む）。"""
    return (ch.isascii() and not ch.isspace()) or '゠' <= ch <= 'ヿ' or ch in 'ー・ｰ'


def _units(text: str) -> List[str]:
    """折り返しの単位。英数字・カタカナの続きは、1語。日本語など、それ以外は、1文字ずつ。"""
    units, word = [], ''
    for ch in text:
        if ch == '\n':
            if word:
                units.append(word)
                word = ''
            units.append('\n')
        elif ch == ' ':
            if word:
                units.append(word)
                word = ''
            units.append(' ')
        elif _is_word_char(ch):
            if word and ch.isascii() != word[-1].isascii():
                units.append(word)      # 英数字とカタカナの境目では、語を分ける
                word = ''
            word += ch
        else:
            if word:
                units.append(word)
                word = ''
            units.append(ch)
    if word:
        units.append(word)
    return units


def _measure(texts: List[str]) -> None:
    """未測定の単位の幅を、Typstで測って、`_width_cache`に入れる（NODE_FONT_SIZEでの幅）。"""
    needed = sorted({u for t in texts for u in _units(t) if u != '\n' and u not in _width_cache})
    if not needed:
        return
    for unit, width in _query(_MEASURE_WRAPPER, "<widths>", {"units": json.dumps(needed)}):
        _width_cache[unit] = float(width)


def _width(unit: str, size: float) -> float:
    if unit not in _width_cache:
        _measure([unit])     # 通常は、layoutが、まとめて先に測っている。単独で呼ばれたときの保険
    return _width_cache[unit] * size / NODE_FONT_SIZE


def wrap(text: str, size: float, max_width: float) -> List[str]:
    """`max_width`（pt）に収まるよう、行に分ける。日本語は、文字の間で折る（行頭に来てはいけない記号は、前の行に付ける）。"""
    lines: List[str] = []
    current, current_width = '', 0.0
    for unit in _units(text):
        if unit == '\n':
            lines.append(current.rstrip())
            current, current_width = '', 0.0
            continue
        w = _width(unit, size)
        if current and current_width + w > max_width and unit != ' ':
            first = unit[0]
            if first in _CJK_NO_LINE_START or (current and current[-1] in _CJK_NO_LINE_END):
                current += unit
                current_width += w
                continue
            lines.append(current.rstrip())
            current, current_width = '', 0.0
        if unit == ' ' and not current:
            continue
        current += unit
        current_width += w
    lines.append(current.rstrip())
    return [ln for ln in lines] or ['']


def _text_size(lines: List[str], size: float) -> Tuple[float, float]:
    width = max((sum(_width(u, size) for u in _units(ln)) for ln in lines), default=0.0)
    return width, len(lines) * size * LINE_HEIGHT


def _length(value) -> float:
    return float(str(value).replace('pt', ''))


@dataclass
class _NodeBox:
    node: Node
    lines: List[str]
    width: float
    height: float
    x: float = 0.0
    y: float = 0.0


def _node_box(node: Node) -> _NodeBox:
    # ひし形は、文字の四角の2倍の大きさになるため、中の文字は、狭く折り返す
    lines = wrap(node.label or node.id, NODE_FONT_SIZE, DIAMOND_TEXT_WIDTH if node.shape == 'diamond' else MAX_TEXT_WIDTH)
    tw, th = _text_size(lines, NODE_FONT_SIZE)
    h = th + 2 * PAD_Y
    if node.shape == 'diamond':
        w, h = 2 * tw + 24, 2 * th + 16      # 文字の四角が、ひし形に収まる大きさ
    elif node.shape in ('circle', 'doublecircle'):
        w = h = math.hypot(tw, th) + 14 + (8 if node.shape == 'doublecircle' else 0)
    elif node.shape in _SLANTED:
        w = tw + 2 * PAD_X + 2 * SLANT * h
    elif node.shape == 'hexagon':
        w = tw + 2 * PAD_X + 1.6 * SLANT * h
    elif node.shape == 'subroutine':
        w = tw + 2 * PAD_X + 2 * SUBROUTINE_BAR
    elif node.shape == 'cylinder':
        w, h = tw + 2 * PAD_X, h + 2 * CYLINDER_CAP
    else:
        w = tw + 2 * PAD_X
    return _NodeBox(node, lines, max(w, 28.0), max(h, 28.0))


_SLANTED = ('parallelogram', 'parallelogram_alt', 'trapezoid', 'trapezoid_alt')


def _outline(box: '_NodeBox') -> Optional[List[Tuple[float, float]]]:
    """多角形の形の、頂点。多角形でない形（四角・楕円）は、None。"""
    x, y, w, h = box.x, box.y, box.width, box.height
    left, right, top, bottom = x - w / 2, x + w / 2, y - h / 2, y + h / 2
    s = SLANT * h
    shape = box.node.shape
    if shape == 'diamond':
        return [(x, top), (right, y), (x, bottom), (left, y)]
    if shape == 'hexagon':
        s = SLANT * h
        return [(left, y), (left + s, top), (right - s, top), (right, y), (right - s, bottom), (left + s, bottom)]
    if shape == 'parallelogram':       # 右へ傾く（上の辺が、右にずれる）
        return [(left + 2 * s, top), (right, top), (right - 2 * s, bottom), (left, bottom)]
    if shape == 'parallelogram_alt':
        return [(left, top), (right - 2 * s, top), (right, bottom), (left + 2 * s, bottom)]
    if shape == 'trapezoid':           # 上の辺が、狭い
        return [(left + s, top), (right - s, top), (right, bottom), (left, bottom)]
    if shape == 'trapezoid_alt':
        return [(left, top), (right, top), (right - s, bottom), (left + s, bottom)]
    return None


def _inside(box: '_NodeBox', px: float, py: float) -> bool:
    """点が、箱の形の内側か（辺の上を含む）。"""
    polygon = _outline(box)
    if polygon is not None:
        inside = False
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
                inside = not inside
        return inside
    if box.node.shape in ('circle', 'doublecircle'):
        return ((px - box.x) / (box.width / 2)) ** 2 + ((py - box.y) / (box.height / 2)) ** 2 <= 1.0
    return abs(px - box.x) <= box.width / 2 and abs(py - box.y) <= box.height / 2


def _snap_to_shape(point: Tuple[float, float], direction: Tuple[float, float], box: '_NodeBox') -> Tuple[float, float]:
    """矢印の端を、箱の、実際の形の縁に合わせる。

    Graphvizは、箱の大きさだけを知っていて、形は知らない（`diagraph-layout`は、形を受け取らない）。そのため、ひし形などでは、
    線の端が、形の縁から離れたり、中に入ったりする。`direction`（箱の中へ向かう向き）に沿って、縁まで動かす。
    """
    dx, dy = direction
    norm = math.hypot(dx, dy)
    if norm < 1e-6:     # 向きが決まらないときは、箱の中心へ向かう
        dx, dy = box.x - point[0], box.y - point[1]
        norm = math.hypot(dx, dy) or 1.0
    dx, dy = dx / norm, dy / norm
    limit = math.hypot(box.width, box.height)
    start_inside = _inside(box, *point)
    sign = -1.0 if start_inside else 1.0      # 内側からは、外へ。外側からは、中へ
    near, far, step = 0.0, None, 0.5
    t = 0.0
    while t <= limit:
        t += step
        if _inside(box, point[0] + sign * dx * t, point[1] + sign * dy * t) != start_inside:
            far = t
            break
        near = t
    if far is None:
        return point
    for _ in range(24):
        mid = (near + far) / 2
        if _inside(box, point[0] + sign * dx * mid, point[1] + sign * dy * mid) != start_inside:
            far = mid
        else:
            near = mid
    t = near if start_inside else far     # 縁の、内側の側の点（縁の上）を返す
    return (point[0] + sign * dx * t, point[1] + sign * dy * t)


def layout(chart: Flowchart) -> dict:
    """配置を求める。戻りは、描画に要るもの（箱・矢印・全体の大きさ）。座標は、左上を原点にした、下向きがプラスのpt。"""
    _measure([n.label or n.id for n in chart.nodes.values()] + [e.label for e in chart.edges if e.label])
    boxes = {i: _node_box(n) for i, n in chart.nodes.items()}
    edge_labels = []
    for e in chart.edges:
        if e.label:
            lines = wrap(e.label, EDGE_FONT_SIZE, MAX_TEXT_WIDTH)
            tw, th = _text_size(lines, EDGE_FONT_SIZE)
            edge_labels.append((lines, tw + 8, th + 4))
        else:
            edge_labels.append(None)
    spec = {
        "rankdir": chart.direction, "nodesep": "0.35", "ranksep": "0.5",
        "nodes": [{"id": i, "w": b.width, "h": b.height} for i, b in boxes.items()],
        "edges": [{"source": e.source, "target": e.target,
                   "lw": lab[1] if lab else None, "lh": lab[2] if lab else None} for e, lab in zip(chart.edges, edge_labels)],
    }
    result = _query(_LAYOUT_WRAPPER, "<layout>", {"spec": json.dumps(spec)})
    if result.get("errored"):
        raise FlowchartError("Layout failed.")
    height = _length(result["height"])
    for item in result["nodes"]:
        box = boxes[item["name"]]
        box.x, box.y = _length(item["x"]), height - _length(item["y"])
    # 矢印は、(始点, 終点)の組で引き当てる（出力の順序は、入力の順序と同じとは限らない）。同じ組が複数あれば、順に使う
    pending: Dict[Tuple[str, str], List[dict]] = {}
    for item in result["edges"]:
        pending.setdefault((item["tail"], item["head"]), []).append(item)
        pending.setdefault((item["head"], item["tail"]), pending[(item["tail"], item["head"])])
    routes = []
    for e, lab in zip(chart.edges, edge_labels):
        items = pending.get((e.source, e.target)) or []
        item = items.pop(0) if items else None
        if item is None:
            raise FlowchartError(f"Layout lost the edge {e.source} -> {e.target}.")
        points = [(_length(p["x"]), height - _length(p["y"])) for p in item["points"]]
        if points and _near(points[0], boxes[e.target]) and not _near(points[0], boxes[e.source]):
            points.reverse()   # 始点がtargetの側にあるときは、向きを入れ替える
        if len(points) >= 2:
            # 線の端を、箱の形の縁に合わせる。始点は、箱から出ていく向きの逆（箱の中へ）、終点は、入っていく向きへ動かす
            first, last = points[0], points[-1]
            points[0] = _snap_to_shape(first, (first[0] - points[1][0], first[1] - points[1][1]), boxes[e.source])
            points[-1] = _snap_to_shape(last, (last[0] - points[-2][0], last[1] - points[-2][1]), boxes[e.target])
        label_pos = None
        if lab and item.get("label"):
            label_pos = (_length(item["label"]["x"]), height - _length(item["label"]["y"]))
        routes.append({"edge": e, "points": points, "label": lab, "label_pos": label_pos})
    return {"width": _length(result["width"]), "height": height, "boxes": boxes, "routes": routes}


def _near(point: Tuple[float, float], box: _NodeBox) -> bool:
    return abs(point[0] - box.x) <= box.width / 2 + 2 and abs(point[1] - box.y) <= box.height / 2 + 2


# ---------------------------------------------------------------------------------------------
# 3. 描画
# ---------------------------------------------------------------------------------------------

def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _f(value: float) -> str:
    return f"{value:.2f}".rstrip('0').rstrip('.')


def _text_element(lines: List[str], cx: float, cy: float, size: float, extra: str = '') -> str:
    line_height = size * LINE_HEIGHT
    top = cy - (len(lines) - 1) * line_height / 2
    parts = []
    for k, line in enumerate(lines):
        y = top + k * line_height + size * 0.35     # 文字の縦の中心を、yに合わせる（dominant-baselineに頼らない）
        parts.append(f'<text x="{_f(cx)}" y="{_f(y)}" text-anchor="middle" font-size="{_f(size)}"{extra}>{_esc(line)}</text>')
    return ''.join(parts)


def _shape(box: _NodeBox) -> str:
    x, y, w, h = box.x, box.y, box.width, box.height
    common = f'fill="{NODE_FILL}" stroke="{STROKE}" stroke-width="1"'
    shape = box.node.shape
    polygon = _outline(box)
    if polygon is not None:
        pts = ' '.join(f"{_f(px)},{_f(py)}" for px, py in polygon)
        return f'<polygon points="{pts}" {common}/>'
    if shape == 'circle':
        return f'<ellipse cx="{_f(x)}" cy="{_f(y)}" rx="{_f(w / 2)}" ry="{_f(h / 2)}" {common}/>'
    if shape == 'doublecircle':
        return (f'<ellipse cx="{_f(x)}" cy="{_f(y)}" rx="{_f(w / 2)}" ry="{_f(h / 2)}" {common}/>'
                f'<ellipse cx="{_f(x)}" cy="{_f(y)}" rx="{_f(w / 2 - 4)}" ry="{_f(h / 2 - 4)}" fill="none" stroke="{STROKE}" stroke-width="1"/>')
    if shape == 'subroutine':
        bar = SUBROUTINE_BAR
        return (f'<rect x="{_f(x - w / 2)}" y="{_f(y - h / 2)}" width="{_f(w)}" height="{_f(h)}" {common}/>'
                f'<path d="M{_f(x - w / 2 + bar)},{_f(y - h / 2)} V{_f(y + h / 2)} M{_f(x + w / 2 - bar)},{_f(y - h / 2)} V{_f(y + h / 2)}" '
                f'fill="none" stroke="{STROKE}" stroke-width="1"/>')
    if shape == 'cylinder':
        ry, rx, left, right = CYLINDER_CAP, w / 2, x - w / 2, x + w / 2
        top, bottom = y - h / 2 + ry, y + h / 2 - ry
        body = (f'M{_f(left)},{_f(top)} A{_f(rx)},{_f(ry)} 0 0 1 {_f(right)},{_f(top)} V{_f(bottom)} '
                f'A{_f(rx)},{_f(ry)} 0 0 1 {_f(left)},{_f(bottom)} Z')
        cap = f'M{_f(left)},{_f(top)} A{_f(rx)},{_f(ry)} 0 0 0 {_f(right)},{_f(top)}'
        return f'<path d="{body}" {common}/><path d="{cap}" fill="none" stroke="{STROKE}" stroke-width="1"/>'
    radius = {'round': 6.0, 'stadium': h / 2}.get(shape, 0.0)
    r = f' rx="{_f(radius)}" ry="{_f(radius)}"' if radius else ''
    return f'<rect x="{_f(x - w / 2)}" y="{_f(y - h / 2)}" width="{_f(w)}" height="{_f(h)}"{r} {common}/>'


def _route(points: List[Tuple[float, float]], arrow: bool) -> Tuple[str, str]:
    """矢印の曲線（3次ベジェ）と、矢じり。矢じりの分だけ、線を短くする。"""
    pts = list(points)
    head = ''
    if arrow and len(pts) >= 2:
        tip = pts[-1]
        # 矢じりの向きは、終点に入ってくる向き（最後の、遠い制御点から終点）
        ref = next((p for p in reversed(pts[:-1]) if math.hypot(p[0] - tip[0], p[1] - tip[1]) > 0.5), pts[-2])
        dx, dy = tip[0] - ref[0], tip[1] - ref[1]
        norm = math.hypot(dx, dy) or 1.0
        ux, uy = dx / norm, dy / norm
        base = (tip[0] - ux * ARROW_LENGTH, tip[1] - uy * ARROW_LENGTH)
        left = (base[0] - uy * ARROW_HALF_WIDTH, base[1] + ux * ARROW_HALF_WIDTH)
        right = (base[0] + uy * ARROW_HALF_WIDTH, base[1] - ux * ARROW_HALF_WIDTH)
        head = f'<polygon points="{_f(tip[0])},{_f(tip[1])} {_f(left[0])},{_f(left[1])} {_f(right[0])},{_f(right[1])}" fill="{STROKE}"/>'
        pts[-1] = base
    d = f"M{_f(pts[0][0])},{_f(pts[0][1])}"
    rest = pts[1:]
    if len(rest) % 3 == 0:
        for k in range(0, len(rest), 3):
            c1, c2, p = rest[k], rest[k + 1], rest[k + 2]
            d += f" C{_f(c1[0])},{_f(c1[1])} {_f(c2[0])},{_f(c2[1])} {_f(p[0])},{_f(p[1])}"
    else:
        for p in rest:
            d += f" L{_f(p[0])},{_f(p[1])}"
    return d, head


def render_svg(code: str) -> str:
    """Mermaidのフローチャートを、SVGの文字列にする。対応しない書き方は`FlowchartUnsupported`、誤りは`FlowchartError`。"""
    chart = parse(code)
    placed = layout(chart)
    width, height = placed["width"] + 2 * MARGIN, placed["height"] + 2 * MARGIN
    body = []
    for route in placed["routes"]:
        edge = route["edge"]
        d, head = _route(route["points"], edge.arrow)
        style = {'solid': '1.2', 'thick': '2.6', 'dotted': '1.2'}[edge.line]
        dash = ' stroke-dasharray="4 3"' if edge.line == 'dotted' else ''
        body.append(f'<path d="{d}" fill="none" stroke="{STROKE}" stroke-width="{style}"{dash}/>{head}')
    for box in placed["boxes"].values():
        body.append(_shape(box) + _text_element(box.lines, box.x, box.y, NODE_FONT_SIZE))
    for route in placed["routes"]:
        if route["label"] and route["label_pos"]:
            lines = route["label"][0]
            body.append(_text_element(lines, route["label_pos"][0], route["label_pos"][1], EDGE_FONT_SIZE))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(width)}pt" height="{_f(height)}pt" '
            f'viewBox="{_f(-MARGIN)} {_f(-MARGIN)} {_f(width)} {_f(height)}" font-family="{FONT_FAMILY}" fill="{STROKE}">'
            + ''.join(body) + '</svg>')
