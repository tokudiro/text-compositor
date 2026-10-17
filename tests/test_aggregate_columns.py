"""aggregateの`columns`（列の設定、#65）のテスト。"""
import re

import pytest
import yaml

from text_compositor.chapters import _expand_chapters, _parse_aggregate_columns, _render_aggregate_chapter, ChapterDefaults
from text_compositor.renderer import TypstRenderer


def _render(tmp_path, ch_dict, files):
    agg_dir = tmp_path / "tc"
    agg_dir.mkdir()
    for name, data in files.items():
        (agg_dir / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    renderer = TypstRenderer(line_mapping="off")
    typst_code, *_ = _render_aggregate_chapter(
        {"aggregate": "tc", **ch_dict}, "tc", str(tmp_path), renderer,
        current_landscape=False, current_paper="a4",
        global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None,
        current_logo=None, global_logo=None,
    )
    return typst_code


def test_omitted_columns_keep_the_five_default_columns(tmp_path):
    code = _render(tmp_path, {}, {"a.yaml": {"id": "TC-1", "title": "t", "priority": "High",
                                              "steps": ["1. a", "2. b"], "expected": "ok"}})
    assert "columns: (auto, 1fr, auto, 2fr, 2fr)," in code
    assert "align: (center, left, center, left, left)," in code
    assert "[*ID*], [*Title*], [*Priority*], [*Steps*], [*Expected*]," in code


def test_custom_columns_set_headers_widths_and_aligns(tmp_path):
    code = _render(tmp_path, {"columns": [
        {"key": "id", "title": "ID", "width": "auto", "align": "center"},
        {"key": "tested_by", "title": "実施者"},
        {"key": "actual_result", "title": "実際の結果", "width": "2fr", "markdown": True},
        {"key": "status", "align": "right"},
    ]}, {"a.yaml": {"id": "TC-1", "tested_by": "Taro", "actual_result": "- x\n- y", "status": "pass"}})
    assert "columns: (auto, 1fr, 2fr, 1fr)," in code
    assert "align: (center, left, left, right)," in code
    assert "[*ID*], [*実施者*], [*実際の結果*], [*status*]," in code   # titleの省略時はkey
    assert "Taro" in code and "pass" in code


def test_missing_key_gives_an_empty_cell(tmp_path):
    code = _render(tmp_path, {"columns": [{"key": "id"}, {"key": "status"}]}, {"a.yaml": {"id": "TC-1"}})
    # 幅がautoでない列には、ソフト改行点（U+200B）が入るので、IDの文字は完全一致で比べない。
    assert re.search(r"^  \[TC.{1,2}1\], \[\],$", code, re.M)


def test_list_value_is_joined_by_comma_unless_markdown(tmp_path):
    code = _render(tmp_path, {"columns": [{"key": "tags"}]}, {"a.yaml": {"tags": ["a", "b"]}})
    assert "a、b" in code


def test_auto_width_column_gets_no_soft_break_hints(tmp_path):
    code = _render(tmp_path, {"columns": [{"key": "id", "width": "auto"}, {"key": "path", "width": "1fr"}]},
                   {"a.yaml": {"id": "tests/test_example.py::TestExample", "path": "tests/test_example.py::TestExample"}})
    cells = re.findall(r"^  \[(.*)\], \[(.*)\],$", code, re.M)[-1]   # 先頭は見出し行
    assert "​" not in cells[0]
    assert "​" in cells[1]


@pytest.mark.parametrize("columns, message", [
    ([], "non-empty list"),
    ("id", "non-empty list"),
    ([{"title": "ID"}], "'key' is required"),
    ([{"key": "id", "width": "wide"}], "width must be"),
    ([{"key": "id", "width": "1.5"}], "width must be"),
    ([{"key": "id", "align": "middle"}], "align must be"),
    ([{"key": "id"}, {"key": "id"}], "duplicate key"),
    ([{"key": "id", "markdown": "yes"}], "markdown must be"),
    ([{"key": "id", "colour": "red"}], "unknown key"),
    (["id"], "must be a mapping"),
])
def test_invalid_columns_stop_with_a_config_error(columns, message, capsys):
    with pytest.raises(SystemExit):
        _parse_aggregate_columns(columns, "chapter 'tc'")
    assert message in capsys.readouterr().out


def test_invalid_columns_are_rejected_when_chapters_are_expanded(capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "columns": [{"title": "x"}]}], root, "/proj", "/proj")
    assert "'key' is required" in capsys.readouterr().out


def test_columns_on_a_file_chapter_is_an_error(capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    with pytest.raises(SystemExit):
        _expand_chapters([{"file": "a.md", "columns": [{"key": "id"}]}], root, "/proj", "/proj")
    assert "only be used with 'aggregate'" in capsys.readouterr().out
