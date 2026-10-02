"""```wavedromフェンス（#299）のテスト。

仕様の検査（wavedrom_render.parse_spec）は、ブラウザなしで確かめる。描画は、偽のページで、キャッシュ・無効化・エラーの扱いを確かめ、
実ブラウザでの描画だけは、ブラウザがある環境でだけ実行する。"""
import json
import os
import re

import pytest

from text_compositor import wavedrom_render
from text_compositor.api import render_html
from text_compositor.deps import find_system_browser
from text_compositor.renderer import TypstRenderer

SPEC = {"signal": [{"name": "clk", "wave": "p...."}, {"name": "req", "wave": "0.1.0"}]}
FENCE = "```wavedrom\n" + json.dumps(SPEC) + "\n```\n"
FAKE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


class TestParseSpec:
    def test_a_signal_spec_is_returned_as_a_dict(self):
        assert wavedrom_render.parse_spec(json.dumps(SPEC)) == SPEC

    def test_a_register_spec_is_accepted(self):
        spec = {"reg": [{"name": "opcode", "bits": 7}]}
        assert wavedrom_render.parse_spec(json.dumps(spec)) == spec

    def test_broken_json_reports_the_position_and_the_strict_json_rule(self):
        with pytest.raises(wavedrom_render.SpecError, match=r"Invalid JSON: .*line 1, column 3.*strict JSON"):
            wavedrom_render.parse_spec('{ signal: [] }')   # WaveDrom本家が許す、キーに引用符のない記法は、受け付けない

    def test_a_non_object_is_rejected(self):
        with pytest.raises(wavedrom_render.SpecError, match="JSON object"):
            wavedrom_render.parse_spec("[1, 2]")

    @pytest.mark.parametrize("spec", [{}, {"head": {"text": "t"}}, {"assign": []}])
    def test_a_spec_without_a_drawable_key_is_rejected(self, spec):
        # WaveDromは、描けない入力でも、例外にせず、空の図を返す。そのため、描く前に、止める。
        with pytest.raises(wavedrom_render.SpecError, match="'signal' array.*'reg' array"):
            wavedrom_render.parse_spec(json.dumps(spec))

    @pytest.mark.parametrize("spec", [{"signal": "x"}, {"signal": []}, {"reg": {}}])
    def test_a_drawable_key_that_is_not_a_non_empty_array_is_rejected(self, spec):
        with pytest.raises(wavedrom_render.SpecError, match="non-empty array"):
            wavedrom_render.parse_spec(json.dumps(spec))


def convert_html(tmp_path, markdown, plugins=None, name="doc.md"):
    md = tmp_path / name
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False, **(plugins or {})})
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class FakeWaveDromPage:
    def __init__(self, svg=FAKE_SVG, error=None):
        self.svg, self.error, self.calls = svg, error, []

    def evaluate(self, script, args):
        self.calls.append((script, args))
        if self.error:
            raise self.error
        return self.svg


@pytest.fixture
def fake_page(monkeypatch):
    page = FakeWaveDromPage()
    monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_wavedrom_page", lambda self, *a: page)
    return page


class TestRenderWithFakePage:
    def test_a_fence_becomes_an_svg_image_and_is_cached(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert result.ok, result.diagnostics
        m = re.search(r'<img src="([^"]+\.svg)" alt="wavedrom diagram">', html)
        assert m
        assert os.path.basename(m.group(1)).startswith("wavedrom_")
        assert len(fake_page.calls) == 1
        assert fake_page.calls[0] == (wavedrom_render.RENDER_SCRIPT, [SPEC])
        second, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert second.ok and len(fake_page.calls) == 1   # キャッシュを使い、再描画しない

    def test_the_pdf_side_embeds_the_svg_with_the_requested_width(self, tmp_path, fake_page):
        renderer = TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off")
        code = renderer._render_diagram_fence("wavedrom", json.dumps(SPEC), width="50%")
        assert re.search(r'#image\("/.text-compositor/cache/wavedrom_[0-9a-f]+\.svg", width: 50%\)', code)

    def test_a_disabled_plugin_leaves_the_source_as_code(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE, plugins={"wavedrom": False})
        assert result.ok and "language-wavedrom" in html and "<img" not in html
        assert fake_page.calls == []

    def test_a_spec_that_cannot_be_drawn_fails_before_touching_the_browser(self, tmp_path, fake_page):
        result, _ = convert_html(tmp_path, "# T\n\n```wavedrom\n{}\n```\n")
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "WaveDrom diagram failed to render" and error.line == 3
        assert "'signal' array" in error.detail
        assert fake_page.calls == []

    def test_broken_json_is_an_error_with_the_fence_line(self, tmp_path, fake_page):
        result, _ = convert_html(tmp_path, "# T\n\n```wavedrom\n{oops\n```\n")
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "WaveDrom diagram failed to render" and "Invalid JSON" in error.detail

    def test_a_rendering_failure_drops_the_internal_prefix_and_stack(self, tmp_path, monkeypatch):
        page = FakeWaveDromPage(error=RuntimeError("Page.evaluate: Error: WaveDrom could not draw this spec.\n    at eval (<anonymous>:1:1)"))
        monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_wavedrom_page", lambda self, *a: page)
        result, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.detail == "WaveDrom could not draw this spec."

    def test_plugins_wavedrom_is_an_allowed_config_key(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        assert "wavedrom" in _ALLOWED_PLUGINS_KEYS

    def test_a_wavedrom_fence_works_inside_a_layout_block(self, tmp_path, fake_page):
        md = "# T\n\n::: layout-right\n本文。\n\n" + FENCE + "\n:::\n"
        result, html = convert_html(tmp_path, md)
        assert result.ok, result.diagnostics
        assert 'alt="wavedrom diagram"' in html


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return find_system_browser() is not None


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
class TestRealBrowser:
    """実ブラウザで描画する（初回は、WaveDromのJSを取得するため、ネットワークが要る）。"""

    def test_signal_and_reg_specs_render_to_svg(self, tmp_path):
        reg = {"reg": [{"name": "opcode", "bits": 7}, {"name": "rd", "bits": 5}]}
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n" + FENCE + "\n```wavedrom\n" + json.dumps(reg) + "\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        assert result.ok, result.diagnostics
        html = open(result.html_path, encoding="utf-8").read()
        svgs = re.findall(r'<img src="([^"]+\.svg)"', html)
        assert len(svgs) == 2
        for src in svgs:
            svg = open(os.path.join(os.path.dirname(result.html_path), src), encoding="utf-8").read()
            assert svg.startswith("<svg") and svg.endswith("</svg>")
        # 信号名・フィールド名が、図の中に出る
        signal, register = (open(os.path.join(os.path.dirname(result.html_path), src), encoding="utf-8").read() for src in svgs)
        assert ">clk<" in signal and ">req<" in signal and "<path" in signal
        assert ">opcode<" in register and ">rd<" in register
