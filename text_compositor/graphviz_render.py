"""HTML出力のGraphvizを、Typstのパッケージ`diagraph`で、SVGにする（#264）。

PDFと同じ経路（`diagraph`）のため、Obunzu・PDF・CLI（Python API）で、同じ図になる。Viz.jsは、使わない。
DOTは、Typstのコードに埋め込まず、`sys.inputs`で渡す（エスケープが要らず、原稿のDOTが、Typstのコードとして解釈されない）。
"""
import hashlib
import os
import re
from typing import List, Optional, Tuple

from text_compositor.deps import _user_cache_dir, ensure_fonts
from text_compositor.typst_runtime import typst_lib, typst_package_options

# 使うdiagraphの版。`templates/_common.typ`の`@preview/diagraph:...`・`viewer/scripts/build-dist.js`と、同じ値にする
# （tests/test_graphviz_render.pyが、一致を確かめる）。
DIAGRAPH_VERSION = "0.3.7"

# 図1つ分のTypstコード。余白なし・大きさは、図に合わせる。フォントは、PDFのテンプレートと同じ`Noto Sans JP`。
# 文字の大きさは、PDFの本文（`render-graph`は、本文の大きさで描く）に近い値にした。
_WRAPPER = f'''#import "@preview/diagraph:{DIAGRAPH_VERSION}": render
#set page(width: auto, height: auto, margin: 0pt)
#set text(font: "Noto Sans JP", size: 11pt)
#render(sys.inputs.dot)
'''


class GraphvizRenderError(Exception):
    """図にできなかった。`dot_line`は、DOTの中の行（1始まり）で、分かる場合だけ入る。"""

    def __init__(self, message: str, dot_line: Optional[int] = None):
        super().__init__(message)
        self.dot_line = dot_line


def wrapper_digest(wrapper: str) -> str:
    return hashlib.sha256(wrapper.encode('utf-8')).hexdigest()[:8]


def cache_version() -> str:
    """図のSVGのキャッシュキーに入れる、描画環境の版。diagraph・Typst・上のTypstコードのどれかが変われば、別のキーになる。"""
    return f"diagraph{DIAGRAPH_VERSION}+typst{typst_lib.__version__}+w{wrapper_digest(_WRAPPER)}"


# Compiler（フォントの読み込みを含む準備は、初回だけ約40〜60 ms。以後は、図1つ14〜59 ms）を、使い回す。
# Pikchr（pikchr_render.py）も、この仕組みを共有する（図の種類ごとに、Typstコード（wrapper）が違う）。
_compilers = {}


def wrapper_path(wrapper: str, kind: str) -> str:
    """図のTypstコードのファイル（内容は、常に同じ）。ユーザーのキャッシュに置く（原稿のフォルダには、何も作らない。#258）。"""
    directory = os.path.join(_user_cache_dir(), "graphviz" if kind == "diagraph" else kind)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{kind}-{wrapper_digest(wrapper)}.typ")
    if not os.path.exists(path):
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(wrapper)
        os.replace(tmp, path)   # 別のプロセスが、書きかけを読まないように
    return path


def compiler_for(wrapper: str, kind: str):
    """wrapper（Typstコード）を、`sys.inputs`を受けて図にする、使い回しのCompilerを返す。"""
    font_dir = ensure_fonts()
    path = wrapper_path(wrapper, kind)
    options = typst_package_options()
    key = (path, font_dir, tuple(sorted(options.items())))
    compiler = _compilers.get(key)
    if compiler is None:
        compiler = typst_lib.Compiler(path, root=os.path.dirname(path), font_paths=[font_dir],
                                      ignore_system_fonts=True, **options)
        _compilers[key] = compiler
    return compiler


def _compiler():
    return compiler_for(_WRAPPER, "diagraph")


_DIAGRAPH_ERROR_RE = re.compile(r'Diagraph error:\s*(.+?)\s*$', re.MULTILINE)
_DOT_LINE_RE = re.compile(r'\bin line (\d+)')


def render_svg(code: str) -> str:
    """DOTを、SVGの文字列にする。失敗は、`GraphvizRenderError`（構文エラーは、DOTの行つき）。"""
    try:
        svg = _compiler().compile(format="svg", sys_inputs={"dot": code})
    except typst_lib.TypstError as e:
        text = str(e)
        m = _DIAGRAPH_ERROR_RE.search(text)
        if m:
            line = _DOT_LINE_RE.search(m.group(1))
            raise GraphvizRenderError(m.group(0).strip(), int(line.group(1)) if line else None) from e
        raise GraphvizRenderError(getattr(e, "diagnostic", None) or text) from e
    if isinstance(svg, (list, tuple)):   # 複数ページには、ならない（ページの大きさは、図に合わせる）。念のため
        svg = svg[0]
    return svg.decode('utf-8') if isinstance(svg, (bytes, bytearray)) else str(svg)


# --- diagraphで描けない記法の検出（警告のため）-----------------------------------------------------------
# `shape=record`・`Mrecord`は、仕切りの記号が、そのまま文字で、1つの箱に出る。図全体の`label`は、表示されない。どちらも、
# エラーにならない（黙って、違う見た目になる）ため、DOTを、簡単に字句分解して、検出する。文字列・HTMLラベル・コメントの中は
# 見ない。ノードの`label`・クラスタの`label`は、描かれるため、対象にしない（図の最上位の`label`だけを、対象にする）。

_ID_RE = re.compile(r'[A-Za-z_\u0080-\U0010ffff][\w\u0080-\U0010ffff]*|-?(?:\d+\.?\d*|\.\d+)')


def _tokenize(code: str) -> List[Tuple[str, str, int]]:
    """(種類, 文字列, 行) の列。種類は、`id`・`str`・`html`・`punct`。"""
    tokens = []
    i, n, line = 0, len(code), 1
    while i < n:
        c = code[i]
        if c == '\n':
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif code.startswith('//', i) or (c == '#' and (i == 0 or code[i - 1] == '\n')):
            end = code.find('\n', i)
            i = n if end < 0 else end
        elif code.startswith('/*', i):
            end = code.find('*/', i + 2)
            end = n if end < 0 else end + 2
            line += code.count('\n', i, end)
            i = end
        elif c == '"':
            j = i + 1
            while j < n and code[j] != '"':
                j += 2 if code[j] == '\\' else 1
            tokens.append(('str', code[i + 1:j], line))
            line += code.count('\n', i, j)
            i = j + 1
        elif c == '<':
            depth, j = 0, i
            while j < n:
                if code[j] == '<':
                    depth += 1
                elif code[j] == '>':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            tokens.append(('html', code[i + 1:j], line))
            line += code.count('\n', i, j)
            i = j + 1
        else:
            m = _ID_RE.match(code, i)
            if m and m.end() > i:
                tokens.append(('id', m.group(0), line))
                i = m.end()
            else:
                tokens.append(('punct', c, line))
                i += 1
    return tokens


def find_unsupported(code: str) -> List[Tuple[str, int]]:
    """diagraphで描けない記法を、(種類, DOTの行) の列で返す。種類は、`record`（`shape=record`・`Mrecord`）と、
    `graph-label`（図の最上位の`label`。`graph [label=...]`を含む）。"""
    tokens = _tokenize(code)
    found = []
    depth = 0            # `{`の深さ。図の最上位は、1
    in_attrs = False     # `[...]`の中か
    owner = None         # `[`の直前の識別子（`graph`・`node`・`edge`・ノード名など）
    last = None
    for i, (kind, text, line) in enumerate(tokens):
        if kind == 'punct':
            if text == '{':
                depth += 1
                last = None
            elif text == '}':
                depth -= 1
                last = None
            elif text == '[':
                in_attrs, owner = True, last
            elif text == ']':
                in_attrs, last = False, None
            elif text == ';' and not in_attrs:
                last = None
            continue
        if kind == 'id' and not in_attrs:
            last = text.lower()
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if kind in ('id', 'str') and nxt and nxt[0] == 'punct' and nxt[1] == '=':
            key = text.lower()
            value = tokens[i + 2] if i + 2 < len(tokens) else None
            if in_attrs and key == 'shape' and value and value[0] in ('id', 'str') and value[1].lower() in ('record', 'mrecord'):
                found.append(('record', value[2]))
            elif key == 'label' and depth == 1 and ((in_attrs and owner == 'graph') or (not in_attrs)):
                found.append(('graph-label', line))
    return found
