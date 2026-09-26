"""Obunzuが配布物に同梱したJava・plantuml.jar・D2・structurizr-cliを、システムの検出・自動取得より
優先して使う仕組み（#290）のテスト。ネットワーク・実際のJava実行は使わない。"""
import os
from pathlib import Path

import pytest

import text_compositor.deps as deps_mod
import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor.deps import (
    BUNDLED_D2_BIN_ENV, BUNDLED_JAVA_BIN_ENV, BUNDLED_PLANTUML_JAR_ENV, BUNDLED_STRUCTURIZR_CLI_LIB_ENV,
    bundled_d2_bin, bundled_java_bin, bundled_plantuml_jar, bundled_structurizr_cli_lib,
)
from text_compositor.renderer import TypstRenderer

ROOT = Path(__file__).resolve().parent.parent


class TestBundledPathHelpers:
    @pytest.mark.parametrize("env,helper,make", [
        (BUNDLED_JAVA_BIN_ENV, bundled_java_bin, "file"),
        (BUNDLED_PLANTUML_JAR_ENV, bundled_plantuml_jar, "file"),
        (BUNDLED_D2_BIN_ENV, bundled_d2_bin, "file"),
        (BUNDLED_STRUCTURIZR_CLI_LIB_ENV, bundled_structurizr_cli_lib, "dir"),
    ])
    def test_returns_the_path_when_it_exists(self, monkeypatch, tmp_path, env, helper, make):
        target = tmp_path / "thing"
        if make == "file":
            target.write_bytes(b"x")
        else:
            target.mkdir()
        monkeypatch.setenv(env, str(target))
        assert helper() == str(target)

    @pytest.mark.parametrize("env,helper", [
        (BUNDLED_JAVA_BIN_ENV, bundled_java_bin),
        (BUNDLED_PLANTUML_JAR_ENV, bundled_plantuml_jar),
        (BUNDLED_D2_BIN_ENV, bundled_d2_bin),
        (BUNDLED_STRUCTURIZR_CLI_LIB_ENV, bundled_structurizr_cli_lib),
    ])
    def test_missing_path_is_ignored(self, monkeypatch, tmp_path, env, helper):
        monkeypatch.setenv(env, str(tmp_path / "nope"))
        assert helper() is None

    @pytest.mark.parametrize("env,helper", [
        (BUNDLED_JAVA_BIN_ENV, bundled_java_bin),
        (BUNDLED_PLANTUML_JAR_ENV, bundled_plantuml_jar),
        (BUNDLED_D2_BIN_ENV, bundled_d2_bin),
        (BUNDLED_STRUCTURIZR_CLI_LIB_ENV, bundled_structurizr_cli_lib),
    ])
    def test_no_variable_returns_none(self, monkeypatch, env, helper):
        monkeypatch.delenv(env, raising=False)
        assert helper() is None


class TestBundledToolsTakePriority:
    """`_ensure_*_tools`が、同梱物をシステムの検出・自動取得より先に使うこと。いずれの取得関数
    （find_system_java・ensure_temurin_jre等）も、呼ばれたら失敗させて、実際には触れないことを確認する。"""

    def _boom(self, *a, **k):
        pytest.fail("must not fall back past the bundled path")

    def test_plantuml_prefers_bundled_java_and_jar(self, monkeypatch, tmp_path):
        java = tmp_path / "java.exe"
        java.write_bytes(b"x")
        jar = tmp_path / "plantuml.jar"
        jar.write_bytes(b"x")
        monkeypatch.setenv(BUNDLED_JAVA_BIN_ENV, str(java))
        monkeypatch.setenv(BUNDLED_PLANTUML_JAR_ENV, str(jar))
        monkeypatch.setattr(diagrams_mod, "find_system_java", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_temurin_jre", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", self._boom)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._ensure_plantuml_tools() == (str(java), str(jar))

    def test_structurizr_prefers_bundled_java_lib_and_jar(self, monkeypatch, tmp_path):
        java = tmp_path / "java.exe"
        java.write_bytes(b"x")
        lib = tmp_path / "lib"
        lib.mkdir()
        jar = tmp_path / "plantuml.jar"
        jar.write_bytes(b"x")
        monkeypatch.setenv(BUNDLED_JAVA_BIN_ENV, str(java))
        monkeypatch.setenv(BUNDLED_STRUCTURIZR_CLI_LIB_ENV, str(lib))
        monkeypatch.setenv(BUNDLED_PLANTUML_JAR_ENV, str(jar))
        monkeypatch.setattr(diagrams_mod, "find_system_java", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_temurin_jre", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_structurizr_cli", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", self._boom)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        assert renderer._ensure_structurizr_tools() == (str(java), str(lib), str(jar))

    def test_d2_prefers_bundled_binary(self, monkeypatch, tmp_path):
        d2 = tmp_path / "d2.exe"
        d2.write_bytes(b"x")
        monkeypatch.setenv(BUNDLED_D2_BIN_ENV, str(d2))
        monkeypatch.setattr(diagrams_mod, "find_system_d2", self._boom)
        monkeypatch.setattr(diagrams_mod, "ensure_d2_binary", self._boom)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._ensure_d2_bin() == str(d2)

    def test_d2_version_uses_the_bundled_binarys_own_version(self, monkeypatch, tmp_path):
        d2 = tmp_path / "d2.exe"
        d2.write_bytes(b"x")
        monkeypatch.setenv(BUNDLED_D2_BIN_ENV, str(d2))
        monkeypatch.setattr(diagrams_mod, "find_system_d2", self._boom)
        monkeypatch.setattr(diagrams_mod, "_system_d2_version", lambda path: f"bundled@{path}")

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._d2_version() == f"bundled@{d2}"

    def test_without_the_variables_the_behavior_is_unchanged(self, monkeypatch, tmp_path):
        for env in (BUNDLED_JAVA_BIN_ENV, BUNDLED_PLANTUML_JAR_ENV, BUNDLED_D2_BIN_ENV, BUNDLED_STRUCTURIZR_CLI_LIB_ENV):
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setattr(diagrams_mod, "find_system_d2", lambda: None)
        monkeypatch.setattr(diagrams_mod, "ensure_d2_binary", lambda: str(tmp_path / "downloaded-d2"))

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._ensure_d2_bin() == str(tmp_path / "downloaded-d2")


def test_build_dist_pins_the_same_java_plantuml_d2_structurizr_and_mermaid_as_the_tool():
    """配布物（build-dist.js）が同梱するJRE・plantuml.jar・D2・structurizr-cli・mermaid.min.jsのURL・SHA256が、
    ツール本体（deps.py）と、ずれていないこと。ずれると、配布物で、CLIと違う版・改ざんされたファイルが使われる。"""
    script = (ROOT / "viewer" / "scripts" / "build-dist.js").read_text(encoding="utf-8")

    win_x64_jre = deps_mod.TEMURIN_JRE_ASSETS[("win32", "x86_64")]
    assert deps_mod.TEMURIN_JRE_BASE_URL + win_x64_jre[0] in script
    assert win_x64_jre[1] in script

    assert deps_mod.PLANTUML_JAR_URL in script
    assert deps_mod.PLANTUML_JAR_SHA256 in script

    win_x64_d2 = deps_mod.D2_ASSETS[("win32", "x86_64")]
    assert deps_mod.D2_BASE_URL + win_x64_d2[0] in script
    assert win_x64_d2[1] in script

    assert deps_mod.STRUCTURIZR_CLI_URL in script
    assert deps_mod.STRUCTURIZR_CLI_SHA256 in script

    assert deps_mod.MERMAID_JS_URL in script
    assert deps_mod.MERMAID_JS_SHA256 in script
