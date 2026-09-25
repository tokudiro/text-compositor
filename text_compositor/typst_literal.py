"""Typstの文字列リテラルを組み立てる補助関数。"""
import re

def escape_string_literal(text):
    return str(text).replace('\\', '\\\\').replace('"', '\\"')

# 区切り記号の直後、およびCamelCaseの境界（小文字/数字→大文字）。
_SOFT_BREAK_AFTER_RE = re.compile(r'([/_.:()\-])')
_SOFT_BREAK_CAMEL_RE = re.compile(r'([a-z0-9])([A-Z])')
_ZERO_WIDTH_SPACE = chr(0x200b)

def insert_soft_break_hints(text):
    """区切り記号の直後・CamelCaseの境界にゼロ幅スペース(U+200B)を挿入する（#269）。
    Typstはスペースを含まない長い文字列（テストパス・関数名等）を1語として扱い、
    表セル内で折り返さずにはみ出す。ZWSPは見た目に影響せず、改行可能点としてのみ働く。"""
    text = _SOFT_BREAK_AFTER_RE.sub(lambda m: m.group(1) + _ZERO_WIDTH_SPACE, text)
    text = _SOFT_BREAK_CAMEL_RE.sub(lambda m: m.group(1) + _ZERO_WIDTH_SPACE + m.group(2), text)
    return text

def _typst_str_or_none(value):
    """PythonのNone/文字列をTypstの`none`/文字列リテラルへ変換する（#42のheader/footer等）。"""
    if value is None:
        return "none"
    return f'"{escape_string_literal(str(value))}"'

def _typst_multiline_literal(text):
    """複数行の文字列を、改行を`\\n`とした1行のTypst文字列リテラルにする。値はデータとして埋め込むため、
    `#`や`*`等はMarkup記法として解釈されない。テンプレート側が`\\n`をlinebreak()等へ変換する。"""
    return '"' + escape_string_literal(text.replace('\r\n', '\n')).replace('\r', '').replace('\n', '\\n') + '"'
