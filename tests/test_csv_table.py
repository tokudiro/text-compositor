"""CSVファイルをTypstテーブルへ変換する機能（#36）のリグレッションテスト。"""
import os

import pytest

import text_compositor.build as build
import text_compositor.project as project_mod
from text_compositor.project import _build_one
from text_compositor.renderer import TypstRenderer


def render_csv(csv_text, filepath="data.csv", table_header_style=None):
    renderer = TypstRenderer(line_mapping="off")
    if table_header_style is not None:
        renderer.table_header_style = table_header_style
    return renderer.render_chapter(csv_text, filepath=filepath)


class TestBasicConversion:
    def test_header_and_rows(self):
        out = render_csv("name,age\nAlice,30\nBob,25\n")
        assert out == (
            "#table(\n"
            "  columns: 2,\n"
            "  table.header(\n"
            "  [name], [age], \n"
            "  ),\n"
            "  [Alice], [30], \n"
            "  [Bob], [25], \n"
            "  \n"
            ")\n\n"
        )

    def test_header_only_no_data_rows(self):
        out = render_csv("a,b\n")
        assert out == "#table(\n  columns: 2,\n  table.header(\n  [a], [b], \n  ),\n  \n)\n\n"


class TestRfc4180Quoting:
    def test_quoted_comma_in_cell(self):
        out = render_csv('a,b\n"1, 2",3\n')
        assert "[1, 2]" in out

    def test_quoted_newline_in_cell(self):
        out = render_csv('a\n"line1\nline2"\n')
        assert "[line1\nline2]" in out

    def test_escaped_quote_char(self):
        out = render_csv('a\n"she said ""hi"""\n')
        assert '[she said "hi"]' in out


class TestEscaping:
    def test_typst_special_characters_are_escaped(self):
        out = render_csv("a\n#tag $x@y\n")
        assert "[\\#tag \\$x\\@y]" in out

    def test_leading_block_marker_is_escaped(self):
        out = render_csv("a\n= heading like\n- list like\n")
        assert "[\\= heading like]" in out
        assert "[\\- list like]" in out

    def test_content_is_not_parsed_as_markdown(self):
        out = render_csv("a\n**not bold**\n")
        assert "[\\*\\*not bold\\*\\*]" in out


class TestFailFast:
    def test_empty_file_exits(self):
        with pytest.raises(SystemExit):
            render_csv("")

    def test_uneven_row_exits(self):
        with pytest.raises(SystemExit):
            render_csv("a,b\n1,2\n3\n")


class TestHeaderStyle:
    def test_table_header_style_applies(self):
        out = render_csv("a,b\n1,2\n", table_header_style={"bold": True, "background": "red"})
        assert "fill: (col, row) => if row == 0 { red } else { none }" in out
        assert "[#strong[a]]" in out
        assert "[1], [2]" in out


class TestHeaderOption:
    """1行目を、ヘッダー行にするか（csv_header、#220）。"""

    def test_without_a_header_every_row_is_data_and_no_table_header_is_made(self):
        renderer = TypstRenderer(line_mapping="off", csv_header=False)
        out = renderer.render_chapter("Alice,30\nBob,25\n", filepath="data.csv")
        assert out == "#table(\n  columns: 2,\n  [Alice], [30], \n  [Bob], [25], \n  \n)\n\n"
        assert "table.header" not in out

    def test_the_header_row_style_is_not_applied_without_a_header(self):
        renderer = TypstRenderer(line_mapping="off", csv_header=False)
        renderer.table_header_style = {"bold": True, "background": "#eee"}
        out = renderer.render_chapter("a,b\n", filepath="data.csv")
        assert "fill" not in out and "*" not in out and out == "#table(\n  columns: 2,\n  [a], [b], \n  \n)\n\n"

    def test_the_first_row_decides_the_column_count_without_a_header(self):
        renderer = TypstRenderer(line_mapping="off", csv_header=False)
        with pytest.raises(SystemExit):
            renderer.render_chapter("a,b\n1,2,3\n", filepath="data.csv")

    def test_the_default_is_a_header_row(self):
        assert TypstRenderer(line_mapping="off").csv_header is True


HEAD = "document:\n  cover: none\ninputs:\n  dir: \".\"\n"


@pytest.fixture
def csv_project(tmp_path, monkeypatch):
    """_build_oneを通して、生成されるTypstコードを取得する（コンパイルは、差し替える）。"""
    (tmp_path / "data.csv").write_text("name,qty\nAlice,3\n", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(project_mod, "_compile_and_cleanup", lambda typst_code, *a, **k: captured.setdefault("code", typst_code))

    def run(config_text):
        cfg = tmp_path / "text-compositor.config.yaml"
        cfg.write_text(config_text, encoding="utf-8")
        captured.clear()
        _build_one(os.path.dirname(os.path.abspath(build.__file__)), str(tmp_path), "fonts", str(cfg))
        return captured["code"]

    return run


class TestHeaderOptionInConfig:
    def test_default_keeps_the_header_row(self, csv_project):
        assert "table.header(" in csv_project(HEAD + "chapters:\n  - data.csv\n")

    def test_document_csv_header_false_applies_to_every_csv_chapter(self, csv_project):
        code = csv_project("document:\n  cover: none\n  csv_header: false\ninputs:\n  dir: \".\"\nchapters:\n  - data.csv\n")
        assert "table.header(" not in code and "[name], [qty]" in code

    def test_a_chapter_overrides_the_document_default(self, csv_project):
        code = csv_project("document:\n  cover: none\n  csv_header: false\ninputs:\n  dir: \".\"\n"
                           "chapters:\n  - file: data.csv\n    csv_header: true\n")
        assert "table.header(" in code
        code = csv_project(HEAD + "chapters:\n  - file: data.csv\n    csv_header: false\n")
        assert "table.header(" not in code

    def test_a_value_that_is_not_true_or_false_is_an_error(self, csv_project):
        with pytest.raises(SystemExit):
            csv_project("document:\n  cover: none\n  csv_header: \"no\"\ninputs:\n  dir: \".\"\nchapters:\n  - data.csv\n")
        with pytest.raises(SystemExit):
            csv_project(HEAD + "chapters:\n  - file: data.csv\n    csv_header: 0\n")