"""```bytefieldフェンス（#300）のテスト。

入力の検査（bytefield_render.parse_spec）は、ブラウザなしで確かめる。描画は、偽のページで、キャッシュ・無効化・エラーの扱いを確かめ、
実ブラウザでの描画だけは、ブラウザがある環境でだけ実行する。"""
import os
import re

import pytest

from text_compositor import bytefield_render, host_renderers
from text_compositor.api import render_html
from text_compositor.deps import find_system_browser
from text_compositor.renderer import TypstRenderer

SOURCE = '(draw-column-headers)\n(draw-box "Source Port" {:span 16})\n(draw-box "Destination Port" {:span 16})'
FENCE = "```bytefield\n" + SOURCE + "\n```\n"
FAKE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


class TestParseSpec:
    def test_a_source_is_returned_as_is(self):
        assert bytefield_render.parse_spec(SOURCE) == SOURCE

    @pytest.mark.parametrize("code", ["", "   \n  "])
    def test_an_empty_source_is_rejected(self, code):
        # Bytefield-svgは、空の入力を、エラーにせず、空の図にする。そのため、描く前に、止める。
        with pytest.raises(bytefield_render.SpecError, match="empty"):
            bytefield_render.parse_spec(code)


def convert_html(tmp_path, markdown, plugins=None, name="doc.md"):
    md = tmp_path / name
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False, **(plugins or {})})
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class FakeBytefieldPage:
    def __init__(self, svg=FAKE_SVG, error=None):
        self.svg, self.error, self.calls = svg, error, []

    def evaluate(self, script, args):
        self.calls.append((script, args))
        if self.error:
            raise self.error
        return self.svg


@pytest.fixture
def fake_page(monkeypatch):
    page = FakeBytefieldPage()
    monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_bytefield_page", lambda self, *a: page)
    return page


class TestRenderWithFakePage:
    def test_a_fence_becomes_an_svg_image_and_is_cached(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert result.ok, result.diagnostics
        m = re.search(r'<img src="([^"]+\.svg)" alt="bytefield diagram">', html)
        assert m
        assert os.path.basename(m.group(1)).startswith("bytefield_")
        assert len(fake_page.calls) == 1
        assert fake_page.calls[0] == (bytefield_render.RENDER_SCRIPT, [SOURCE + chr(10)])   # フェンスの中身は、末尾の改行つき
        second, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        assert second.ok and len(fake_page.calls) == 1   # キャッシュを使い、再描画しない

    def test_the_pdf_side_embeds_the_svg_with_the_requested_width(self, tmp_path, fake_page):
        renderer = TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off")
        code = renderer._render_diagram_fence("bytefield", SOURCE, width="50%")
        assert re.search(r'#image\("/.text-compositor/cache/bytefield_[0-9a-f]+\.svg", width: 50%\)', code)

    def test_a_disabled_plugin_leaves_the_source_as_code(self, tmp_path, fake_page):
        result, html = convert_html(tmp_path, "# T\n\n" + FENCE, plugins={"bytefield": False})
        assert result.ok and "language-bytefield" in html and "<img" not in html
        assert fake_page.calls == []

    def test_an_empty_fence_fails_before_touching_the_browser(self, tmp_path, fake_page):
        result, _ = convert_html(tmp_path, "# T\n\n```bytefield\n \n```\n")
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "Bytefield diagram failed to render" and error.line == 3
        assert "empty" in error.detail
        assert fake_page.calls == []

    def test_a_rendering_failure_keeps_the_message_with_the_position(self, tmp_path, monkeypatch):
        page = FakeBytefieldPage(error=RuntimeError(
            "Page.evaluate: Error: draw-box called with span larger than remaining columns in row [at line 2, column 1]\n    at eval (<anonymous>:1:1)"))
        monkeypatch.setattr("text_compositor.mermaid.MermaidBrowser.ensure_bytefield_page", lambda self, *a: page)
        result, _ = convert_html(tmp_path, "# T\n\n" + FENCE)
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.detail == "draw-box called with span larger than remaining columns in row [at line 2, column 1]"

    def test_the_bundled_js_dir_env_is_used_without_downloading(self, tmp_path, monkeypatch):
        from text_compositor import deps
        (tmp_path / "lib.js").write_text("/* b */", encoding="utf-8")
        monkeypatch.setenv(deps.BYTEFIELD_JS_DIR_ENV, str(tmp_path))
        monkeypatch.setattr(deps, "_download", lambda *a, **k: pytest.fail("must not download"))
        assert deps.ensure_bytefield_js() == str(tmp_path / "lib.js")

    def test_a_host_renderer_is_used_instead_of_the_browser(self, tmp_path, monkeypatch):
        calls = []

        def host(diagram_id, source, script, js):
            calls.append((diagram_id, source, script, js))
            return FAKE_SVG
        monkeypatch.setattr(host_renderers, "_bytefield_host_renderer", host)
        monkeypatch.setattr("text_compositor.renderer_diagrams.ensure_bytefield_js", lambda: "lib.js")
        result, _ = convert_html(tmp_path, "# T\n\n" + FENCE)   # ensure_bytefield_pageは、呼ばれない
        assert result.ok, result.diagnostics
        assert len(calls) == 1 and calls[0][1:] == (SOURCE + chr(10), bytefield_render.RENDER_SCRIPT, {"bytefield": "lib.js"})
        assert calls[0][0].startswith("bytefield-")

    def test_plugins_bytefield_is_an_allowed_config_key(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        assert "bytefield" in _ALLOWED_PLUGINS_KEYS

    def test_a_bytefield_fence_works_inside_a_layout_block(self, tmp_path, fake_page):
        md = "# T\n\n::: layout-right\n本文。\n\n" + FENCE + "\n:::\n"
        result, html = convert_html(tmp_path, md)
        assert result.ok, result.diagnostics
        assert 'alt="bytefield diagram"' in html


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return find_system_browser() is not None


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
class TestRealBrowser:
    """実ブラウザで描画する（初回は、Bytefield-svgのJSを取得するため、ネットワークが要る）。"""

    def test_a_packet_diagram_renders_to_svg(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n```bytefield\n(def boxes-per-row 32)\n(draw-box \"Source Port\" {:span 16})\n"
                      "(draw-box \"Destination Port\" {:span 16})\n(draw-gap \"Data\")\n(draw-bottom)\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        assert result.ok, result.diagnostics
        html = open(result.html_path, encoding="utf-8").read()
        src = re.search(r'<img src="([^"]+\.svg)"', html).group(1)
        svg = open(os.path.join(os.path.dirname(result.html_path), src), encoding="utf-8").read()
        assert "<svg" in svg and "Source Port" in svg and "Destination Port" in svg

    def test_a_drawing_error_is_reported_with_the_position(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n```bytefield\n(draw-box \"A\" {:span 99})\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert "span larger than remaining columns" in error.detail and "[at line 1, column 1]" in error.detail

    def test_javascript_interop_is_not_available_to_the_source(self, tmp_path):
        """記述から、ブラウザの機能（通信など）には触れない。インタプリタが、`js/`の記号を解決しない。"""
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n```bytefield\n(js/fetch \"http://example.invalid/\")\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert "Could not resolve symbol: js/fetch" in error.detail
