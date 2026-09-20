"""手動で使うスクリプト（benchmarks/・viewer/scripts/）が、`text_compositor.build`から使う名前が、今もあること（#157）。

`build.py`を、責務ごとのモジュールに分けたとき（#157）、関数や定数の多くが、別のモジュールへ移った。CIで動かさない
スクリプトが、`build.<名前>`のまま残ると、移したあとの、手動の実行で、初めて壊れる（`check-dist.js`が、
`build._download`を呼んで、失敗した）。テストは、スクリプトを実行せず、参照する名前が、`build`に、あるかだけを確かめる。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "benchmarks").rglob("*.py")) + sorted((ROOT / "viewer" / "scripts").glob("*.js"))


def _aliases_of_build(text):
    """`import text_compositor.build as B`・`from text_compositor import build`で、buildモジュールにつけた名前。"""
    aliases = set(re.findall(r"import text_compositor\.build as (\w+)", text))
    if re.search(r"from text_compositor import build\b", text):
        aliases.add("build")
    return aliases


def test_scripts_only_use_names_that_the_build_module_still_has():
    import text_compositor.build as build

    problems = []
    for path in SCRIPTS:
        text = path.read_text(encoding="utf-8")
        for alias in _aliases_of_build(text):
            for name in sorted(set(re.findall(rf"\b{alias}\.(\w+)", text))):
                if not hasattr(build, name):
                    problems.append(f"{path.relative_to(ROOT).as_posix()}: {alias}.{name}")
    assert not problems, "text_compositor.buildに、無い名前を使っている（移動先のモジュールから、importする）:\n" + "\n".join(problems)


def test_the_scripts_to_check_are_found():
    """スクリプトの置き場所が変わって、何も調べなくなる（常に成功する）ことを防ぐ。"""
    names = {p.name for p in SCRIPTS}
    assert {"gui_latency.py", "worker_startup.py", "check-dist.js"} <= names
