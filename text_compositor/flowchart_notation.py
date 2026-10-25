"""JIS X 0121に準じたフローチャートの独自記法（`flowchart`フェンス。#536）の解析。設計は`doc/flowchart-notation.md`。

字下げとキーワードを読み、`flowchart_render.Flowchart`（ノードと矢印）にする。配置・描画は、`flowchart_render`の層を使う。
解析は、行ごとにキーワードで判別する小さな手書きの解析器である。誤りは、`FlowchartError`（行つき）で知らせる。
"""
import re
from dataclasses import dataclass
from typing import List, Tuple

from text_compositor.flowchart_render import Edge, Flowchart, FlowchartError, Node, draw_svg

# キーワード → 図記号の形。キーワードのない行は、処理（rect）。
_SHAPES = {
    'start': 'stadium', 'end': 'stadium', 'terminal': 'stadium',
    'process': 'rect', 'judge': 'diamond', 'data': 'parallelogram',
    'sub': 'subroutine', 'prep': 'hexagon', 'doc': 'document',
}
_DEFAULT_TEXT = {'start': 'start', 'end': 'end'}   # 文字を省いたら、その言葉を出す
_KEYWORDS = set(_SHAPES) | {'loop'}

_KEYWORD_RE = re.compile(r'^([a-z]+)(?=\s|$)')
_ENDLOOP_RE = re.compile(r'^endloop(?=\s|:|$)')
_BRANCH_RE = re.compile(r'^([^:]+):\s*(.*)$')

Tails = List[Tuple[str, str]]   # 次の図記号へつなぐ、(出口のノードid, 矢印の文字)


@dataclass
class _Line:
    number: int
    indent: int
    text: str


def _scan(code: str) -> List[_Line]:
    """空行と`//`の注釈を除き、字下げを調べる。字下げは、半角の空白だけ。1段の幅は、最初の字下げで決める。"""
    lines: List[_Line] = []
    unit = 0
    for number, raw in enumerate(code.splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith('//'):
            continue
        lead = raw[:len(raw) - len(raw.lstrip(' \t'))]
        if '\t' in lead:
            raise FlowchartError("Tabs are not allowed in indentation; use spaces.", number)
        indent = len(lead)
        if indent and not unit:
            unit = indent
        if unit and indent % unit:
            raise FlowchartError(f"Indentation must be a multiple of {unit} spaces.", number)
        lines.append(_Line(number, indent, text))
    return lines


def _quoted(raw: str, line: int) -> Tuple[str, str]:
    """`"`で始まる文字を読む。(中身, 閉じた`"`より後ろ)を返す。`\\"`は`"`、`\\n`は改行。"""
    out: List[str] = []
    i = 1
    while i < len(raw):
        ch = raw[i]
        if ch == '\\' and i + 1 < len(raw) and raw[i + 1] in '"n':
            out.append('"' if raw[i + 1] == '"' else '\n')
            i += 2
            continue
        if ch == '"':
            return ''.join(out), raw[i + 1:].strip()
        out.append(ch)
        i += 1
    raise FlowchartError("Unclosed quote.", line)


def _text(raw: str, line: int) -> str:
    """図記号の中の文字。`"`でくくってもよい。くくらないときの`\\n`は、改行。"""
    raw = raw.strip()
    if raw.startswith('"'):
        text, rest = _quoted(raw, line)
        if rest:
            raise FlowchartError("Unexpected text after the closing quote.", line)
        return text
    return raw.replace('\\n', '\n')


def _is_endloop(text: str) -> bool:
    return bool(_ENDLOOP_RE.match(text))


class _Parser:
    def __init__(self, lines: List[_Line]):
        self.lines = lines
        self.pos = 0
        self.chart = Flowchart(orthogonal=True)     # 独自記法の図は、線を水平・垂直だけで引く（#540）
        self.count = 0
        self.loop_names: List[str] = []

    # --- ノードと矢印 ---

    def _new(self, label: str, shape: str, condition: str = '') -> Node:
        self.count += 1
        node = Node(f"n{self.count}", label, shape, condition)
        self.chart.nodes[node.id] = node
        return node

    def _connect(self, tails: Tails, node: Node):
        for source, label in tails:
            self.chart.edges.append(Edge(source, node.id, label))

    def _peek_indent(self) -> int:
        return self.lines[self.pos].indent if self.pos < len(self.lines) else -1

    # --- 構文 ---

    def block(self, indent: int, tails: Tails) -> Tails:
        """同じ深さの行を、続けて読む。浅い行、または`endloop`で終わる（`endloop`は、外側の`loop`が受ける）。"""
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.indent < indent or _is_endloop(line.text):
                break
            if line.indent > indent:
                raise FlowchartError("Unexpected indentation.", line.number)
            self.pos += 1
            tails = self.statement(line, tails)
        return tails

    def statement(self, line: _Line, tails: Tails) -> Tails:
        text = line.text
        match = None if text.startswith('"') else _KEYWORD_RE.match(text)
        if not match or match.group(1) not in _KEYWORDS:
            return self.symbol('process', text, line, tails)
        keyword, rest = match.group(1), text[match.end():]
        if keyword == 'judge':
            return self.judge(line, rest, tails)
        if keyword == 'loop':
            return self.loop(line, rest, tails)
        return self.symbol(keyword, rest, line, tails)

    def symbol(self, keyword: str, rest: str, line: _Line, tails: Tails) -> Tails:
        label = _text(rest, line.number) if rest.strip() else _DEFAULT_TEXT.get(keyword, '')
        if not label:
            raise FlowchartError(f"'{keyword}' needs text.", line.number)
        node = self._new(label, _SHAPES[keyword])
        self._connect(tails, node)
        return [] if keyword == 'end' else [(node.id, '')]   # `end`の後ろへは、つながらない

    def judge(self, line: _Line, rest: str, tails: Tails) -> Tails:
        label = _text(rest, line.number) if rest.strip() else ''
        if not label:
            raise FlowchartError("'judge' needs text.", line.number)
        node = self._new(label, 'diamond')
        self._connect(tails, node)
        if self._peek_indent() <= line.indent:
            raise FlowchartError("A judge needs at least two branches ('label:' lines).", line.number)
        branch_indent = self._peek_indent()
        merged: Tails = []
        count = 0
        while self._peek_indent() >= branch_indent:
            branch = self.lines[self.pos]
            if branch.indent > branch_indent:
                raise FlowchartError("Unexpected indentation.", branch.number)
            match = _BRANCH_RE.match(branch.text)
            if not match or not match.group(1).strip():
                raise FlowchartError("A branch must start with 'label:'.", branch.number)
            self.pos += 1
            count += 1
            branch_tails: Tails = [(node.id, match.group(1).strip())]
            inline = match.group(2).strip()
            if inline:
                if _is_endloop(inline) or re.match(r'^loop(?=\s|$)', inline):
                    raise FlowchartError("'loop' and 'endloop' must be on their own lines.", branch.number)
                branch_tails = self.statement(_Line(branch.number, branch_indent, inline), branch_tails)
            if self._peek_indent() > branch_indent:
                branch_tails = self.block(self._peek_indent(), branch_tails)
            merged += branch_tails      # 全部の分岐が、次の行で合流する。`end`で終わる分岐は、空
        if count < 2:
            raise FlowchartError("A judge needs at least two branches.", line.number)
        return merged

    def loop(self, line: _Line, rest: str, tails: Tails) -> Tails:
        name, condition = self._loop_parts(rest, line.number)
        if not name:
            raise FlowchartError("'loop' needs a name.", line.number)
        if name in self.loop_names:
            raise FlowchartError(f"The loop name '{name}' is already used by an enclosing loop.", line.number)
        start = self._new(name, 'loop_start', condition)
        self._connect(tails, start)
        self.loop_names.append(name)
        body: Tails = [(start.id, '')]
        if self._peek_indent() > line.indent:
            body = self.block(self._peek_indent(), body)
        closing = self.lines[self.pos] if self.pos < len(self.lines) else None
        if closing is None or closing.indent != line.indent or not _is_endloop(closing.text):
            raise FlowchartError(f"The loop '{name}' has no matching endloop.", line.number)
        self.pos += 1
        after = closing.text[len('endloop'):].strip()
        end_condition = ''
        if after.startswith(':'):
            end_condition = _text(after[1:], closing.number) if after[1:].strip() else ''
        elif after:
            raise FlowchartError("'endloop' takes no name; write 'endloop: condition' for a test at the end.", closing.number)
        if condition and end_condition:
            raise FlowchartError("A loop condition goes at either the start or the end, not both.", closing.number)
        end = self._new(name, 'loop_end', end_condition)
        self._connect(body, end)
        self.loop_names.pop()
        return [(end.id, '')]

    @staticmethod
    def _loop_parts(rest: str, line: int) -> Tuple[str, str]:
        """`名前: 条件`を、(名前, 条件)に分ける。名前を`"`でくくれば、名前の中に`:`を書ける。"""
        rest = rest.strip()
        if rest.startswith('"'):
            name, tail = _quoted(rest, line)
            if tail and not tail.startswith(':'):
                raise FlowchartError("Unexpected text after the closing quote.", line)
            condition = tail[1:]
        elif ':' in rest:
            name, condition = rest.split(':', 1)
            name = name.strip()
        else:
            name, condition = rest, ''
        return name, (_text(condition, line) if condition.strip() else '')


def render_svg(code: str) -> str:
    """`flowchart`フェンスの中身を、SVGの文字列にする。誤りは`FlowchartError`（行つき）。"""
    return draw_svg(parse(code))


def parse(code: str) -> Flowchart:
    """`flowchart`フェンスの中身を読む。誤りは`FlowchartError`（行つき）。"""
    lines = _scan(code)
    if not lines:
        raise FlowchartError("The diagram is empty.")
    if lines[0].indent:
        raise FlowchartError("The first line must not be indented.", lines[0].number)
    parser = _Parser(lines)
    parser.block(0, [])
    if parser.pos < len(lines):
        stray = lines[parser.pos]
        raise FlowchartError("'endloop' has no matching loop." if _is_endloop(stray.text) else "Unexpected indentation.", stray.number)
    return parser.chart
