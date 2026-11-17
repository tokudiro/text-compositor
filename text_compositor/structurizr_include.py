"""```structurizrフェンスの`!include`を、原稿のあるフォルダ基準で解決する。

structurizr-cliには、フェンスの中身を一時フォルダに書いて渡す。そのままだと、`!include model.dsl`は
一時フォルダの中で探され、見つからない。ここでは、取り込まれるファイルを集め、一時フォルダへ、プロジェクトと
同じフォルダ構造でコピーできるようにする。キャッシュのキーにも、取り込んだファイルの中身を含められるようにする。

取り込めるのは、プロジェクトのルートの中にある`.dsl`ファイルだけ。URL・絶対パス・ルートの外へ出るもの
（`../`・シンボリックリンク）は、失敗クローズにする（複数の書き手が、原稿の外のファイルを図へ取り込めないように。
vega-liteのデータと同じ方針）。
"""
import hashlib
import os
import re
from typing import List

# 行頭の`!include パス`。パスは、引用符で囲んでも、囲まなくてもよい。
_INCLUDE_RE = re.compile(r'^[ \t]*!include[ \t]+(?:"([^"\r\n]+)"|(\S+))', re.MULTILINE)
_MAX_DEPTH = 8


class IncludeError(Exception):
    """`!include`を取り込めない。メッセージは、そのまま利用者に見せる。"""


def _within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(root), os.path.normcase(path)]) == os.path.normcase(root)
    except ValueError:   # 別のドライブ
        return False


def include_root(origin_dir: str, base_dir: str) -> str:
    """取り込みを許す範囲（ルート）を返す。原稿がプロジェクトのルートの中にあれば、ルート。
    外にあるとき（`chapters`で外のファイルを指した場合など）は、その原稿のフォルダだけを範囲にする。"""
    base = os.path.realpath(base_dir)
    return base if _within(base, os.path.realpath(origin_dir)) else os.path.realpath(origin_dir)


def find_includes(code: str) -> List[str]:
    """DSLの中の`!include`のパスを、書かれた順に返す。"""
    return [m.group(1) or m.group(2) for m in _INCLUDE_RE.finditer(code)]


def collect_includes(code: str, origin_dir: str, root: str) -> List[str]:
    """`code`が（入れ子も含めて）取り込む`.dsl`ファイルの実パスを、重複なしで返す。

    origin_dir: `code`を書いたMarkdownのあるフォルダ。root: プロジェクトのルート。
    取り込めないものがあれば、IncludeErrorにする。"""
    root = os.path.realpath(root)
    found: List[str] = []
    seen = set()

    def visit(text: str, base: str, depth: int) -> None:
        for raw in find_includes(text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]+:', raw) or raw.startswith('//'):
                raise IncludeError(f"External URLs are not supported in !include: '{raw}'. Use a .dsl file inside the project.")
            if os.path.isabs(raw) or raw.startswith(('/', '\\')) or re.match(r'^[a-zA-Z]:', raw):
                raise IncludeError(f"Absolute paths are not allowed in !include: '{raw}'. Use a path relative to the manuscript.")
            if not raw.lower().endswith('.dsl'):
                raise IncludeError(f"Only .dsl files can be included: '{raw}'. Directories and other file types are not supported.")
            path = os.path.realpath(os.path.join(base, raw))
            if not _within(root, path):
                raise IncludeError(f"!include '{raw}' points outside the project. Only files inside the project can be included.")
            if not os.path.isfile(path):
                raise IncludeError(f"!include '{raw}' was not found (looked for {path}).")
            if path in seen:
                continue
            if depth >= _MAX_DEPTH:
                raise IncludeError(f"!include is nested more than {_MAX_DEPTH} levels deep at '{raw}'.")
            seen.add(path)
            found.append(path)
            with open(path, 'r', encoding='utf-8') as f:
                visit(f.read(), os.path.dirname(path), depth + 1)

    visit(code, os.path.realpath(origin_dir), 0)
    return found


def cache_suffix(files: List[str], root: str) -> str:
    """取り込んだファイルの、パスと中身から、キャッシュのキーに足す文字列を作る。なければ空。
    取り込んだファイルを直したときに、図を描き直すためのもの。"""
    if not files:
        return ''
    root = os.path.realpath(root)
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(os.path.relpath(path, root).replace(os.sep, '/').encode('utf-8'))
        h.update(b'\0')
        with open(path, 'rb') as f:
            h.update(f.read())
        h.update(b'\0')
    return '\n// includes:' + h.hexdigest() + '\n'


def stage(files: List[str], origin_dir: str, root: str, tmp_dir: str) -> str:
    """取り込むファイルを、tmp_dirへ、プロジェクトと同じフォルダ構造でコピーする。
    ワークスペースを置くフォルダ（原稿のフォルダに当たる、tmp_dirの中のフォルダ）を返す。
    originがrootの外にあるときは、tmp_dirの外へ書いてしまうため、エラーにする（呼び出し側が、include_root()でrootを決める）。"""
    import shutil
    root = os.path.realpath(root)
    if not _within(root, os.path.realpath(origin_dir)):
        raise IncludeError("The manuscript folder is outside the include root.")
    for path in files:
        dest = os.path.join(tmp_dir, os.path.relpath(path, root))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest)
    ws_dir = os.path.join(tmp_dir, os.path.relpath(os.path.realpath(origin_dir), root))
    os.makedirs(ws_dir, exist_ok=True)
    return ws_dir
