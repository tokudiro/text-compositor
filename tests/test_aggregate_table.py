"""aggregateの表（テストケース一覧）の列幅リグレッションテスト（#269）。

長いTitleがあっても、Steps・Expected列が極端に細くならないこと
（Steps・ExpectedのfrがTitleのfr以上であること）を確認する。
"""
import re

import yaml

from text_compositor.chapters import _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer


def test_aggregate_table_gives_steps_and_expected_generous_width(tmp_path):
    agg_dir = tmp_path / "tc"
    agg_dir.mkdir()
    (agg_dir / "tc001.yaml").write_text(
        yaml.safe_dump({
            "id": "TC-001",
            "title": "とても長いタイトルの例（tests/test_example.py::TestExample::test_something_long）",
            "priority": "High",
            "steps": "1. 手順A\n2. 手順B",
            "expected": "期待される結果",
        }, allow_unicode=True),
        encoding="utf-8",
    )

    renderer = TypstRenderer(line_mapping="off")
    typst_code, *_ = _render_aggregate_chapter(
        {"aggregate": "tc", "title": "Test Cases"}, "tc", str(tmp_path), renderer,
        current_landscape=False, current_paper="a4",
        global_landscape=False, global_paper="a4",
        current_header=None, current_footer=None, current_paginate=True,
        global_header=None, global_footer=None, global_paginate=True,
        current_background=None, global_background=None,
        current_logo=None, global_logo=None,
    )

    m = re.search(r"columns:\s*\(([^)]*)\)", typst_code)
    assert m, "table columns definition not found"
    columns = [c.strip() for c in m.group(1).split(",")]

    # ID・PriorityはautoでよいがTitleはfrで折り返し可能にし、
    # Steps・ExpectedはTitleを圧迫しないfr幅を持つこと。
    assert columns[0] == "auto"  # ID
    assert columns[2] == "auto"  # Priority
    assert columns[1].endswith("fr"), "Title column must be a fr column, not auto (#269)"
    assert columns[3].endswith("fr")  # Steps
    assert columns[4].endswith("fr")  # Expected

    title_fr = float(columns[1].removesuffix("fr"))
    steps_fr = float(columns[3].removesuffix("fr"))
    expected_fr = float(columns[4].removesuffix("fr"))
    assert steps_fr >= title_fr, "Steps column must not be narrower than Title (#269)"
    assert expected_fr >= title_fr, "Expected column must not be narrower than Title (#269)"
