"""aggregateの`font_size`（表と集計の文字の大きさ、#484）のテスト。"""
import pytest
import yaml

from text_compositor.chapters import ChapterDefaults, _expand_chapters, _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer


def _render(tmp_path, ch_extra):
    agg = tmp_path / "tc"
    agg.mkdir()
    (agg / "a.yaml").write_text(yaml.safe_dump({"id": "T-1", "title": "t"}), encoding="utf-8")
    code, *_ = _render_aggregate_chapter(
        {"aggregate": "tc", "title": "Heading", **ch_extra}, "tc", str(tmp_path), TypstRenderer(line_mapping="off"),
        current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None, current_logo=None, global_logo=None)
    return code


def test_font_size_wraps_only_the_table(tmp_path):
    code = _render(tmp_path, {"font_size": "8pt"})
    assert "#[\n#set text(size: 8pt)\n#table(" in code
    assert code.index("= Heading") < code.index("#set text(size: 8pt)")   # 見出しは、表の外


def test_decimal_font_size(tmp_path):
    assert "size: 7.5pt" in _render(tmp_path, {"font_size": "7.5pt"})


def test_font_size_also_applies_to_the_summary(tmp_path):
    (tmp_path / "res").mkdir()
    code = _render(tmp_path, {"font_size": "8pt", "join": {
        "aggregate": "res", "columns": [{"key": "status"}], "summary": True}})
    wrapped = code[code.index("#set text"):code.rindex("]\n#pagebreak")]
    assert wrapped.count("#table(") == 2


def test_without_font_size_the_output_is_unchanged(tmp_path):
    assert "#set text" not in _render(tmp_path, {})


@pytest.mark.parametrize("value", ["8", "8px", "pt", "-8pt", "8 pt", 8, True, ["8pt"]])
def test_invalid_font_size_stops_when_chapters_are_expanded(value, capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "font_size": value}], root, "/proj", "/proj")
    assert "font_size must look like" in capsys.readouterr().out
