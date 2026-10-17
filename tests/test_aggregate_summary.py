"""aggregateの`join.summary`（集計）と`join.skip_missing`（#66）のテスト。"""
import re

import pytest
import yaml

from text_compositor.chapters import ChapterDefaults, _expand_chapters, _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer

RESULT_COLUMNS = [{"key": "tested_at", "title": "At", "width": "auto"}, {"key": "status", "title": "Status"}]
SPEC = {f"T-0{i}.yaml": {"id": f"T-0{i}", "title": f"t{i}", "priority": p}
        for i, p in enumerate(["High", "High", "Low", "Low", "Low"], 1)}


def _write(directory, files):
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _render(tmp_path, results, join=None, spec=None):
    _write(tmp_path / "tc", spec or SPEC)
    _write(tmp_path / "res", results)
    ch = {"aggregate": "tc", "columns": [{"key": "id"}],
          "join": {"aggregate": "res", "columns": RESULT_COLUMNS, **(join or {})}}
    code, *_ = _render_aggregate_chapter(
        ch, "tc", str(tmp_path), TypstRenderer(line_mapping="off"),
        current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None, current_logo=None, global_logo=None)
    return code


def _summary(code):
    """集計の表のセル行を、[[セル...], ...]で返す（先頭が見出し行）。表が無ければNone。"""
    tables = code.split("#table(")
    if len(tables) < 3:
        return None
    lines = [ln for ln in tables[-1].split("\n") if ln.startswith("  [")]
    return [re.findall(r"\[(.*?)\]", ln) for ln in lines]


def _summary_at_top(code):
    tables = code.split("#table(")
    lines = [ln for ln in tables[1].split("\n") if ln.startswith("  [")]
    return [re.findall(r"\[(.*?)\]", ln) for ln in lines]


RESULTS = {
    "a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "OK"},
    "b.yaml": {"id": "T-02", "tested_at": "2026-10-20", "status": "NG"},
    "c.yaml": {"id": "T-03", "tested_at": "2026-10-20", "status": "N/A"},
}


def test_no_summary_means_no_second_table(tmp_path):
    code = _render(tmp_path, RESULTS)
    assert code.count("#table(") == 1


def test_summary_false_and_show_false_do_not_change_the_output(tmp_path):
    outputs = []
    for i, summary in enumerate([None, False, {"show": False}]):
        join = {} if summary is None else {"summary": summary}
        outputs.append(_render(tmp_path / str(i), RESULTS, join))
    assert outputs[0] == outputs[1] == outputs[2]


def test_summary_counts_tests_not_runs(tmp_path):
    results = {
        "a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "status": "NG"},
        "b.yaml": {"id": "T-01", "tested_at": "2026-10-25", "status": "OK"},   # 再実施
        "c.yaml": {"id": "T-02", "runs": [{"tested_at": "2026-10-20", "status": "NG"},
                                          {"tested_at": "2026-10-21", "status": "NG"}]},
    }
    rows = _summary(_render(tmp_path, results, {"runs": "all", "summary": True}))
    header, line = rows
    assert sorted(h.strip("*") for h in header) == sorted(["合計", "NG", "OK", "未実施"])
    counts = dict(zip([h.strip("*") for h in header], line))
    assert counts["合計"] == "5"   # 仕様のテスト数。再実施で水増ししない
    assert (counts["OK"], counts["NG"], counts["未実施"]) == ("1", "1", "3")


def test_unfilled_status_and_result_without_spec(tmp_path):
    results = {"a.yaml": {"id": "T-01", "tested_at": "2026-10-20"},          # statusが無い
               "b.yaml": {"id": "T-99", "tested_at": "2026-10-20", "status": "OK"}}   # 仕様が無い
    header, line = _summary(_render(tmp_path, results, {"summary": True}))
    counts = dict(zip([h.strip("*") for h in header], line))
    assert counts["合計"] == "5"
    assert counts["（未記入）"] == "1"
    assert "OK" not in counts


def test_explicit_unexecuted_status_joins_the_missing_label(tmp_path):
    results = {"a.yaml": {"id": "T-01", "status": "未実施"}}
    header, line = _summary(_render(tmp_path, results, {"summary": True}))
    counts = dict(zip([h.strip("*") for h in header], line))
    assert counts["未実施"] == "5"


def test_order_and_missing_label(tmp_path):
    join = {"summary": {"order": ["NG", "OK"], "missing_label": "not run"}}
    header, line = _summary(_render(tmp_path, RESULTS, join))
    assert [h.strip("*") for h in header] == ["合計", "NG", "OK", "N/A", "not run"]


def test_rate_classes_and_excluded(tmp_path):
    join = {"summary": {"rate": True, "classes": {"pass": ["OK"], "fail": ["NG"], "excluded": ["N/A"]}}}
    header, line = _summary(_render(tmp_path, RESULTS, join))
    counts = dict(zip([h.strip("*") for h in header], line))
    assert counts["合計"] == "4"          # 対象外のN/Aは、合計に含めない
    assert counts["対象外"] == "1"
    assert "N/A" not in counts            # 対象外の値は、1つの列にまとまる
    assert counts["未実施"] == "2"
    assert counts["合格率"].startswith("50%") and "1/2" in counts["合格率"]   # 分母はpass＋fail


def test_rate_is_a_dash_when_nothing_is_done(tmp_path):
    join = {"summary": {"rate": True, "classes": {"pass": ["OK"]}}}
    header, line = _summary(_render(tmp_path, {}, join))
    assert line[-1] == "-"


def test_pending_class_is_in_total_but_not_in_the_rate(tmp_path):
    results = {"a.yaml": {"id": "T-01", "status": "OK"}, "b.yaml": {"id": "T-02", "status": "保留"}}
    join = {"summary": {"rate": True, "classes": {"pass": ["OK"], "pending": ["保留"]}}}
    header, line = _summary(_render(tmp_path, results, join))
    counts = dict(zip([h.strip("*") for h in header], line))
    assert counts["合計"] == "5"
    assert counts["合格率"].startswith("100%")


def test_group_by_adds_rows_and_a_total_row(tmp_path):
    join = {"summary": {"group_by": "priority", "order": ["OK", "NG"]}}
    rows = _summary(_render(tmp_path, RESULTS, join))
    assert [r[0] for r in rows[1:]] == ["High", "Low", "全体"]
    header = [h.strip("*") for h in rows[0]]
    high = dict(zip(header, rows[1]))
    assert (high["合計"], high["OK"], high["NG"]) == ("2", "1", "1")
    assert dict(zip(header, rows[-1]))["合計"] == "5"


def test_title_and_position(tmp_path):
    code = _render(tmp_path, RESULTS, {"summary": {"title": "Totals", "position": "top"}})
    assert code.index("*Totals*") < code.index("#table(\n  columns: (1fr")
    code = _render(tmp_path / "b", RESULTS, {"summary": {"title": ""}})
    assert "*集計*" not in code


def test_default_title_is_shown_below_the_table(tmp_path):
    code = _render(tmp_path, RESULTS, {"summary": True})
    assert code.index("#table(") < code.index("*集計*")


RERUN = {
    "a.yaml": {"id": "T-01", "tested_at": "2026-10-20", "tested_by": "A", "status": "OK"},
    "b.yaml": {"id": "T-01", "tested_at": "2026-10-25", "tested_by": "A", "status": "未実施"},   # 再実施の予定
    "c.yaml": {"id": "T-02", "tested_at": "2026-10-25", "status": "未実施"},                      # 未実施だけ
}


@pytest.mark.parametrize("skip, expected_ok, expected_missing", [(False, "0", "5"), (True, "1", "4")])
def test_skip_missing_changes_table_and_summary_together(tmp_path, skip, expected_ok, expected_missing):
    code = _render(tmp_path, RERUN, {"skip_missing": skip, "summary": {"order": ["OK"]}})
    header, line = _summary(code)
    counts = dict(zip([h.strip("*") for h in header], line))
    assert (counts["OK"], counts["未実施"]) == (expected_ok, expected_missing)
    # 表（runs: latest）のT-01の行も、同じ判定になる
    row = next(ln for ln in code.split("\n") if ln.startswith("  [T") and "T-01" in ln.replace("​", ""))
    assert ("OK" in row) == skip


def test_skip_missing_keeps_unexecuted_only_tests_unexecuted(tmp_path):
    code = _render(tmp_path, RERUN, {"skip_missing": True, "missing": "n/a"})
    row = next(ln for ln in code.split("\n") if "T-02" in ln.replace("​", "") and ln.startswith("  [T"))
    assert row.count("[n/a]") == 2


def test_runs_all_table_is_not_affected_by_skip_missing(tmp_path):
    a = _render(tmp_path / "a", RERUN, {"runs": "all", "skip_missing": False})
    b = _render(tmp_path / "b", RERUN, {"runs": "all", "skip_missing": True})
    assert a == b


@pytest.mark.parametrize("summary, message", [
    ("yes", "must be true, false or a mapping"),
    ({"rate": True}, "needs classes.pass"),
    ({"rate": True, "classes": {"fail": ["NG"]}}, "needs classes.pass"),
    ({"classes": {"pass": ["OK"], "fail": ["OK"]}}, "in both"),
    ({"classes": {"passed": ["OK"]}}, "unknown class"),
    ({"classes": {"pass": "OK"}}, "must be a list"),
    ({"position": "middle"}, "position must be"),
    ({"order": "OK"}, "must be a list"),
    ({"by": ""}, "must not be empty"),
    ({"rate": "yes"}, "rate must be"),
    ({"group_by": ""}, "group_by must be"),
    ({"bogus": 1}, "unknown key"),
])
def test_invalid_summary_stops_when_chapters_are_expanded(summary, message, capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    join = {"aggregate": "res", "columns": RESULT_COLUMNS, "summary": summary}
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "join": join}], root, "/proj", "/proj")
    assert message in capsys.readouterr().out


def test_invalid_skip_missing_stops(capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    join = {"aggregate": "res", "columns": RESULT_COLUMNS, "skip_missing": "yes"}
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "join": join}], root, "/proj", "/proj")
    assert "skip_missing must be" in capsys.readouterr().out
