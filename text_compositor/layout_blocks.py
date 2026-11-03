"""`:::`のレイアウトブロックの切り出し（#560）。

以前は、1本の正規表現で「最初の`:::`の行」をブロックの終わりとしていた。`layout-right`などの中に
`::: layers`を入れ子にすると、`layers`の閉じが外側の終わりと取り違えられるため、行を順に読んで
入れ子の深さを数える方式に替えた。入れ子にできるのは`layers`だけである。他の`:::`の行は、
以前と同じく、ブロックの中の地の文として扱う。`layers`自身は、最上位のブロックにもなる
（group(2)は、`{...}`でなく、見出し行の文字列）。
"""
import re
from typing import List, Optional, Tuple

# 最上位のブロックの開始行。ブロック名の後ろに`{key=value ...}`というPandoc風の属性を書ける（#83）。
_OPEN_RE = re.compile(
    r'^::: *(layout-right|layout-left|layout-compare|layout-feature|layout-columns|'
    r'layout-takahashi|align)(?: +\{([^}\r\n]*)\})? *$')
# `layers`の開始行。見出し行の文字列は、重ね全体の代替テキストになる。最上位でも、他のブロックの
# 入れ子でも置ける。
_LAYERS_OPEN_RE = re.compile(r'^::: *layers(?: +([^\r\n]*?))? *$')
_CLOSE_RE = re.compile(r'^::: *$')


class LayoutBlockMatch:
    """切り出した1ブロック。`re.Match`と同じ形（group・start・end）で読めるようにしてある。

    group(1)=ブロック名、group(2)=`{...}`の中身（なければNone。layersは、見出し行の文字列）、
    group(3)=ブロックの中身。"""

    def __init__(self, start: int, end: int, body_start: int, kind: str,
                 attrs: Optional[str], body: str):
        self._start, self._end, self._body_start = start, end, body_start
        self._groups = (None, kind, attrs, body)

    def group(self, index: int = 0):
        if index == 0:
            raise NotImplementedError("group(0) is not supported")
        return self._groups[index]

    def start(self, index: int = 0) -> int:
        return self._body_start if index == 3 else self._start

    def end(self, index: int = 0) -> int:
        return self._end


class LayersMatch:
    """`layout-*`の中に置かれた`::: layers`を、「図・画像の1マッチ」として扱うためのもの。

    DIAGRAM_OR_IMAGE_REのマッチと同じ位置の読み方（start・end）を持つ。フェンスや画像のグループ
    （lang・image・attrs・code）は、すべてNoneを返す。"""

    def __init__(self, block: LayoutBlockMatch):
        self.header = block.group(2)
        self.body = block.group(3)
        self._start, self._end = block.start(), block.end()

    def group(self, name):
        return None

    def start(self, index: int = 0) -> int:
        return self._start

    def end(self, index: int = 0) -> int:
        return self._end


def _in_ranges(offset: int, ranges: List[Tuple[int, int]]) -> bool:
    # 外側のフェンス（使い方説明のサンプルなど）の中の行は、ブロックの開始・終わりとして数えない。
    # 厳密な不等号にする理由は、renderer.py の`_in_ranges`と同じ（#127）。
    return any(start < offset < end for start, end in ranges)


def find_layout_blocks(text: str, protected: List[Tuple[int, int]]) -> List[LayoutBlockMatch]:
    """textから、最上位の`:::`ブロックを、先頭から順に切り出す。

    protectedは、フェンスの中として除外する文字オフセットの範囲（renderer.py の`_fenced_char_ranges`）。
    閉じていないブロックは、以前と同じく、ブロックとして扱わない。"""
    blocks: List[LayoutBlockMatch] = []
    depth = 0
    open_start = body_start = 0
    kind = attrs = None
    pos = 0
    while pos <= len(text):
        newline = text.find('\n', pos)
        line_end = len(text) if newline < 0 else newline
        line = text[pos:line_end]
        bare = line[:-1] if line.endswith('\r') else line
        if bare.startswith(':::') and not _in_ranges(pos, protected):
            if depth == 0:
                m = _OPEN_RE.match(bare) or _LAYERS_OPEN_RE.match(bare)
                if m:
                    depth = 1
                    # layersだけは、`{...}`の属性でなく、見出し行の文字列（代替テキスト）を渡す
                    kind = 'layers' if m.re is _LAYERS_OPEN_RE else m.group(1)
                    attrs = m.group(1) if kind == 'layers' else m.group(2)
                    open_start = pos
                    body_start = min(line_end + 1, len(text))
            elif _LAYERS_OPEN_RE.match(bare):
                depth += 1
            elif _CLOSE_RE.match(bare):
                depth -= 1
                if depth == 0:
                    # 本文の末尾の改行（開始行の直後が閉じの行のときは、本文なし）は、含めない
                    body_end = pos - 2 if text.endswith('\r\n', 0, pos) else pos - 1
                    body = text[body_start:body_end] if body_end >= body_start else ''
                    blocks.append(LayoutBlockMatch(open_start, line_end, body_start, kind, attrs, body))
        if newline < 0:
            break
        pos = newline + 1
    return blocks
