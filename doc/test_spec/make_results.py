"""テスト仕様書（testcases/）の実施結果を、pytestの実行結果から作る（#482）。

使い方（リポジトリのルートで）:
    python doc/test_spec/make_results.py                 # pytestを実行して、結果を作る
    python doc/test_spec/make_results.py --junit r.xml   # 実行済みのJUnit XMLから、結果を作る

各ケースの`tests`（pytestのクラス、または関数）に対応するテストを集計し、`testresults/<ID>.yaml`に書く。
1ケースにつき1ファイルを上書きする（履歴はGitに任せる）。判定は、次のとおり。
  - 対応するテストが全て成功: OK
  - 1つでも失敗・エラー: NG
  - 対応するテストが無い、または全てskip: 未実施
"""
import argparse
import datetime
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATUS_OK, STATUS_NG, STATUS_NOT_RUN = "OK", "NG", "未実施"


def load_outcomes(junit_path):
    """JUnit XMLから、[(クラス名, テスト名, "passed"|"failed"|"skipped"), ...]を返す。"""
    outcomes = []
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        outcomes.append((case.get("classname", ""), case.get("name", ""), outcome))
    return outcomes


def matching_outcomes(node, outcomes):
    """`tests/test_x.py::TestY`（クラス）または`tests/test_x.py::test_f`（関数）に対応する結果を返す。"""
    path, _, target = node.partition("::")
    module = path.removesuffix(".py").replace("/", ".")
    if target.startswith("test_"):
        return [o for o in outcomes if o[0] == module and o[1].split("[")[0] == target]
    prefix = f"{module}.{target}"
    return [o for o in outcomes if o[0] == prefix or o[0].startswith(prefix + ".")]


def judge(nodes, outcomes):
    """ケースの判定を、(status, note)で返す。"""
    matched = [o for node in nodes for o in matching_outcomes(node, outcomes)]
    counts = {k: sum(1 for o in matched if o[2] == k) for k in ("passed", "failed", "skipped")}
    note = f"成功 {counts['passed']}・失敗 {counts['failed']}・skip {counts['skipped']}"
    if not matched:
        return STATUS_NOT_RUN, "対応するテストが見つからない"
    if counts["failed"]:
        return STATUS_NG, note
    if not counts["passed"]:
        return STATUS_NOT_RUN, note
    return STATUS_OK, note


def build_result(case, outcomes, tested_at, tested_by):
    status, note = judge(case.get("tests") or [], outcomes)
    result = {"id": case["id"], "tested_at": tested_at, "tested_by": tested_by}
    if case.get("rev") is not None:
        result["spec_rev"] = case["rev"]
    result.update({"status": status, "note": note})
    return result


def write_results(testcases_dir, results_dir, outcomes, tested_at, tested_by):
    """ケースごとに結果を書き、{ID: status}を返す。"""
    results_dir.mkdir(exist_ok=True)
    statuses = {}
    for path in sorted(testcases_dir.glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = build_result(case, outcomes, tested_at, tested_by)
        (results_dir / f"{case['id']}.yaml").write_text(
            yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
        statuses[case["id"]] = result["status"]
    return statuses


def run_pytest(junit_path):
    """pytestを実行し、JUnit XMLを書く。テストの失敗は、結果（NG）として扱うので、終了コードは見ない。"""
    subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", f"--junitxml={junit_path}"],
                   cwd=ROOT, check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", help="実行済みのJUnit XML。省略時は、pytestを実行する")
    parser.add_argument("--tested-by", default="pytest", help="実施者の欄に書く名前（既定: pytest）")
    args = parser.parse_args(argv)

    if args.junit:
        junit_path = Path(args.junit)
        outcomes = load_outcomes(junit_path)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            junit_path = Path(tmp) / "junit.xml"
            run_pytest(junit_path)
            if not junit_path.exists():
                print("pytest did not write a JUnit XML.", file=sys.stderr)
                return 1
            outcomes = load_outcomes(junit_path)

    statuses = write_results(HERE / "testcases", HERE / "testresults", outcomes,
                             datetime.date.today().isoformat(), args.tested_by)
    summary = {s: sum(1 for v in statuses.values() if v == s) for s in (STATUS_OK, STATUS_NG, STATUS_NOT_RUN)}
    print(f"{len(statuses)} cases: " + ", ".join(f"{k} {v}" for k, v in summary.items()))
    return 1 if summary[STATUS_NG] else 0


if __name__ == "__main__":
    sys.exit(main())
