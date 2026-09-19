"""Viewer（Obunzu）のバージョンが、text-compositorのバージョンと連動していること（#194）。

ウィンドウのタイトルに出るバージョンは、`viewer/package.json`のversionである。版上げのときに、`pyproject.toml`だけを
上げて、Viewerの側を忘れると、画面のバージョンが古いまま配布される。それを、テストで防ぐ。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_viewer_version_follows_the_package_version():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE).group(1)

    viewer = json.loads((ROOT / "viewer" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "viewer" / "package-lock.json").read_text(encoding="utf-8"))

    assert viewer["version"] == package_version
    assert lock["version"] == package_version
    assert lock["packages"][""]["version"] == package_version
