"""生成した図のSVGへ、トリミング（svg_trim.py、#315）を適用する配線のテスト。

svg_trim.trim_svg()自体の正しさは test_svg_trim.py で確かめる。ここでは、
plugins.diagram_trim・フェンス属性`{trim=...}`・キャッシュキー・失敗時のフォールバックといった、
呼び出し側（renderer_diagrams.py）の配線だけを、d2を例に確かめる（他のmermaid/plantuml/
structurizrも、同じ_maybe_trim_svg/_resolve_trimを通るため、同じ配線を共有する）。"""
import subprocess

import pytest

import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor import config as config_mod
from text_compositor import svg_trim
from text_compositor.renderer import TypstRenderer

RAW_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100"></svg>'


class _Ok:
    returncode = 0
    stdout = RAW_SVG
    stderr = ""


def _renderer(tmp_path, monkeypatch, diagram_trim_enabled=False):
    monkeypatch.setattr(TypstRenderer, "_ensure_d2_bin", lambda self: "d2")
    monkeypatch.setattr(TypstRenderer, "_d2_version", lambda self: "v0")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Ok())
    return TypstRenderer(base_dir=str(tmp_path), line_mapping="off", diagram_trim_enabled=diagram_trim_enabled)


class TestConfigKey:
    def test_diagram_trim_is_an_allowed_plugins_key(self):
        # #309: 未知キーはFail-fastするため、許可リストに無いと、config.yamlに書いた瞬間に壊れる。
        errors = []
        config_mod._collect_unknown_keys({"diagram_trim": True}, config_mod._ALLOWED_PLUGINS_KEYS, "plugins", errors)
        assert errors == []


class TestParseTrimAttr:
    def test_unspecified_is_none(self):
        assert TypstRenderer(line_mapping="off")._parse_trim_attr("") is None
        assert TypstRenderer(line_mapping="off")._parse_trim_attr("width=50%") is None

    def test_true_and_false(self):
        renderer = TypstRenderer(line_mapping="off")
        assert renderer._parse_trim_attr("trim=true") is True
        assert renderer._parse_trim_attr("trim=false") is False
        assert renderer._parse_trim_attr("width=50% trim=true") is True


class TestResolveTrim:
    def test_fence_override_wins_over_the_project_default(self):
        renderer = TypstRenderer(line_mapping="off", diagram_trim_enabled=True)
        assert renderer._resolve_trim(None) is True
        assert renderer._resolve_trim(False) is False
        renderer2 = TypstRenderer(line_mapping="off", diagram_trim_enabled=False)
        assert renderer2._resolve_trim(None) is False
        assert renderer2._resolve_trim(True) is True


class TestD2TrimWiring:
    def test_trim_is_applied_when_enabled(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=True)
        calls = []

        def fake_trim(svg, margin=svg_trim.DEFAULT_MARGIN):
            calls.append(svg)
            return "<svg trimmed/>"
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg", fake_trim)

        svg_path = renderer._d2_svg_path("a -> b")
        assert calls == [RAW_SVG]
        with open(svg_path, encoding="utf-8") as f:
            assert f.read() == "<svg trimmed/>"

    def test_trim_is_skipped_when_disabled(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=False)
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg",
                             lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))

        svg_path = renderer._d2_svg_path("a -> b")
        with open(svg_path, encoding="utf-8") as f:
            assert f.read() == RAW_SVG

    def test_fence_attribute_overrides_the_project_default(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=False)
        calls = []
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg", lambda svg, margin=svg_trim.DEFAULT_MARGIN: calls.append(svg) or "<svg trimmed/>")

        renderer._d2_svg_path("a -> b", trim=True)
        assert calls == [RAW_SVG]

    def test_enabling_trim_changes_the_cache_path(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=False)
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg", lambda svg, margin=svg_trim.DEFAULT_MARGIN: "<svg trimmed/>")

        path_without_trim = renderer._d2_svg_path("a -> b", trim=False)
        path_with_trim = renderer._d2_svg_path("a -> b", trim=True)
        assert path_without_trim != path_with_trim

    def test_a_trim_error_falls_back_to_the_untrimmed_svg(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=True)

        def failing_trim(svg, margin=svg_trim.DEFAULT_MARGIN):
            raise svg_trim.TrimError("boom")
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg", failing_trim)

        svg_path = renderer._d2_svg_path("a -> b")
        with open(svg_path, encoding="utf-8") as f:
            assert f.read() == RAW_SVG

    def test_missing_dependency_fails_fast(self, tmp_path, monkeypatch):
        renderer = _renderer(tmp_path, monkeypatch, diagram_trim_enabled=True)

        def failing_trim(svg, margin=svg_trim.DEFAULT_MARGIN):
            raise ImportError("no module named resvg_py")
        monkeypatch.setattr(diagrams_mod.svg_trim, "trim_svg", failing_trim)

        with pytest.raises(SystemExit):
            renderer._d2_svg_path("a -> b")
