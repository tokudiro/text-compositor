"""`table`フェンスの解析（#554 段階1）のテスト。"""
import pytest

from text_compositor import table_fence
from text_compositor.table_fence import TableFenceError, parse_table_attrs, parse_table_fence


class TestParse:
    def test_defaults(self):
        spec = parse_table_fence("a,b\n1,2\n")
        assert spec.rows == [["a", "b"], ["1", "2"]]
        assert (spec.cols, spec.header_rows, spec.header_cols) == (2, 1, 0)

    def test_quoted_comma_newline_and_quote(self):
        spec = parse_table_fence('a,b\n"1,000","x\ny"\n"say ""hi""",z\n')
        assert spec.rows[1] == ["1,000", "x\ny"]
        assert spec.rows[2][0] == 'say "hi"'

    def test_blank_lines_skipped(self):
        spec = parse_table_fence("a,b\n\n1,2\n\n")
        assert len(spec.rows) == 2

    def test_tab_delimiter_keeps_commas(self):
        spec = parse_table_fence("a\tb\n1,000\t2\n", "{delimiter=tab}")
        assert spec.rows[1] == ["1,000", "2"]

    def test_header_options(self):
        spec = parse_table_fence("a,b\n1,2\n", "{header_rows=0 header_cols=2}")
        assert (spec.header_rows, spec.header_cols) == (0, 2)

    def test_first_line_triple_dash_is_data(self):
        assert parse_table_fence("---,x\n1,2\n").rows[0] == ["---", "x"]


class TestErrors:
    def test_column_mismatch_reports_line(self):
        with pytest.raises(TableFenceError) as e:
            parse_table_fence("a,b\n1,2\n3\n")
        assert e.value.line == 3

    def test_column_mismatch_line_after_multiline_cell(self):
        with pytest.raises(TableFenceError) as e:
            parse_table_fence('a,b\n"x\ny",2\n3\n')
        assert e.value.line == 4

    def test_empty(self):
        with pytest.raises(TableFenceError):
            parse_table_fence("\n\n")

    def test_unknown_option(self):
        with pytest.raises(TableFenceError, match="header-rows|rows"):
            parse_table_fence("a\n", "{header-rows=1}")

    @pytest.mark.parametrize("attrs", ["{header_rows=abc}", "{header_cols=-1}", "{delimiter=semicolon}",
                                       "{header_rows=3}", "{header_cols=3}"])
    def test_invalid_values(self, attrs):
        with pytest.raises(TableFenceError):
            parse_table_fence("a,b\n1,2\n", attrs)


class TestQuotedValues:
    """属性の値は、`"…"`・`'…'`で囲むと、空白を含められる（#569）。"""

    @pytest.fixture(autouse=True)
    def future_options(self, monkeypatch):
        # 空白を含む値が要る設定（列の幅など）は、まだ無い。足されたあとの状態を、テストの中だけで再現する
        monkeypatch.setattr(table_fence, '_KNOWN_ATTRS', (*table_fence._KNOWN_ATTRS, 'col_widths', 'note'))

    def test_double_quotes_keep_spaces(self):
        assert parse_table_attrs('{header_rows=2 col_widths="20% 30% 50%"}') == {'header_rows': '2', 'col_widths': '20% 30% 50%'}

    def test_single_quotes_keep_spaces(self):
        assert parse_table_attrs("{note='a b c' header_cols=1}") == {'note': 'a b c', 'header_cols': '1'}

    def test_unquoted_values_are_read_as_before(self):
        assert parse_table_attrs("{header_cols=1 delimiter=tab}") == {'header_cols': '1', 'delimiter': 'tab'}

    def test_empty_quoted_value(self):
        assert parse_table_attrs('{note=""}') == {'note': ''}

    def test_a_known_option_may_be_quoted(self):
        assert parse_table_fence("a\tb\n1\t2\n", '{delimiter="tab"}').cols == 2

    @pytest.mark.parametrize("attrs", ['{x="a b}', "{x='a b}", '{x=a"b}', '{x="a{b}"}'])
    def test_an_unclosed_or_invalid_quote_is_an_error(self, attrs):
        with pytest.raises(TableFenceError, match="quote"):
            parse_table_attrs(attrs)

    def test_a_quoted_value_does_not_hide_an_unknown_option(self):
        with pytest.raises(TableFenceError, match="unknown option 'caption'"):
            parse_table_fence("a\n", '{caption="a long title"}')
