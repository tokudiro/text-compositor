"""`table`フェンス（#554 段階2）のTypst出力のテスト。"""
import pytest

from text_compositor.renderer import TypstRenderer


def render(md, **style):
    renderer = TypstRenderer(line_mapping="off")
    if style:
        renderer.table_header_style = style
    return renderer.render_chapter(md, filepath="doc.md")


def fence(body, attrs=""):
    return f"```table {attrs}\n{body}```\n"


class TestBasic:
    def test_default_header_row(self):
        out = render(fence("a,b\n1,2\n"))
        assert out == ("#table(\n  columns: 2,\n  table.header(\n  [a], [b], \n  ),\n"
                       "  [1], [2], \n  \n)\n\n")

    def test_inline_markup_and_math(self):
        out = render(fence('a,b\n**x**,`c`\n"line1\nline2",$x^2$\n'))
        assert "#strong[x]" in out or "*x*" in out
        assert "line1" in out and "line2" in out
        assert "[line1\nline2]" not in out   # 改行は、生の改行ではなく、行送りになる

    def test_no_header(self):
        out = render(fence("a,b\n1,2\n", "{header_rows=0}"))
        assert "table.header" not in out

    def test_two_header_rows(self):
        out = render(fence("a,b\nc,d\n1,2\n", "{header_rows=2}"))
        assert out.index("[c]") < out.index("),")
        assert out.index("[1]") > out.index("),")

    def test_header_cols_styled(self):
        out = render(fence("a,b\n1,2\n", "{header_cols=1}"), bold=True)
        assert "#strong[1]" in out
        assert "#strong[2]" not in out

    def test_header_cols_background(self):
        out = render(fence("a,b\n1,2\n", "{header_cols=1}"), background="#eeeeee")
        assert "col < 1" in out and "row == 0" in out

    def test_tab_delimiter(self):
        out = render(fence("a\tb\n1,000\t2\n", "{delimiter=tab}"))
        assert "[1,000]" in out


class TestErrors:
    @pytest.mark.parametrize("body,attrs", [("a,b\n1\n", ""), ("a\n", "{bogus=1}"), ("a\n", "{header_rows=x}")])
    def test_fail_fast(self, body, attrs):
        with pytest.raises(SystemExit):
            render(fence(body, attrs))
