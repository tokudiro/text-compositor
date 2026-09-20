"""効かずに、文字として残った太字（`**`）の警告（emphasis_lint.py、#215）のテスト。"""
import os

import pytest

from text_compositor import diagnostics
from text_compositor.api import render_html
from text_compositor.emphasis_lint import find_unapplied_bold
from text_compositor.renderer import TypstRenderer

PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}


def _inline(text):
    md = TypstRenderer(line_mapping="off").md
    return [t for t in md.parse(text) if t.type == "inline"][0]


def _inline_children(text):
    return _inline(text).children


def _find(text):
    inline = _inline(text)
    return find_unapplied_bold(inline.children, inline.content)


class TestFindUnappliedBold:
    @pytest.mark.parametrize("text, snippet", [
        ("これは**「重要」**です。", "**「重要」**"),
        ("結果は**100%**です", "**100%**"),
        ("**注意：**この点に注意", "**注意：**"),
        ("値は**（仮）**とする", "**（仮）**"),
    ])
    def test_finds_bold_that_commonmark_did_not_apply(self, text, snippet):
        assert _find(text)[0] == (0, snippet)

    @pytest.mark.parametrize("text", [
        "これは**重要**です。",          # 日本語の文字に挟まれても、効く
        "これは **重要** です。",
        "「**重要**」です",
        "**注意:** この点",
        "`**code**`",                    # コードスパン
        r"\*\*not bold\*\*",             # エスケープ
        "a ** b ** c",                   # 空白で挟まれた`**`は、太字のつもりではない
        "def f(*args, **kwargs)",        # `**`が1つだけ
        "2**3 and 4**5",                 # 数字の間は、太字として効く
        "__太字__です",                   # `__`は、対象外
        "**a**b**c**",
        "普通の文章です。",
    ])
    def test_does_not_flag_what_is_fine(self, text):
        assert _find(text) == []

    def test_reports_the_line_offset_inside_a_multi_line_paragraph(self):
        found = _find("1行目です。\n2行目は**「重要」**です。\n3行目。")
        assert found == [(1, "**「重要」**")]

    def test_bold_around_a_code_span_is_found_with_a_placeholder(self):
        assert _find("式は**`x`**です") == [(0, "**…**")]

    def test_a_long_match_is_shortened(self):
        found = _find("あ**「" + "長" * 80 + "」**い")
        assert len(found[0][1]) == 40 and found[0][1].endswith("…")

    def test_no_children_is_fine(self):
        assert find_unapplied_bold(None) == []


def _html_warnings(tmp_path, text):
    md = tmp_path / "doc.md"
    md.write_text(text, encoding="utf-8")
    result = render_html(str(md), plugins=PLAIN)
    return result, [w for w in result.warnings if "Bold markup" in w.message]


class TestHtmlOutput:
    def test_a_failed_bold_is_a_warning_with_the_manuscript_line(self, tmp_path):
        result, warnings = _html_warnings(tmp_path, "# 見出し\n\n本文です。\n\nこれは**「重要」**です。\n")
        assert result.ok
        assert len(warnings) == 1 and warnings[0].line == 5
        assert "**「重要」**" in warnings[0].message and "space" in warnings[0].message

    def test_the_line_counts_the_lines_inside_a_paragraph_and_after_a_layout_block(self, tmp_path):
        text = "a\n\n::: layout-right\n```mermaid\ngraph TD\n A-->B\n```\n本文\n:::\n\n1行目\n2行目は**「重要」**です\n"
        _, warnings = _html_warnings(tmp_path, text)
        assert [w.line for w in warnings] == [12]

    def test_a_working_bold_and_code_are_not_flagged(self, tmp_path):
        _, warnings = _html_warnings(tmp_path, "これは**重要**です。\n\n`**code**`\n\n```\n**fence**\n```\n")
        assert warnings == []

    def test_the_text_is_still_shown(self, tmp_path):
        result, _ = _html_warnings(tmp_path, "これは**「重要」**です。\n")
        with open(result.html_path, encoding="utf-8") as f:
            assert "<p>これは**「重要」**です。</p>" in f.read()

    def test_a_table_cell_and_a_list_item_are_checked(self, tmp_path):
        text = "| a | b |\n| - | - |\n| **「x」**です | y |\n\n- 項目**（仮）**です\n"
        _, warnings = _html_warnings(tmp_path, text)
        assert [w.line for w in warnings] == [3, 5]


class TestPdfPath:
    def test_the_pdf_renderer_warns_with_the_line(self, tmp_path):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as collected:
            renderer.render("# 見出し\n\n本文\n\nこれは**「重要」**です。\n", filepath=str(tmp_path / "doc.md"))
        warnings = [w for w in collected.warnings if "Bold markup" in w.message]
        assert len(warnings) == 1 and warnings[0].line == 5
        assert os.path.basename(warnings[0].file) == "doc.md"
