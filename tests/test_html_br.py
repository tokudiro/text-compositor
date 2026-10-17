"""`<br>`を改行として扱う（#489）のテスト。PDF（Typst）とHTML出力の両方。"""
import re

import pytest
import yaml

from text_compositor import diagnostics
from text_compositor.api import render_html
from text_compositor.chapters import _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer

PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}
FORMS = ["<br>", "<br/>", "<br />", "<BR>", "<Br/>", "<br  />"]


def _typst(markdown):
    renderer = TypstRenderer(line_mapping="off")
    with diagnostics.collect() as collected:
        out = renderer.render(markdown, filepath="doc.md")
    return out, [w.message for w in collected.warnings if "HTML" in w.message]


def _html(tmp_path, markdown):
    md = tmp_path / "doc.md"
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), plugins=PLAIN)
    assert result.ok
    with open(result.html_path, encoding="utf-8") as f:
        text = f.read()
    return text.split("<main>", 1)[1].split("</main>", 1)[0], [d.message for d in result.warnings if "HTML" in d.message]


class TestPdf:
    @pytest.mark.parametrize("form", FORMS)
    def test_a_br_in_a_paragraph_is_a_line_break_without_a_warning(self, form):
        out, warnings = _typst(f"one{form}two\n")
        assert "one#linebreak()\ntwo" in out
        assert warnings == []

    @pytest.mark.parametrize("form", FORMS)
    def test_a_br_in_a_table_cell_breaks_the_line_and_keeps_the_table(self, form):
        out, warnings = _typst(f"| a | b |\n| - | - |\n| x{form}y | z |\n")
        assert "[x#linebreak()\ny]" in out and "[z]" in out
        assert warnings == []

    def test_text_after_a_br_is_escaped_as_the_start_of_a_line(self):
        # 行頭の`-`・`#`・`=`は、Typstの記法になるため、改行の後でもエスケープする
        out, _ = _typst("one<br>- two\n")
        assert "#linebreak()\n\\- two" in out

    def test_a_br_alone_on_a_line_is_a_blank_line_without_a_warning(self):
        out, warnings = _typst("a\n\n<br>\n\nb\n")
        assert "#linebreak()" in out
        assert warnings == []

    def test_a_br_in_a_code_span_and_a_fence_stays_as_text(self):
        out, warnings = _typst("`<br>` と\n\n```html\na<br>b\n```\n")
        assert "#linebreak()" not in out
        assert "<br>" in out
        assert warnings == []

    @pytest.mark.parametrize("tag", ['<br class="a">', '<br id=x/>', "<div>", "<b>", "</p>"])
    def test_other_tags_still_warn_and_are_ignored(self, tag):
        out, warnings = _typst(f"x{tag}y\n")
        assert "#linebreak()" not in out
        assert len(warnings) == 1 and "HTML tag detected" in warnings[0]

    def test_two_brs_make_two_breaks(self):
        out, _ = _typst("a<br><br>b\n")
        assert out.count("#linebreak()") == 2

    def test_a_br_in_a_list_item_and_a_heading(self):
        out, warnings = _typst("- one<br>two\n\n# H<br>x\n")
        assert out.count("#linebreak()") == 2
        assert warnings == []


class TestHtmlOutput:
    @pytest.mark.parametrize("form", FORMS)
    def test_a_br_in_a_paragraph_becomes_br(self, tmp_path, form):
        body, warnings = _html(tmp_path, f"one{form}two\n")
        assert re.search(r"<p[^>]*>one<br />two</p>", body)
        assert warnings == []

    def test_a_br_in_a_table_cell_becomes_br(self, tmp_path):
        body, warnings = _html(tmp_path, "| a | b |\n| - | - |\n| x<br>y | z |\n")
        assert "<td>x<br />y</td>" in body or re.search(r"<td[^>]*>x<br />y</td>", body)
        assert warnings == []

    def test_a_br_alone_on_a_line_becomes_br(self, tmp_path):
        body, warnings = _html(tmp_path, "a\n\n<br>\n\nb\n")
        assert "<br />" in body
        assert warnings == []

    def test_a_br_in_code_is_escaped_text(self, tmp_path):
        body, warnings = _html(tmp_path, "`<br>`\n")
        assert "&lt;br&gt;" in body and "<br />" not in body
        assert warnings == []

    def test_other_tags_still_warn(self, tmp_path):
        body, warnings = _html(tmp_path, 'x<br class="a">y\n')
        assert "<br" not in body and "xy" in body   # 改行にならず、タグも出ない（無視される）
        assert len(warnings) == 1


class TestAggregateCell:
    def test_a_br_in_a_markdown_cell_of_an_aggregate_table(self, tmp_path):
        agg = tmp_path / "tc"
        agg.mkdir()
        (agg / "a.yaml").write_text(yaml.safe_dump({"id": "T-1", "expected": "one<br>two"}), encoding="utf-8")
        with diagnostics.collect() as collected:
            code, *_ = _render_aggregate_chapter(
                {"aggregate": "tc", "columns": [{"key": "id"}, {"key": "expected", "markdown": True}]}, "tc", str(tmp_path),
                TypstRenderer(line_mapping="off"),
                current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
                current_header=None, current_footer=None, current_paginate=True,
                global_header=None, global_footer=None, global_paginate=True,
                current_background=None, global_background=None, current_logo=None, global_logo=None)
        assert "one#linebreak()\ntwo" in code
        assert [w for w in collected.warnings if "HTML" in w.message] == []
