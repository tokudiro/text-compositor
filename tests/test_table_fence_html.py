"""`table`フェンス（#554 段階3）のHTML出力のテスト。"""
from tests.test_html_output import convert


def table_html(tmp_path, body, attrs="", before=""):
    result, html = convert(tmp_path, f"{before}```table {attrs}\n{body}```\n")
    assert result.ok
    return result, html


class TestHtmlTable:
    def test_default_header_row(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\n1,2\n")
        assert "<thead>" in html and '<th scope="col">a</th>' in html
        assert "<td>1</td>" in html and "<td>2</td>" in html

    def test_data_line_on_table(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\n1,2\n", before="# T\n\n")
        assert '<table data-line="3">' in html

    def test_inline_markup_and_br(self, tmp_path):
        _, html = table_html(tmp_path, 'a,b\n**x**,`c`\n"l1\nl2",z\n')
        assert "<strong>x</strong>" in html and "<code>c</code>" in html
        assert "l1<br" in html

    def test_header_cols_are_row_headers(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\n1,2\n", "{header_cols=1}")
        assert '<th scope="row">1</th>' in html and "<td>2</td>" in html

    def test_no_header(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\n1,2\n", "{header_rows=0}")
        assert "<thead>" not in html and "<th" not in html and "<td>a</td>" in html

    def test_header_only(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\n")
        assert "<thead>" in html and "<tbody>" not in html

    def test_two_header_rows(self, tmp_path):
        _, html = table_html(tmp_path, "a,b\nc,d\n1,2\n", "{header_rows=2}")
        head = html[html.index("<thead>"):html.index("</thead>")]
        assert "c</th>" in head and "1" not in head.replace("scope", "")

    def test_tab_delimiter(self, tmp_path):
        _, html = table_html(tmp_path, "a\tb\n1,000\t2\n", "{delimiter=tab}")
        assert "<td>1,000</td>" in html


class TestHtmlErrors:
    def test_column_mismatch_warns_with_line_and_shows_code(self, tmp_path):
        result, html = convert(tmp_path, "# T\n\n```table\na,b\n1\n```\n")
        assert result.ok
        warn = [d for d in result.diagnostics if d.severity == "warning"]
        assert warn and warn[0].line == 5   # 不足している行（`1`）の行
        assert "<table" not in html and "a,b" in html

    def test_unknown_option_warns(self, tmp_path):
        result, html = convert(tmp_path, "```table {header-rows=1}\na\n```\n")
        assert any("unknown option" in d.message for d in result.diagnostics)
