"""ドキュメントの記法バッジ（doc/usage/badges/、#216）のテスト。"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USAGE = ROOT / "doc" / "usage"


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_badges", USAGE / "badges" / "make_badges.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_badge_referenced_in_the_usage_docs_exists():
    referenced = set()
    for doc in USAGE.glob("*.md"):
        for path in re.findall(r"!\[[^\]]*\]\((badges/[^)]+)\)", doc.read_text(encoding="utf-8")):
            referenced.add(path)
            assert (USAGE / path).is_file(), f"{doc.name}: {path} がありません"
    assert referenced, "バッジが、どのドキュメントにも使われていません"


def test_the_committed_badges_match_the_generator():
    """make_badges.pyを変えたのに、SVGを作り直し忘れることを防ぐ。"""
    generator = _load_generator()
    for name, text, color, meaning in generator.BADGES:
        expected = generator.svg(text, color, meaning)
        actual = (USAGE / "badges" / f"{name}.svg").read_text(encoding="utf-8")
        assert actual == expected, f"{name}.svg が、make_badges.pyの出力と違います（python doc/usage/badges/make_badges.py で作り直す）"


def test_badge_text_is_readable_on_its_background():
    generator = _load_generator()
    for name, _, color, _ in generator.BADGES:
        assert generator.contrast_with_white(color) >= 4.5, name
