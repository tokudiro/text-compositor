"""Markdownテーブルの本文セル単位の背景色・枠線（#89）のリグレッションテスト。"""
import pytest

from text_compositor.renderer import TypstRenderer


def render(md_text, table_header_style=None):
    renderer = TypstRenderer(line_mapping="off")
    if table_header_style is not None:
        renderer.table_header_style = table_header_style
    return renderer.render(md_text)


def table(*cells):
    """ヘッダ行（h1, h2）と、本文1行（cells）のテーブルを組み立てる。"""
    return "| h1 | h2 |\n| --- | --- |\n| " + " | ".join(cells) + " |\n"


class TestWholeCellSpan:
    def test_bg_becomes_cell_fill(self):
        out = render(table('[実務あり]{bg="#d9f2d9"}', "plain"))
        assert 'table.cell(fill: rgb("#d9f2d9"))[実務あり]' in out

    def test_named_color_is_passed_as_typst_constant(self):
        out = render(table("[x]{bg=red}", "plain"))
        assert "table.cell(fill: red)[x]" in out

    @pytest.mark.parametrize("value,expected", [
        ("dashed", 'dash: "dashed"'),
        ("dotted", 'dash: "dotted"'),
        ("solid", "stroke: 1pt + black"),
        ("none", "stroke: none"),
    ])
    def test_border_styles(self, value, expected):
        out = render(table(f"[x]{{border={value}}}", "plain"))
        assert "table.cell(" in out and expected in out

    def test_bg_and_border_together(self):
        out = render(table('[x]{bg="#eeeeee" border=dashed}', "plain"))
        assert 'fill: rgb("#eeeeee"), stroke: (paint: black, thickness: 1pt, dash: "dashed")' in out

    def test_empty_cell_can_be_styled(self):
        """「空白（概念自体が無い）」を表す、中身が空のセル。"""
        out = render(table('[]{bg="#eeeeee"}', "plain"))
        assert 'table.cell(fill: rgb("#eeeeee"))[]' in out

    def test_inline_markup_inside_the_cell_is_kept(self):
        out = render(table('[**強調** と通常]{bg=yellow}', "plain"))
        assert "table.cell(fill: yellow)[" in out and "#strong[強調]" in out

    def test_text_color_still_applies_inside_the_cell(self):
        out = render(table("[白抜き]{bg=black color=white}", "plain"))
        assert "table.cell(fill: black)[#text(fill: white)[白抜き]]" in out

    def test_header_cells_can_be_styled_too(self):
        out = render('| [h1]{bg=yellow} | h2 |\n| --- | --- |\n| a | b |\n')
        assert "table.cell(fill: yellow)[h1]" in out

    def test_unstyled_cells_are_unchanged(self):
        out = render(table("a", "b"))
        assert "table.cell" not in out
        assert "[a], [b], " in out


class TestIgnored:
    def test_partial_span_is_ignored_with_warning(self, capsys):
        out = render(table("前の[背景]{bg=red}後ろ", "plain"))
        assert "table.cell" not in out and "fill:" not in out
        assert "Ignoring bg/border" in capsys.readouterr().out

    def test_span_outside_a_table_is_ignored_with_warning(self, capsys):
        out = render("本文の[一部]{bg=red}です。\n")
        assert "fill:" not in out
        assert "Ignoring bg/border" in capsys.readouterr().out

    def test_invalid_border_is_ignored_but_bg_is_kept(self, capsys):
        out = render(table('[x]{bg=red border=wavy}', "plain"))
        assert "table.cell(fill: red)[x]" in out and "stroke" not in out
        assert "invalid border 'wavy'" in capsys.readouterr().out

    def test_invalid_border_only_falls_back_to_plain_cell(self, capsys):
        out = render(table("[x]{border=wavy}", "plain"))
        assert "table.cell" not in out and "[x], " in out

    def test_unquoted_hash_value_is_not_a_cell_attribute(self):
        """`{bg=#f5f5f5}`は属性として解釈されない（`#`始まりの値は引用符が要る）。"""
        out = render(table("[x]{bg=#f5f5f5}", "plain"))
        assert "table.cell" not in out


class TestCoexistsWithHeaderStyle:
    def test_table_header_fill_is_still_emitted(self):
        out = render(table('[x]{bg=red}', "plain"), table_header_style={"background": "#dddddd"})
        assert 'fill: (col, row) => if row == 0' in out and "table.cell(fill: red)[x]" in out
