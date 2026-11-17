"""```plantumlフェンスの`!include`を、原稿のあるフォルダ基準で解決する（#622）。

plantuml.jarは、セキュリティの設定（ALLOWLIST）で動かすため、ファイルとURLの取り込みは、許可した場所以外では
拒否される。許可する場所は、図が書かれた原稿のフォルダだけにする（`PLANTUML_INCLUDE_PATH`で渡す）。
このモジュールは、その手前で、次の2つを受け持つ。

- 図のコードの`!include`を拾い、取り込まれるファイルを集める。キャッシュのキーに、取り込んだファイルの中身を
  含めて、そのファイルを直したときに、図を描き直せるようにする。HTML出力では、変更の検知にも加える。
- 取り込めないもの（URL・絶対パス・原稿のフォルダの外へ出るもの・見つからないもの）を、PlantUMLの
  分かりにくいエラー画像になる前に、理由つきのエラーにする。

取り込めるのは、原稿のフォルダの中にあるファイルだけ（`../`で外へ出る書き方・シンボリックリンクは拒否）。
標準ライブラリ（`!include <C4/C4_Container>`のように、山括弧で囲むもの）は、対象外で、そのまま使える。
Structurizrの`!include`（#618）は、プロジェクトのルートの中なら`../`も許すが、PlantUMLは、より厳しく、
原稿のフォルダの中だけにする（`include.path`は、複数のフォルダを並べると、同名のファイルを取り違えるため）。
"""
import hashlib
import os
import re
from typing import List

# 行頭の`!include`・`!include_once`・`!include_many`・`!includesub`と、そのパス。
# パスは、引用符で囲んでも、囲まなくてもよい。パスの後ろの`!1`・`!SUB`（番号・部分の指定）は、取り除く。
_INCLUDE_RE = re.compile(
    r'^[ \t]*!(?:include|include_once|include_many|includesub)[ \t]+(?:"([^"\r\n]+)"|(\S+))',
    re.MULTILINE)
_MAX_DEPTH = 8


class IncludeError(Exception):
    """`!include`を取り込めない。メッセージは、そのまま利用者に見せる。"""


def _within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(root), os.path.normcase(path)]) == os.path.normcase(root)
    except ValueError:   # 別のドライブ
        return False


def find_includes(code: str) -> List[str]:
    """図のコードの中の、ファイルの`!include`のパスを、書かれた順に返す。
    標準ライブラリ（`<...>`）と、変数・関数を含むパス（`%`・`$`）は、含めない。"""
    paths = []
    for m in _INCLUDE_RE.finditer(code):
        raw = m.group(1) or m.group(2)
        if raw.startswith('<') or '%' in raw or '$' in raw:
            continue
        path = raw.split('!', 1)[0]   # `file.iuml!1`・`file.iuml!SUB`
        if path:
            paths.append(path)
    return paths


def collect_includes(code: str, origin_dir: str) -> List[str]:
    """`code`が（入れ子も含めて）取り込むファイルの実パスを、重複なしで返す。

    origin_dir: `code`を書いたMarkdownのあるフォルダ（取り込みを許す範囲）。
    入れ子の`!include`は、取り込んだファイルのあるフォルダを先に探し、なければ、origin_dirを探す
    （実機で確認したPlantUMLの挙動に合わせる）。取り込めないものがあれば、IncludeErrorにする。"""
    root = os.path.realpath(origin_dir)
    found: List[str] = []
    seen = set()

    def resolve(raw: str, base: str) -> str:
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]+:', raw) and not re.match(r'^[a-zA-Z]:[\\/]', raw):
            raise IncludeError(f"External URLs are not supported in !include: '{raw}'. Use a file inside the manuscript folder.")
        if os.path.isabs(raw) or raw.startswith(('/', '\\')) or re.match(r'^[a-zA-Z]:', raw):
            raise IncludeError(f"Absolute paths are not allowed in !include: '{raw}'. Use a path relative to the manuscript.")
        candidates = [base] if base == root else [base, root]
        for folder in candidates:
            path = os.path.realpath(os.path.join(folder, raw))
            if not _within(root, path):
                raise IncludeError(f"!include '{raw}' points outside the manuscript folder. "
                                   "Only files inside the manuscript folder can be included.")
            if os.path.isfile(path):
                return path
        raise IncludeError(f"!include '{raw}' was not found (looked for {os.path.join(root, raw)}).")

    def visit(text: str, base: str, depth: int) -> None:
        for raw in find_includes(text):
            path = resolve(raw, base)
            if path in seen:
                continue
            if depth >= _MAX_DEPTH:
                raise IncludeError(f"!include is nested more than {_MAX_DEPTH} levels deep at '{raw}'.")
            seen.add(path)
            found.append(path)
            with open(path, 'r', encoding='utf-8') as f:
                visit(f.read(), os.path.dirname(path), depth + 1)

    visit(code, root, 0)
    return found


def cache_suffix(files: List[str], origin_dir: str) -> str:
    """取り込んだファイルの、パスと中身から、キャッシュのキーに足す文字列を作る。なければ空。
    取り込んだファイルを直したときに、図を描き直すためのもの。パスは、原稿のフォルダからの相対にして、
    フォルダごと別の場所へ動かしても、同じキーになるようにする。"""
    if not files:
        return ''
    root = os.path.realpath(origin_dir)
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(os.path.relpath(path, root).replace(os.sep, '/').encode('utf-8'))
        h.update(b'\0')
        with open(path, 'rb') as f:
            h.update(f.read())
        h.update(b'\0')
    return ':inc=' + h.hexdigest()[:16]
