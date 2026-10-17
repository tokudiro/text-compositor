"""テスト仕様書の結果を作るスクリプト（doc/test_spec/make_results.py、#482）のテスト。"""
import importlib.util
from pathlib import Path

import yaml

_SCRIPT = Path(__file__).resolve().parents[1] / "doc" / "test_spec" / "make_results.py"
_spec = importlib.util.spec_from_file_location("make_results", _SCRIPT)
make_results = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_results)

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.test_a.TestOk" name="test_one"/>
  <testcase classname="tests.test_a.TestOk" name="test_two"/>
  <testcase classname="tests.test_a.TestBad" name="test_one"/>
  <testcase classname="tests.test_a.TestBad" name="test_two"><failure message="boom"/></testcase>
  <testcase classname="tests.test_a.TestErr" name="test_one"><error message="boom"/></testcase>
  <testcase classname="tests.test_a.TestSkipped" name="test_one"><skipped message="no browser"/></testcase>
  <testcase classname="tests.test_a.TestMixed" name="test_one"/>
  <testcase classname="tests.test_a.TestMixed" name="test_two"><skipped message="x"/></testcase>
  <testcase classname="tests.test_a.TestOk.TestNested" name="test_n"/>
  <testcase classname="tests.test_b" name="test_func[param]"/>
</testsuite></testsuites>
"""


def _outcomes(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    return make_results.load_outcomes(path)


def test_all_passed_is_ok(tmp_path):
    status, note = make_results.judge(["tests/test_a.py::TestOk"], _outcomes(tmp_path))
    assert status == "OK"
    assert "成功 3" in note   # 入れ子のクラスも、数える


def test_a_failure_makes_the_case_ng(tmp_path):
    assert make_results.judge(["tests/test_a.py::TestBad"], _outcomes(tmp_path))[0] == "NG"


def test_an_error_makes_the_case_ng(tmp_path):
    assert make_results.judge(["tests/test_a.py::TestErr"], _outcomes(tmp_path))[0] == "NG"


def test_only_skipped_is_not_run(tmp_path):
    assert make_results.judge(["tests/test_a.py::TestSkipped"], _outcomes(tmp_path))[0] == "未実施"


def test_passed_and_skipped_is_ok(tmp_path):
    assert make_results.judge(["tests/test_a.py::TestMixed"], _outcomes(tmp_path))[0] == "OK"


def test_no_matching_test_is_not_run(tmp_path):
    status, note = make_results.judge(["tests/test_a.py::TestMissing"], _outcomes(tmp_path))
    assert status == "未実施" and "見つからない" in note


def test_class_name_is_not_matched_by_prefix_of_another_class(tmp_path):
    # TestOkが、TestOkayのような、名前が前方一致するだけの別のクラスを拾わない
    outcomes = _outcomes(tmp_path) + [("tests.test_a.TestOkay", "test_x", "failed")]
    assert make_results.judge(["tests/test_a.py::TestOk"], outcomes)[0] == "OK"


def test_function_node_matches_parametrized_tests(tmp_path):
    assert make_results.judge(["tests/test_b.py::test_func"], _outcomes(tmp_path))[0] == "OK"


def test_any_failing_node_makes_a_multi_node_case_ng(tmp_path):
    nodes = ["tests/test_a.py::TestOk", "tests/test_a.py::TestBad"]
    assert make_results.judge(nodes, _outcomes(tmp_path))[0] == "NG"


def test_write_results_writes_one_file_per_case_and_overwrites(tmp_path):
    cases = tmp_path / "testcases"
    cases.mkdir()
    (cases / "A-01.yaml").write_text(yaml.safe_dump(
        {"id": "A-01", "rev": 2, "tests": ["tests/test_a.py::TestOk"]}), encoding="utf-8")
    (cases / "A-02.yaml").write_text(yaml.safe_dump(
        {"id": "A-02", "tests": ["tests/test_a.py::TestBad"]}), encoding="utf-8")
    results = tmp_path / "testresults"
    outcomes = _outcomes(tmp_path)

    for _ in range(2):   # 2回実行しても、ファイルは増えない
        statuses = make_results.write_results(cases, results, outcomes, "2026-10-17", "pytest")
    assert statuses == {"A-01": "OK", "A-02": "NG"}
    assert sorted(p.name for p in results.iterdir()) == ["A-01.yaml", "A-02.yaml"]

    ok = yaml.safe_load((results / "A-01.yaml").read_text(encoding="utf-8"))
    assert (ok["id"], ok["status"], ok["spec_rev"], ok["tested_by"]) == ("A-01", "OK", 2, "pytest")
    assert str(ok["tested_at"]) == "2026-10-17"
    assert "spec_rev" not in yaml.safe_load((results / "A-02.yaml").read_text(encoding="utf-8"))


def test_every_real_case_has_tests_and_rev():
    for path in sorted((_SCRIPT.parent / "testcases").glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert case.get("tests"), path.name
        assert case.get("rev") is not None, path.name
