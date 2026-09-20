"""太字（`**...**`）が、効かずに、そのまま文字として残った箇所を、見つける（#215）。

AIが書いたMarkdownでは、`これは**「重要」**です。`のように、`**`の前後に空白がなく、しかも`**`の内側の端が、
句読点・括弧である書き方が多い。CommonMarkの規則では、この`**`は、太字の開始・終了になれず、`**`が、そのまま
本文に出る（エラーにも警告にもならない）。パーサーの結果を調べれば、確実に検出できる: 太字が効いていれば、`**`は、
`strong_open`・`strong_close`のトークンになり、`text`のトークンには、残らない。

検出の対象は、`**`だけである。`__`は、識別子（`some__name__x`）に現れやすく、誤検出が多いため、対象にしない。
コードスパン・エスケープ（`\\*\\*`）・リンクなど、`text`以外のトークンの中は、見ない。"""
import re
from typing import List, Tuple

# 内側の端が空白でない`**`の対。開きの直後・閉じの直前が空白のもの（`a ** b ** c`）は、太字のつもりではないため、対象外。
# `\0`は、`text`以外のトークン（コードスパンなど）の位置を表す（`\S`に含まれる）。
_UNAPPLIED_BOLD_RE = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*')

_SNIPPET_MAX = 40


def find_unapplied_bold(children, raw=None) -> List[Tuple[int, str]]:
    """インライントークンの子（`inline`トークンの`children`）から、効かなかった太字を、(段落の先頭からの行のずれ, 該当の文字列) の列で返す。
    行のずれは、0始まり（段落の1行目なら0。改行を含む段落で、2行目なら1）。
    raw: そのインライントークンの、原稿の文字列（`inline`トークンの`content`）。あれば、エスケープ（`\\*\\*`）・文字参照
    （`&ast;`）で書いた`**`を、除く。markdown-itは、これらを、ただの`text`にするため、トークンだけでは、区別できない。"""
    parts = []
    for child in children or []:
        if child.type == 'text':
            parts.append(child.content)
        elif child.type in ('softbreak', 'hardbreak'):
            parts.append('\n')
        else:
            parts.append('\0')
    joined = ''.join(parts)
    if '**' not in joined:
        return []
    found = []
    for m in _UNAPPLIED_BOLD_RE.finditer(joined):
        if raw is not None and not all(segment in raw for segment in m.group(0).split('\0')):
            continue   # 原稿に、そのままの形で、書かれていない（エスケープ・文字参照）
        snippet = m.group(0).replace('\0', '…')
        if len(snippet) > _SNIPPET_MAX:
            snippet = snippet[:_SNIPPET_MAX - 1] + '…'
        found.append((joined.count('\n', 0, m.start()), snippet))
    return found


def unapplied_bold_message(snippet: str) -> str:
    """警告の文言。原因（CommonMarkの規則）と、直し方を示す。"""
    return (f"Bold markup {snippet!r} was not applied and is shown as plain text: CommonMark cannot start or end bold "
            f"next to punctuation (e.g. a bracket) without a space outside the markers. "
            f"Put a space before the opening ** and after the closing **.")
