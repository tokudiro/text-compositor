"""HTML出力の`<html lang>`（#340）のテスト。スクリーンリーダーが、読み上げの言語を決めるのに使う。"""
import re

import pytest

from text_compositor.api import render_html

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


def html_tag(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    result = render_html(str(path), plugins=PLAIN)
    assert result.ok, result.diagnostics
    html = open(result.html_path, encoding="utf-8").read()
    return re.search(r"<html[^>]*>", html).group(0)


@pytest.mark.parametrize("text,lang", [
    ("# 見出し\n\n本文です。\n", "ja"),
    ("# Title\n\nplain english text\n", "en"),
    ("# Mixed\n\nコードは `x = 1` です。\n", "ja"),
    ("# ひらがな\n", "ja"),
    ("# カタカナ\n", "ja"),
])
def test_the_language_is_guessed_from_the_text(tmp_path, text, lang):
    assert html_tag(tmp_path, "doc.md", text) == f'<html lang="{lang}">'


@pytest.mark.parametrize("declared,lang", [("en", "en"), ("fr", "fr"), ("zh-Hans", "zh-Hans"), ("pt-BR", "pt-BR")])
def test_the_front_matter_lang_wins(tmp_path, declared, lang):
    assert html_tag(tmp_path, "doc.md", f"---\nlang: {declared}\n---\n# 見出し\n\n本文\n") == f'<html lang="{lang}">'


@pytest.mark.parametrize("declared", ['"x y"', '"<script>"', "123", '"a"'])
def test_an_invalid_lang_is_ignored_and_never_reaches_the_html(tmp_path, declared):
    tag = html_tag(tmp_path, "doc.md", f"---\nlang: {declared}\n---\n# Title\n\ntext\n")
    assert tag == '<html lang="en">'


def test_a_text_file_gets_a_language_too(tmp_path):
    assert html_tag(tmp_path, "memo.txt", "メモです\n") == '<html lang="ja">'
