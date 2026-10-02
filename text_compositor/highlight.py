"""HTML出力の、シンタックスハイライト（#218）。

Pygmentsで、コードを、`<span class="k">…</span>`の形のHTMLにする。Pygmentsは、任意の依存で、無ければ、ハイライトなし（等幅の素の表示）に戻る
（PyPIの最小の依存を、増やさないため。`pip install text-compositor[highlight]`、またはObunzuの同梱で使える）。
色は、スタイルのCSSで決まり、ライト・ダークは、`prefers-color-scheme`で切り替える。出力は、スクリプトを含まない
（コードの文字は、Pygmentsが、すべてエスケープする）。
"""
import functools

# ファイルとして開けるファイルの拡張子と、Pygmentsの言語名（#218）。図・Markdown・.txt・.csv・.svgは、別の扱いで、ここに含めない。
SOURCE_FILE_LANGS = {
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.toml': 'toml', '.xml': 'xml', '.ini': 'ini',
    '.html': 'html', '.htm': 'html', '.css': 'css', '.sql': 'sql',
    '.sh': 'bash', '.bash': 'bash', '.ps1': 'powershell',
    '.py': 'python', '.js': 'javascript', '.mjs': 'javascript', '.ts': 'typescript', '.jsx': 'jsx', '.tsx': 'tsx',
    '.java': 'java', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp', '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
}

# ハイライトする大きさの上限（バイト）。ハイライトすると、HTMLは、元の約8〜24倍になる（実測: 512 KBのYAMLで、約10 MB）。
# 超える大きさは、色を付けずに、等幅の素のテキストで表示する（ファイルとして開くときの上限は、別。html_output.TEXT_MAX_BYTES）。
HIGHLIGHT_MAX_BYTES = 128 * 1024

_LIGHT_STYLE = 'default'
_DARK_STYLE = 'github-dark'
CODE_CLASS = 'highlighted'


@functools.lru_cache(maxsize=1)
def _pygments():
    """(highlight, get_lexer_by_name, ClassNotFound, HtmlFormatterのクラス)を返す。Pygmentsが無ければ、None。"""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:
        return None
    return highlight, get_lexer_by_name, ClassNotFound, HtmlFormatter


def available() -> bool:
    return _pygments() is not None


def highlight_html(code: str, lang: str):
    """コードを、色分けのHTML（`<code>`の中身）にして返す。Pygmentsが無い・言語が分からない・言語が空のときは、None（呼び出し側は、素の表示にする）。"""
    pygments = _pygments()
    if pygments is None or not lang or not code:
        return None
    highlight, get_lexer_by_name, class_not_found, formatter_class = pygments
    try:
        lexer = get_lexer_by_name(lang)
    except class_not_found:
        return None
    # nowrap: 外側の<div><pre>は、こちらで作る。classprefixは、既定（クラス名が短い）のまま
    return highlight(code, lexer, formatter_class(nowrap=True))


def _scoped(css: str) -> list:
    """スタイルのCSSから、トークンの色の規則だけを残す（行番号・`pre`の規則・全体の背景は、不要。背景は、ページ側の配色で決める）。"""
    # 行末の`/* Comment */`のような注釈は、CSSの大きさを増やすだけのため、外す
    lines = [line for line in css.splitlines() if f'code.{CODE_CLASS} .' in line and 'linenos' not in line]
    return [line.split(' /*')[0] for line in lines]


@functools.lru_cache(maxsize=1)
def css() -> str:
    """トークンの色のCSS（ライト、ダークは`prefers-color-scheme`）。Pygmentsが無ければ、空文字列。"""
    pygments = _pygments()
    if pygments is None:
        return ''
    formatter_class = pygments[3]
    selector = f'code.{CODE_CLASS}'
    light = _scoped(formatter_class(style=_LIGHT_STYLE).get_style_defs(selector))
    dark = _scoped(formatter_class(style=_DARK_STYLE).get_style_defs(selector))
    lines = ['/* シンタックスハイライト（#218。Pygments） */', *light,
             '@media (prefers-color-scheme: dark) {', *[f'  {line}' for line in dark], '}']
    return '\n'.join(lines) + '\n'
