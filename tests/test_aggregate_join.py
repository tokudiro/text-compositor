"""aggregateの`join`（テスト仕様と結果の結合表、#66）のテスト。"""
import re

import pytest
import yaml

from text_compositor.chapters import ChapterDefaults, _expand_chapters, _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer

SPEC_COLUMNS = [{"key": "id", "title": "ID", "width": "auto"}, {"key": "title", "title": "Title"}]
RESULT_COLUMNS = [{"key": "tested_at", "title": "At", "width": "auto"},
                  {"key": "tested_by", "title": "By", "width": "auto"},
                  {"key": "status", "title": "Status", "width": "auto"}]


def _write(directory, files):
    directory.mkdir()
    for name, data in files.items():
        (directory / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _render(tmp_path, spec, results, join=None, columns=None):
    _write(tmp_path / "tc", spec)
    _write(tmp_path / "res", results)
    ch = {"aggregate": "tc", "columns": columns or SPEC_COLUMNS,
          "join": {"aggregate": "res", "columns": RESULT_COLUMNS, **(join or {})}}
    renderer = TypstRenderer(line_mapping="off")
    code, *_ = _render_aggregate_chapter(
        ch, "tc", str(tmp_path), renderer,
        current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None, current_logo=None, global_logo=None)
    return code


def _rows(code):
    """見出し行を除いた、データ行のセル（ソフト改行点U+200Bを除いたもの）のリスト。"""
    lines = [ln for ln in code.split("\n") if ln.startswith("  [")][1:]
    return [[c.replace("​", "") for c in re.findall(r"\[(.*?)\]", ln)] for ln in lines]


SPEC = {"T-01.yaml": {"id": "T-01", "title": "first"}, "T-02.yaml": {"id": "T-02", "title": "second"}}


def test_style1_one_file_per_run_latest_by_tested_at(tmp_path):
    results = {
        "a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "tested_by": "A", "status": "NG"},
        "b.yaml": {"id": "T-01", "tested_at": "2026-10-25", "tested_by": "B", "status": "OK"},
    }
    rows = _rows(_render(tmp_path, SPEC, results))
    assert rows[0] == ["T-01", "first", "2026-10-25", "B", "OK"]


def test_style2_runs_list_and_common_values(tmp_path):
    results = {"T-01.yaml": {"id": "T-01", "tested_by": "A", "runs": [
        {"tested_at": "2026-10-25", "status": "OK"},
        {"tested_at": "2026-10-20", "status": "NG", "tested_by": "B"},
    ]}}
    rows = _rows(_render(tmp_path, SPEC, results))
    assert rows[0] == ["T-01", "first", "2026-10-25", "A", "OK"]   # 共通値のtested_byが入る


def test_runs_all_shows_every_run_and_blanks_spec_after_the_first_row(tmp_path):
    results = {"T-01.yaml": {"id": "T-01", "runs": [
        {"tested_at": "2026-10-25", "tested_by": "A", "status": "OK"},
        {"tested_at": "2026-10-20", "tested_by": "B", "status": "NG"},
    ]}}
    rows = _rows(_render(tmp_path, SPEC, results, join={"runs": "all"}))
    assert rows[0] == ["T-01", "first", "2026-10-20", "B", "NG"]
    assert rows[1] == ["", "", "2026-10-25", "A", "OK"]
    assert rows[2][:2] == ["T-02", "second"]


def test_mixed_styles_in_one_directory(tmp_path):
    results = {
        "T-01_a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "NG"},
        "T-01_b.yaml": {"id": "T-01", "runs": [{"tested_at": "2026-10-25", "status": "OK"}]},
    }
    rows = _rows(_render(tmp_path, SPEC, results, join={"runs": "all"}))
    assert [r[2] for r in rows[:2]] == ["2026-10-20", "2026-10-25"]


def test_untested_test_gets_the_missing_text(tmp_path):
    results = {"a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "tested_by": "A", "status": "OK"}}
    rows = _rows(_render(tmp_path, SPEC, results, join={"missing": "n/a"}))
    assert rows[1] == ["T-02", "second", "n/a", "n/a", "n/a"]


def test_untested_test_is_empty_by_default(tmp_path):
    rows = _rows(_render(tmp_path, SPEC, {"a.yaml": {"id": "T-01", "status": "OK"}}))
    assert rows[1] == ["T-02", "second", "", "", ""]


def test_result_without_spec_is_warned_and_appended(tmp_path, capsys):
    results = {"a.yaml": {"id": "T-99", "tested_at": "2026-10-20", "tested_by": "A", "status": "OK"}}
    rows = _rows(_render(tmp_path, SPEC, results))
    assert rows[-1] == ["", "", "2026-10-20", "A", "OK"]
    assert len(rows) == 3
    assert "T-99" in capsys.readouterr().out


def test_result_without_id_is_warned_and_skipped(tmp_path, capsys):
    rows = _rows(_render(tmp_path, SPEC, {"a.yaml": {"status": "OK"}}))
    assert len(rows) == 2
    assert "a.yaml" in capsys.readouterr().out


def test_same_id_and_tested_at_is_warned_as_possible_duplicate(tmp_path, capsys):
    results = {"a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "OK"},
               "b.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "OK"}}
    _render(tmp_path, SPEC, results)
    assert "duplicates" in capsys.readouterr().out


def test_different_tested_at_is_not_a_duplicate(tmp_path, capsys):
    results = {"a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "OK"},
               "b.yaml": {"id": "T-01", "tested_at": "2026-10-21", "status": "OK"}}
    _render(tmp_path, SPEC, results)
    assert "duplicates" not in capsys.readouterr().out


def test_custom_join_key(tmp_path):
    spec = {"a.yaml": {"no": "7", "title": "t"}}
    results = {"r.yaml": {"no": 7, "status": "OK"}}
    rows = _rows(_render(tmp_path, spec, results, join={"key": "no"},
                         columns=[{"key": "no"}, {"key": "title"}]))
    assert rows[0][-1] == "OK"   # 7と"7"は、文字列として突き合わせる


def test_chapter_without_join_is_unchanged(tmp_path):
    _write(tmp_path / "tc", SPEC)
    renderer = TypstRenderer(line_mapping="off")
    code, *_ = _render_aggregate_chapter(
        {"aggregate": "tc", "columns": SPEC_COLUMNS}, "tc", str(tmp_path), renderer,
        current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None, current_logo=None, global_logo=None)
    assert "columns: (auto, 1fr)," in code


def test_missing_results_directory_is_an_error(tmp_path, capsys):
    _write(tmp_path / "tc", SPEC)
    renderer = TypstRenderer(line_mapping="off")
    with pytest.raises(SystemExit):
        _render_aggregate_chapter(
            {"aggregate": "tc", "join": {"aggregate": "nowhere", "columns": RESULT_COLUMNS}}, "tc",
            str(tmp_path), renderer,
            current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
            current_header=None, current_footer=None, current_paginate=True,
            global_header=None, global_footer=None, global_paginate=True,
            current_background=None, global_background=None, current_logo=None, global_logo=None)
    assert "nowhere" in capsys.readouterr().out


@pytest.mark.parametrize("join, message", [
    ("res", "must be a mapping"),
    ({"columns": RESULT_COLUMNS}, "'aggregate' is required"),
    ({"aggregate": "res"}, "'columns' is required"),
    ({"aggregate": "res", "columns": RESULT_COLUMNS, "runs": "first"}, "runs must be one of"),
    ({"aggregate": "res", "columns": RESULT_COLUMNS, "missing": 1}, "missing must be a string"),
    ({"aggregate": "res", "columns": RESULT_COLUMNS, "key": ""}, "key must be"),
    ({"aggregate": "res", "columns": RESULT_COLUMNS, "summary": True}, "unknown key"),
    ({"aggregate": "res", "columns": [{"title": "x"}]}, "'key' is required"),
])
def test_invalid_join_stops_when_chapters_are_expanded(join, message, capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "join": join}], root, "/proj", "/proj")
    assert message in capsys.readouterr().out


def test_join_on_a_file_chapter_is_an_error(capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    with pytest.raises(SystemExit):
        _expand_chapters([{"file": "a.md", "join": {}}], root, "/proj", "/proj")
    assert "only be used with 'aggregate'" in capsys.readouterr().out
