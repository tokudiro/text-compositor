"""wingetのマニフェストの生成（packaging/winget/make_manifest.py、#334）のテスト。外部ツールは使わない。"""
import importlib.util
import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SPEC = importlib.util.spec_from_file_location("make_manifest", os.path.join(ROOT, "packaging", "winget", "make_manifest.py"))
mm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mm)

SHA = "b2b1d8df8720bb892370e1270a0762d7e0dc5f5c6801c386ac07d09bc9bab4b4"


def installer(version="0.4.6", sha=SHA):
    return mm.render(version, sha)[f"{mm.PACKAGE_ID}.installer.yaml"]


class TestRender:
    def test_three_files_with_the_same_identifier_and_version(self):
        files = mm.render("0.4.6", SHA)
        assert sorted(files) == [f"{mm.PACKAGE_ID}.installer.yaml", f"{mm.PACKAGE_ID}.locale.en-US.yaml", f"{mm.PACKAGE_ID}.yaml"]
        for text in files.values():
            assert f"PackageIdentifier: {mm.PACKAGE_ID}\n" in text and "PackageVersion: 0.4.6\n" in text

    def test_the_installer_is_a_portable_zip_of_the_release_asset(self):
        text = installer()
        assert "InstallerType: zip\n" in text and "NestedInstallerType: portable\n" in text
        assert ("InstallerUrl: https://github.com/tokudiro/text-compositor/releases/download/v0.4.6/"
                "Obunzu-Markdown-Viewer-0.4.6-win-x64.zip\n") in text
        assert "RelativeFilePath: Obunzu-Markdown-Viewer-0.4.6-win-x64\\obunzu-markdown-viewer.exe\n" in text
        assert "PortableCommandAlias: obunzu\n" in text

    def test_the_hash_is_upper_case(self):
        assert f"InstallerSha256: {SHA.upper()}\n" in installer()

    @pytest.mark.parametrize("bad", ["v0.4.6", "0.4", "0.4.6-rc1", ""])
    def test_a_bad_version_is_refused(self, bad):
        with pytest.raises(ValueError):
            mm.render(bad, SHA)

    @pytest.mark.parametrize("bad", ["", "abc", "z" * 64, SHA[:-1]])
    def test_a_bad_hash_is_refused(self, bad):
        with pytest.raises(ValueError):
            mm.render("0.4.6", bad)

    def test_files_use_lf_and_end_with_a_newline(self):
        for text in mm.render("0.4.6", SHA).values():
            assert text.endswith("\n") and "\r" not in text


class TestConsistencyWithTheBuild:
    def test_release_name_matches_the_build_script(self):
        script = open(os.path.join(ROOT, "viewer", "scripts", "build-dist.js"), encoding="utf-8").read()
        assert "`Obunzu-Markdown-Viewer-${pkg.version}-win-x64`" in script
        assert mm.release_name("1.2.3") == "Obunzu-Markdown-Viewer-1.2.3-win-x64"

    def test_the_executable_name_matches_the_packager_options(self):
        script = open(os.path.join(ROOT, "viewer", "scripts", "build-dist.js"), encoding="utf-8").read()
        assert "obunzu-markdown-viewer" in script and mm.EXE_NAME == "obunzu-markdown-viewer.exe"

    def test_the_current_viewer_version_renders(self):
        version = json.load(open(os.path.join(ROOT, "viewer", "package.json"), encoding="utf-8"))["version"]
        assert re.search(rf"v{re.escape(version)}/Obunzu-Markdown-Viewer-{re.escape(version)}-win-x64\.zip", installer(version))


class TestMain:
    def test_writes_the_winget_pkgs_layout(self, tmp_path):
        assert mm.main(["--version", "0.4.6", "--sha256", SHA, "--out", str(tmp_path)]) == 0
        folder = tmp_path / "manifests" / "t" / "tokudiro" / "ObunzuMarkdownViewer" / "0.4.6"
        assert sorted(p.name for p in folder.iterdir()) == sorted(mm.render("0.4.6", SHA))

    def test_the_hash_can_be_computed_from_a_zip(self, tmp_path):
        z = tmp_path / "x.zip"
        z.write_bytes(b"hello")
        mm.main(["--version", "0.4.6", "--zip", str(z), "--out", str(tmp_path / "out")])
        text = next((tmp_path / "out").rglob("*.installer.yaml")).read_text(encoding="utf-8")
        assert "InstallerSha256: 2CF24DBA5FB0A30E26E83B2AC5B9E29E1B161E5C1FA7425E73043362938B9824\n" in text
