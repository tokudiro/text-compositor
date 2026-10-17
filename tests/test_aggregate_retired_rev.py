"""aggregateの`join.retired`（廃止したテスト）と`join.rev`（仕様の版の確認）のテスト（#66）。"""
import re

import pytest
import yaml

from text_compositor.chapters import ChapterDefaults, _expand_chapters, _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer

RESULT_COLUMNS = [{"key": "status", "title": "Status", "width": "auto"}]


def _write(directory, files):
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _render(tmp_path, spec, results, join):
    _write(tmp_path / "tc", spec)
    _write(tmp_path / "res", results)
    ch = {"aggregate": "tc", "columns": [{"key": "id", "width": "auto"}],
          "join": {"aggregate": "res", "columns": RESULT_COLUMNS, **join}}
    code, *_ = _render_aggregate_chapter(
        ch, "tc", str(tmp_path), TypstRenderer(line_mapping="off"),
        current_landscape=False, current_paper="a4", global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None, current_logo=None, global_logo=None)
    return code


def _tables(code):
    out = []
    for chunk in code.split("#table(")[1:]:
        lines = [ln for ln in chunk.split("\n") if ln.startswith("  [")]
        out.append([[c.replace("​", "") for c in re.findall(r"\[(.*?)\]", ln)] for ln in lines])
    return out


def _counts(summary_table):
    header, line = summary_table
    return dict(zip([h.strip("*") for h in header], line))


SPEC = {
    "T-01.yaml": {"id": "T-01", "rev": 3},
    "T-02.yaml": {"id": "T-02", "rev": 3, "status": "廃止"},
    "T-03.yaml": {"id": "T-03"},   # 版を持たない
}
RESULTS = {
    "a.yaml": {"id": "T-01", "spec_rev": 3, "status": "OK"},
    "b.yaml": {"id": "T-02", "spec_rev": 3, "status": "OK"},
    "c.yaml": {"id": "T-03", "status": "OK"},
}
RETIRED = {"key": "status", "values": ["廃止"]}


def test_retired_test_is_hidden_from_table_and_summary_by_default(tmp_path, capsys):
    code = _render(tmp_path, SPEC, RESULTS, {"retired": RETIRED, "summary": True})
    table, summary = _tables(code)
    assert [r[0] for r in table[1:]] == ["T-01", "T-03"]
    assert _counts(summary)["合計"] == "2"
    assert "T-02" not in capsys.readouterr().out   # 結果が残っていても、警告しない


def test_retired_with_show_keeps_the_row_but_not_the_count(tmp_path):
    code = _render(tmp_path, SPEC, RESULTS, {"retired": {**RETIRED, "show": True}, "summary": True})
    table, summary = _tables(code)
    assert [r[0] for r in table[1:]] == ["T-01", "T-02", "T-03"]
    assert _counts(summary)["合計"] == "2"


def test_retired_is_also_hidden_in_a_runs_all_table(tmp_path):
    code = _render(tmp_path, SPEC, RESULTS, {"retired": RETIRED, "runs": "all"})
    assert "T-02" not in code


def test_without_retired_every_test_is_shown(tmp_path):
    code = _render(tmp_path, SPEC, RESULTS, {"summary": True})
    assert _counts(_tables(code)[1])["合計"] == "3"


def test_rev_match_keeps_the_result(tmp_path):
    code = _render(tmp_path, SPEC, RESULTS, {"rev": True})
    rows = {r[0]: r for r in _tables(code)[0][1:]}
    assert rows["T-01"][1] == "OK"


def test_rev_mismatch_shows_the_label(tmp_path):
    results = {**RESULTS, "a.yaml": {"id": "T-01", "spec_rev": 2, "status": "OK"}}
    code = _render(tmp_path, SPEC, results, {"rev": True})
    rows = {r[0]: r for r in _tables(code)[0][1:]}
    assert rows["T-01"][1] == "要再実施"


def test_rev_compares_as_strings(tmp_path):
    results = {**RESULTS, "a.yaml": {"id": "T-01", "spec_rev": "3", "status": "OK"}}
    rows = {r[0]: r for r in _tables(_render(tmp_path, SPEC, results, {"rev": True}))[0][1:]}
    assert rows["T-01"][1] == "OK"


def test_result_without_spec_rev_is_stale_and_warned(tmp_path, capsys):
    results = {**RESULTS, "a.yaml": {"id": "T-01", "status": "OK"}}
    code = _render(tmp_path, SPEC, results, {"rev": True})
    rows = {r[0]: r for r in _tables(code)[0][1:]}
    assert rows["T-01"][1] == "要再実施"
    assert "T-01" in capsys.readouterr().out


def test_spec_without_rev_is_not_checked(tmp_path):
    rows = {r[0]: r for r in _tables(_render(tmp_path, SPEC, RESULTS, {"rev": True}))[0][1:]}
    assert rows["T-03"][1] == "OK"   # 結果にspec_revが無くても、仕様にrevが無ければ確認しない


def test_untested_test_stays_untested_with_rev(tmp_path):
    code = _render(tmp_path, SPEC, {}, {"rev": True, "missing": "none"})
    rows = {r[0]: r for r in _tables(code)[0][1:]}
    assert rows["T-01"][1] == "none"


def test_custom_rev_keys_and_label(tmp_path):
    spec = {"a.yaml": {"id": "T-01", "version": "b"}}
    results = {"r.yaml": {"id": "T-01", "tested_version": "a", "status": "OK"}}
    rev = {"spec": "version", "result": "tested_version", "label": "retest"}
    rows = _tables(_render(tmp_path, spec, results, {"rev": rev}))[0]
    assert rows[1][1] == "retest"


def test_stale_result_counts_as_pending_in_the_summary(tmp_path):
    results = {**RESULTS, "a.yaml": {"id": "T-01", "spec_rev": 2, "status": "OK"}}
    join = {"rev": True, "summary": {"rate": True, "classes": {"pass": ["OK"], "fail": ["NG"]}}}
    counts = _counts(_tables(_render(tmp_path, SPEC, results, join))[1])
    assert counts["合計"] == "3"
    assert counts["要再実施"] == "1"
    assert counts["合格率"].startswith("100%") and "2/2" in counts["合格率"]   # 要再実施は分母に入れない


def test_runs_all_table_does_not_replace_the_status(tmp_path):
    results = {"a.yaml": {"id": "T-01", "spec_rev": 2, "status": "OK"}}
    code = _render(tmp_path, SPEC, results, {"rev": True, "runs": "all"})
    rows = {r[0]: r for r in _tables(code)[0][1:]}
    assert rows["T-01"][1] == "OK"


def test_order_retired_then_latest_then_rev_then_class(tmp_path):
    spec = {"a.yaml": {"id": "T-01", "rev": 3}, "b.yaml": {"id": "T-02", "rev": 3, "status": "廃止"}}
    results = {
        "a1.yaml": {"id": "T-01", "tested_at": "2026-10-20", "spec_rev": 3, "status": "OK"},
        "a2.yaml": {"id": "T-01", "tested_at": "2026-10-25", "status": "未実施"},   # 再実施の予定
        "b1.yaml": {"id": "T-02", "spec_rev": 1, "status": "NG"},
    }
    join = {"retired": RETIRED, "skip_missing": True, "rev": True,
            "summary": {"classes": {"pass": ["OK"]}}}
    counts = _counts(_tables(_render(tmp_path, spec, results, join))[1])
    # T-02は廃止で除く。T-01は、skip_missingで1回目(spec_rev 3)が最新になり、版が合うのでOK。
    assert counts["合計"] == "1" and counts["OK"] == "1"


@pytest.mark.parametrize("join_extra, message", [
    ({"retired": "x"}, "must be a mapping"),
    ({"retired": {"values": ["a"]}}, "'key' is required"),
    ({"retired": {"key": "s"}}, "values must be a list"),
    ({"retired": {"key": "s", "values": []}}, "must not be empty"),
    ({"retired": {"key": "s", "values": ["a"], "show": "no"}}, "show must be"),
    ({"retired": {"key": "s", "values": ["a"], "hide": True}}, "unknown key"),
    ({"rev": "x"}, "must be true or a mapping"),
    ({"rev": {"spec": ""}}, "non-empty string"),
    ({"rev": {"label": 1}}, "non-empty string"),
    ({"rev": {"other": 1}}, "unknown key"),
])
def test_invalid_retired_and_rev_stop_when_chapters_are_expanded(join_extra, message, capsys):
    root = ChapterDefaults(False, "a4", None, None, True, None, None, {}, 0)
    join = {"aggregate": "res", "columns": RESULT_COLUMNS, **join_extra}
    with pytest.raises(SystemExit):
        _expand_chapters([{"aggregate": "tc", "join": join}], root, "/proj", "/proj")
    assert message in capsys.readouterr().out
