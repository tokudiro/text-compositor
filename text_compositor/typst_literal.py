"""Typstの文字列リテラルを組み立てる補助関数。"""

def escape_string_literal(text):
    return str(text).replace('\\', '\\\\').replace('"', '\\"')

def _typst_str_or_none(value):
    """PythonのNone/文字列をTypstの`none`/文字列リテラルへ変換する（#42のheader/footer等）。"""
    if value is None:
        return "none"
    return f'"{escape_string_literal(str(value))}"'

def _typst_multiline_literal(text):
    """複数行の文字列を、改行を`\\n`とした1行のTypst文字列リテラルにする。値はデータとして埋め込むため、
    `#`や`*`等はMarkup記法として解釈されない。テンプレート側が`\\n`をlinebreak()等へ変換する。"""
    return '"' + escape_string_literal(text.replace('\r\n', '\n')).replace('\r', '').replace('\n', '\\n') + '"'
