"""フローチャートのガイド（doc/usage/30_flowchart.md。#536）の例が、実装で解析できることを調べる。

文書と実装の食い違い（キーワードの変更など）を、ガイドの例が古くなる前に、見つけるための検査。
"""
import re
from pathlib import Path

import pytest

from text_compositor import flowchart_notation as fn

DOC_USAGE = Path(__file__).resolve().parent.parent / "doc" / "usage"
GUIDE = DOC_USAGE / "30_flowchart.md"
FENCE = re.compile(r"^```(?P<lang>\w+)[^\n]*\n(?P<code>.*?)^```", re.S | re.M)


def _blocks(path):
    return [(m.group("lang"), m.group("code")) for m in FENCE.finditer(path.read_text(encoding="utf-8"))]


def _flowcharts(path):
    return [code for lang, code in _blocks(path) if lang == "flowchart"]


def test_the_guide_is_part_of_the_usage_guide():
    config = (DOC_USAGE / "text-compositor.config.yaml").read_text(encoding="utf-8")
    assert '"30_flowchart.md"' in config


def test_every_example_in_the_guide_parses():
    codes = _flowcharts(GUIDE)
    assert len(codes) >= 8
    for code in codes:
        fn.parse(code)


def test_a_source_block_shown_before_a_figure_is_the_same_text_as_the_figure():
    """「書き方」と「描いた図」を並べた例は、同じテキストにする（片方だけ直して、食い違うのを防ぐ）。"""
    blocks = _blocks(GUIDE)
    pairs = [(a[1], b[1]) for a, b in zip(blocks, blocks[1:]) if a[0] == "text" and b[0] == "flowchart"]
    assert len(pairs) >= 5
    for source, figure in pairs:
        assert source == figure


def test_every_error_message_in_the_guide_is_what_the_parser_says():
    text = GUIDE.read_text(encoding="utf-8")
    messages = re.findall(r"^\| [^|]+ \| `([^`]+)` \|$", text, re.M)
    assert len(messages) >= 5
    samples = [
        "judge 1つだけ?\n  はい: 処理\n",
        "loop L\n  処理\n",
        "loop L: 始め\n  処理\nendloop: 終わり\n",
        "judge x?\n\tはい: A\n\tいいえ: B\n",
        '"閉じ忘れ\n',
    ]
    said = []
    for code in samples:
        with pytest.raises(fn.FlowchartError) as e:
            fn.parse(code)
        said.append(str(e.value))
    for message in messages:
        assert message in said, message
