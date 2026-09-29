"""```vega-lite・```vegaフェンス（#211）のテスト。

仕様の検査（vega_render.parse_spec）は、ブラウザなしで確かめる。描画は、偽のページで、キャッシュ・無効化・エラーの扱いを確かめ、
実ブラウザでの描画だけは、ブラウザがある環境でだけ実行する。"""
import json
import os
import re

import pytest

from text_compositor import host_renderers, vega_render
from text_compositor.api import Session, render_html
from text_compositor.deps import find_system_browser
from text_compositor.renderer import TypstRenderer

SPEC = {
    "data": {"values": [{"a": "x", "b": 1}, {"a": "y", "b": 2}]},
    "mark": "bar",
    "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "b", "type": "quantitative"}},
}
FENCE = "```vega-lite\n" + json.dumps(SPEC) + "\n```\n"
FAKE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


class TestParseSpec:
    def test_a_valid_spec_is_returned_as_a_dict(self):
        assert vega_render.parse_spec(json.dumps(SPEC)) == SPEC

    def test_broken_json_reports_the_position(self):
        with pytest.raises(vega_render.SpecError, match=r"Invalid JSON: .*line 1, column 6"):
            vega_render.parse_spec('{"a":')

    def test_a_non_object_is_rejected(self):
        with pytest.raises(vega_render.SpecError, match="JSON object"):
            vega_render.parse_spec("[1, 2]")

    @pytest.mark.parametrize("spec,where", [
        ({"data": {"url": "sales.csv"}, "mark": "bar"}, "$.data.url"),
        ({"data": {"url": "http://example.com/x.csv"}}, "$.data.url"),
        ({"layer": [{"mark": "bar"}, {"data": {"url": "x.json"}}]}, "$.layer[1].data.url"),
        ({"data": [{"name": "t", "url": "x.csv"}]}, "$.data[0].url"),
        ({"layer": [{"mark": {"type": "image", "url": "http://example.com/a.png"}}]}, "$.layer[0].mark.url"),
    ])
    def test_external_references_are_rejected(self, spec, where):
        with pytest.raises(vega_render.SpecError) as e:
            vega_render.parse_spec(json.dumps(spec))
        assert "External resources are not supported" in str(e.value) and where in str(e.value)

    def test_a_column_named_url_inside_inline_data_is_not_a_reference(self):
        spec = {"data": {"values": [{"url": "http://example.com", "n": 1}]}, "mark": "bar"}
        assert vega_render.parse_spec(json.dumps(spec)) == spec
        datasets = {"datasets": {"d": [{"url": "x"}]}, "mark": "bar"}
        assert vega_render.parse_spec(json.dumps(datasets)) == datasets


def convert_html(tmp_path, markdown, plugins=None, name="doc.md"):
    md = tmp_path / name
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False, **(plugins or {})})
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class FakeVegaPage:
    def __init__(self, svg=FAKE_SVG, error=None):
        self.svg, self.error, self.calls = svg, error, []

    def evaluate(self, script, args):
        self.calls.append((script, args))
        if self.error:
            raise self.error
        return self.svg


@pytest.fixture
def fake_page(monkeypatch):
    page = FakeVegaPage()
    monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_vega_page", lambda self, *a: page)
    return page


class TestRenderWithFakePage:
    def test_a_fence_becomes_an_svg_image_and_is_cached(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert result.ok, result.diagnostics
        m = re.search(r'<img src="([^"]+\.svg)" alt="vega-lite diagram">', html)
        assert m
        assert os.path.basename(m.group(1)).startswith("vega-lite_")
        assert len(fake_page.calls) == 1
        assert fake_page.calls[0][1] == ["vega-lite", SPEC]
        second, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert second.ok and len(fake_page.calls) == 1   # キャッシュを使い、再描画しない

    def test_vega_and_vega_lite_do_not_share_a_cache_entry(self, tmp_path, fake_page):
        renderer = TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off")
        a = renderer._vega_svg_path("vega-lite", json.dumps(SPEC))
        b = renderer._vega_svg_path("vega", json.dumps(SPEC))
        assert a != b

    def test_the_pdf_side_embeds_the_svg_with_the_requested_width(self, tmp_path, fake_page):
        renderer = TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off")
        code = renderer._render_diagram_fence("vega-lite", json.dumps(SPEC), width="50%")
        assert re.search(r'#image\("/.text-compositor/cache/vega-lite_[0-9a-f]+\.svg", width: 50%\)', code)

    def test_a_disabled_plugin_leaves_the_source_as_code(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE, plugins={"vega": False})
        assert result.ok and "language-vega-lite" in html and "<img" not in html
        assert fake_page.calls == []

    def test_an_external_reference_fails_before_touching_the_browser(self, tmp_path, fake_page):
        bad = json.dumps({"data": {"url": "sales.csv"}, "mark": "bar"})
        result, _ = convert_html(tmp_path, "# T\n\n```vega-lite\n" + bad + "\n```\n")
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "Vega-Lite diagram failed to render" and error.line == 3
        assert "External resources are not supported" in error.detail and "$.data.url" in error.detail
        assert fake_page.calls == []

    def test_broken_json_is_an_error_with_the_fence_line(self, tmp_path, fake_page):
        result, _ = convert_html(tmp_path, "# T\n\n```vega\n{oops\n```\n")
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "Vega diagram failed to render" and "Invalid JSON" in error.detail

    def test_a_rendering_failure_drops_the_internal_prefix_and_stack(self, tmp_path, monkeypatch):
        page = FakeVegaPage(error=RuntimeError("Page.evaluate: Error: Unrecognized function: nosuchfn\n    at eval (<anonymous>:1:1)"))
        monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_vega_page", lambda self, *a: page)
        result, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.detail == "Unrecognized function: nosuchfn"

    def test_a_host_renderer_is_used_instead_of_the_browser(self, tmp_path, monkeypatch):
        calls = []

        def host(diagram_id, lang, spec, script, js):
            calls.append((lang, spec, script, js))
            return FAKE_SVG
        monkeypatch.setattr(host_renderers, "_vega_host_renderer", host)
        monkeypatch.setattr("text_compositor.renderer_diagrams.ensure_vega_js", lambda: ("v.js", "vl.js"))
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE)   # ensure_vega_pageは、呼ばれない（偽のページも、使わない）
        assert result.ok, result.diagnostics
        assert calls == [("vega-lite", SPEC, vega_render.RENDER_SCRIPT, {"vega": "v.js", "vega_lite": "vl.js"})]

    def test_the_bundled_js_dir_env_is_used_without_downloading(self, tmp_path, monkeypatch):
        from text_compositor import deps
        (tmp_path / "vega.min.js").write_text("/* v */", encoding="utf-8")
        (tmp_path / "vega-lite.min.js").write_text("/* vl */", encoding="utf-8")
        monkeypatch.setenv(deps.VEGA_JS_DIR_ENV, str(tmp_path))
        monkeypatch.setattr(deps, "_download", lambda *a, **k: pytest.fail("must not download"))
        assert deps.ensure_vega_js() == (str(tmp_path / "vega.min.js"), str(tmp_path / "vega-lite.min.js"))

    def test_plugins_vega_is_an_allowed_config_key(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        assert "vega" in _ALLOWED_PLUGINS_KEYS

    def test_a_vega_fence_works_inside_a_layout_block(self, tmp_path, fake_page):
        md = "# T\n\n::: layout-right\n本文。\n\n" + FENCE + "\n:::\n"
        result, html = convert_html(tmp_path, md)
        assert result.ok, result.diagnostics
        assert 'alt="vega-lite diagram"' in html


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return find_system_browser() is not None


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
class TestRealBrowser:
    """実ブラウザで描画する（初回は、vega・vega-liteのJSを取得するため、ネットワークが要る）。"""

    def test_vega_lite_and_vega_render_to_svg(self, tmp_path):
        vega_spec = {"width": 50, "height": 50,
                     "marks": [{"type": "rect", "encode": {"enter": {"width": {"value": 20}, "height": {"value": 20}}}}]}
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n" + FENCE + "\n```vega\n" + json.dumps(vega_spec) + "\n```\n", encoding="utf-8")
        with Session() as session:
            result = session.render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
            assert result.ok, result.diagnostics
            html = open(result.html_path, encoding="utf-8").read()
            svgs = re.findall(r'<img src="([^"]+\.svg)"', html)
            assert len(svgs) == 2
            for src in svgs:
                assert "<svg" in open(os.path.join(os.path.dirname(result.html_path), src), encoding="utf-8").read()

    def test_a_faceted_log_scale_chart_renders(self, tmp_path):
        """Mermaidのxychartでは描けない、ファセット分割と対数軸（#211の完了条件）。"""
        spec = {
            "data": {"values": [{"region": r, "month": m, "sales": m * 10 ** i}
                                for i, r in enumerate(["east", "west"]) for m in (1, 2, 3)]},
            "mark": "line",
            "encoding": {"x": {"field": "month", "type": "quantitative"},
                         "y": {"field": "sales", "type": "quantitative", "scale": {"type": "log"}},
                         "facet": {"field": "region", "type": "nominal"}},
        }
        md = tmp_path / "doc.md"
        md.write_text("```vega-lite\n" + json.dumps(spec) + "\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        assert result.ok, result.diagnostics

    def test_a_spec_that_bypasses_the_check_still_cannot_reach_the_network(self, tmp_path):
        """検査（parse_spec）をすり抜けた経路があっても、描画側のloaderが止めて、エラーにする。"""
        from text_compositor.mermaid import MermaidBrowser
        browser = MermaidBrowser()
        try:
            page = browser.ensure_vega_page(True, False)
            spec = {"data": {"url": "http://example.invalid/x.csv"}, "mark": "bar",
                    "encoding": {"x": {"field": "a", "type": "nominal"}}}
            with pytest.raises(Exception, match="External resources are blocked"):
                page.evaluate(vega_render.RENDER_SCRIPT, ["vega-lite", spec])
        finally:
            browser.close()
