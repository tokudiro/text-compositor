"""CSVファイルをTypstテーブルへ変換する機能（#36）のリグレッションテスト。"""
import pytest

import text_compositor.build as build


def render_csv(csv_text, filepath="data.csv", table_header_style=None):
    renderer = build.TypstRenderer(line_mapping="off")
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
