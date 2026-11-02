"""`table`フェンス（#554）の解析。CSV形式の本文と、開始行の属性`{...}`から、表の中身と見出しの指定を取り出す。

描画（PDF・HTML）には依存しない。誤りは`TableFenceError`で返し、診断への変換は呼び出し側が行う。
"""
import csv
import io
import re
from dataclasses import dataclass

# renderer_layout.FENCE_ATTR_REと同じ形。rendererを取り込むと循環するため、ここに持つ。
_ATTR_RE = re.compile(r'(\w+)=([^\s{}]+)')
_DELIMITERS = {'comma': ',', 'tab': '\t'}
_KNOWN_ATTRS = ('header_rows', 'header_cols', 'delimiter')


class TableFenceError(Exception):
    """`table`フェンスの誤り。`line`は本文の何行目か（1始まり）。属性の誤りなど、行を特定できないときはNone。"""

    def __init__(self, message, line=None):
        super().__init__(message)
        self.line = line


@dataclass
class TableSpec:
    rows: list          # 空行を除いた、セルの文字列の2次元リスト。すべての行が同じ列数
    cols: int
    header_rows: int
    header_cols: int


def _int_attr(attrs, key, default, minimum=0):
    val = attrs.get(key)
    if val is None:
        return default
    try:
        n = int(val)
    except ValueError:
        raise TableFenceError(f"table fence: {key}={val} is not an integer.")
    if n < minimum:
        raise TableFenceError(f"table fence: {key} must be {minimum} or greater, got {n}.")
    return n


def parse_table_attrs(attrs_str):
    """開始行の属性部分（例: `{header_cols=1 delimiter=tab}`）を、検証して辞書で返す。
    未知の属性は、綴りの誤りを黙って見逃さないよう、誤りにする。"""
    attrs = dict(_ATTR_RE.findall(attrs_str or ''))
    for key in attrs:
        if key not in _KNOWN_ATTRS:
            raise TableFenceError(f"table fence: unknown option {key!r}; expected one of {', '.join(_KNOWN_ATTRS)}.")
    return attrs


def parse_table_fence(content, attrs_str=''):
    """`table`フェンスの本文と属性から、`TableSpec`を作る。"""
    attrs = parse_table_attrs(attrs_str)
    delim_name = attrs.get('delimiter', 'comma')
    if delim_name not in _DELIMITERS:
        raise TableFenceError(f"table fence: delimiter={delim_name} is invalid; expected comma or tab.")
    header_rows = _int_attr(attrs, 'header_rows', 1)
    header_cols = _int_attr(attrs, 'header_cols', 0)

    # 行分割をcsv.readerに任せる（クォート内の改行を保つため。.csvの章と同じ理由）。
    # line_numは、いま読み終えた行（複数行のセルなら、その最後）を指すので、前回の値＋1が開始行になる。
    reader = csv.reader(io.StringIO(content, newline=''), delimiter=_DELIMITERS[delim_name])
    rows = []
    starts = []
    prev_end = 0
    for row in reader:
        start = prev_end + 1
        prev_end = reader.line_num
        if row:   # 空行は読み飛ばす（末尾の改行や、貼り付けの余白）
            rows.append(row)
            starts.append(start)
    if not rows:
        raise TableFenceError("table fence: the table is empty.")

    cols = len(rows[0])
    for row, start in zip(rows[1:], starts[1:]):
        if len(row) != cols:
            raise TableFenceError(f"table fence: expected {cols} columns (from the first row), got {len(row)}.", line=start)
    if header_rows > len(rows):
        raise TableFenceError(f"table fence: header_rows={header_rows} exceeds the number of rows ({len(rows)}).")
    if header_cols > cols:
        raise TableFenceError(f"table fence: header_cols={header_cols} exceeds the number of columns ({cols}).")
    return TableSpec(rows=rows, cols=cols, header_rows=header_rows, header_cols=header_cols)
