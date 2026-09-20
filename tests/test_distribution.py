"""Viewerの配布物（#168）の前提のテスト。

- typstとMermaid用のplaywrightが、なくても、HTML出力が動くこと（HTML出力は、この2つに依存しない。pipで入れる場合の、
  最小の構成。配布物は、Typstを通す処理のために、typstを同梱する。#263）。
- 配布物のPython依存（viewer/dist-requirements.txt）が、pyproject.tomlの依存と、ずれていないこと。"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_python(code, tmp_path):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                          cwd=str(tmp_path), env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})


class TestWithoutTypstAndPlaywright:
    # `sys.modules[name] = None`にすると、importがImportErrorになる（そのパッケージが、無い状態を再現する）
    BLOCK = "import sys; sys.modules['typst'] = None; sys.modules['playwright'] = None; sys.modules['playwright.sync_api'] = None\n"

    def test_importing_the_package_does_not_load_typst(self, tmp_path):
        result = run_python(self.BLOCK + "import text_compositor, text_compositor.build, text_compositor.api\nprint('ok')", tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"

    def test_html_output_works_without_typst_and_playwright(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("# 見出し\n\n本文。\n\n> [!NOTE]\n> alert\n", encoding="utf-8")
        code = self.BLOCK + (
            "import json\nfrom text_compositor.api import render_html\n"
            f"r = render_html({str(md)!r}, plugins={{'mermaid': False, 'plantuml': False, 'd2': False}})\n"
            "print(json.dumps({'ok': r.ok, 'errors': [d.message for d in r.errors]}))")
        result = run_python(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.strip().splitlines()[-1]) == {"ok": True, "errors": []}

    def test_a_pdf_build_without_typst_says_what_is_missing(self, tmp_path):
        code = self.BLOCK + (
            "from text_compositor.compiler import typst_lib\n"
            "try:\n    typst_lib.compile\nexcept ImportError as e:\n    print('IMPORTERROR', e)")
        result = run_python(code, tmp_path)
        assert "IMPORTERROR" in result.stdout and "not needed for HTML output" in result.stdout


def _pins(lines):
    pins = {}
    for line in lines:
        line = line.split("#", 1)[0].strip().strip(",").strip('"')
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)$", line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def test_the_distribution_requirements_follow_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.S | re.M).group(1)
    project = _pins(dependencies.splitlines())
    dist = _pins((ROOT / "viewer" / "dist-requirements.txt").read_text(encoding="utf-8").splitlines())

    assert dist, "no pinned requirements found"
    for name, version in dist.items():
        assert project.get(name) == version, f"{name}: dist {version} != pyproject {project.get(name)}"
    # typstは、Typstを通す処理のために、同梱する（#263。#237で決めた）。Mermaid用のplaywrightは、pyprojectの必須の依存ではなく、
    # ElectronのChromiumで描画するため、同梱しない
    assert "typst" in project and "typst" in dist
    assert "playwright" not in dist
    assert set(project) == set(dist)
