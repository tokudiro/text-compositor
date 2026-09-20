"""ViewerのZIPに同梱した、フォントとTypstのパッケージを使う仕組み（#263）のテスト。ネットワークは使わない。"""
import os
import re
import urllib.request
from pathlib import Path

import pytest

import text_compositor.deps as deps_mod
from text_compositor.compiler import TYPST_PACKAGES_ENV, typst_package_options
from text_compositor.deps import FONT_DIR_ENV, NOTO_SANS_JP_FILES, ensure_fonts

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def no_download(monkeypatch, tmp_path):
    """取得を試みたら、失敗させる。ユーザーのキャッシュも、使い捨てにする。"""
    monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(urllib.request, "urlretrieve", lambda *a, **k: pytest.fail("downloaded"))


class TestBundledFonts:
    def test_a_complete_bundled_folder_is_used_without_downloading(self, tmp_path, monkeypatch, no_download):
        bundled = tmp_path / "fonts"
        bundled.mkdir()
        for name in NOTO_SANS_JP_FILES:
            (bundled / name).write_bytes(b"font")
        monkeypatch.setenv(FONT_DIR_ENV, str(bundled))
        assert ensure_fonts() == str(bundled)
        assert not (tmp_path / "cache").exists()   # ユーザーのキャッシュにも、何も作らない

    def test_an_incomplete_folder_warns_and_falls_back_to_the_download(self, tmp_path, monkeypatch, no_download, capsys):
        bundled = tmp_path / "fonts"
        bundled.mkdir()
        (bundled / "NotoSansJP-Regular.otf").write_bytes(b"font")   # Boldが無い
        monkeypatch.setenv(FONT_DIR_ENV, str(bundled))
        with pytest.raises(BaseException, match="downloaded"):
            ensure_fonts()   # 通常の取得へ進む（このテストでは、取得を失敗させてある）
        captured = capsys.readouterr()
        assert FONT_DIR_ENV in captured.out + captured.err   # 警告が出る（出力先は、ログの実装に任せる）

    def test_without_the_variable_the_behavior_is_unchanged(self, tmp_path, monkeypatch, no_download):
        monkeypatch.delenv(FONT_DIR_ENV, raising=False)
        with pytest.raises(BaseException, match="downloaded"):
            ensure_fonts()


class TestBundledTypstPackages:
    def test_no_variable_means_no_option(self, monkeypatch):
        monkeypatch.delenv(TYPST_PACKAGES_ENV, raising=False)
        assert typst_package_options() == {}

    def test_an_existing_folder_becomes_package_cache_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv(TYPST_PACKAGES_ENV, str(tmp_path))
        assert typst_package_options() == {"package_cache_path": str(tmp_path)}

    def test_a_missing_folder_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setenv(TYPST_PACKAGES_ENV, str(tmp_path / "nope"))
        assert typst_package_options() == {}

    def test_a_bundled_package_folder_is_enough_to_compile_offline(self, tmp_path, monkeypatch):
        """置いたパッケージだけで、`@preview/...`が解決される（ダウンロードには、頼らない）。"""
        typst = pytest.importorskip("typst")
        package = tmp_path / "packages" / "preview" / "mini" / "0.1.0"
        package.mkdir(parents=True)
        (package / "typst.toml").write_text('[package]\nname = "mini"\nversion = "0.1.0"\nentrypoint = "lib.typ"\n', encoding="utf-8")
        (package / "lib.typ").write_text('#let hello() = [bundled]\n', encoding="utf-8")
        source = tmp_path / "doc.typ"
        source.write_text('#import "@preview/mini:0.1.0": hello\n#hello()\n', encoding="utf-8")
        monkeypatch.setenv(TYPST_PACKAGES_ENV, str(tmp_path / "packages"))
        pdf = typst.compile(str(source), root=str(tmp_path), ignore_system_fonts=True, **typst_package_options())
        assert pdf.startswith(b"%PDF")


def test_build_dist_pins_the_same_fonts_and_packages_as_the_tool():
    """配布物（build-dist.js）が同梱するフォントと、Typstのパッケージの版・SHA256が、ツール本体（deps.py・テンプレート）と、
    ずれていないこと。ずれると、配布物で、CLIと違うフォント・パッケージが使われる。"""
    script = (ROOT / "viewer" / "scripts" / "build-dist.js").read_text(encoding="utf-8")
    for name, sha256 in NOTO_SANS_JP_FILES.items():
        assert f"'{name}': '{sha256}'" in script, name
    assert deps_mod.NOTO_SANS_JP_RELEASE_URL in script
    common = (ROOT / "text_compositor" / "templates" / "_common.typ").read_text(encoding="utf-8")
    used = set(re.findall(r"@preview/([a-z0-9-]+):([\d.]+)", common))
    bundled = set(re.findall(r"name: '([a-z0-9-]+)', version: '([\d.]+)'", script))
    assert used and used == bundled, (used, bundled)
