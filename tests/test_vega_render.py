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
        bad = json.dumps({"layer": [{"mark": {"type": "image", "url": "http://example.com/a.png"}}]})
        result, _ = convert_html(tmp_path, "# T\n\n```vega-lite\n" + bad + "\n```\n")
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "Vega-Lite diagram failed to render" and error.line == 3
        assert "External resources are not supported" in error.detail and "$.layer[0].mark.url" in error.detail
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


CSV = "month,sales\n1,10\n2,20\n"


def data_spec(url, **extra):
    return json.dumps({"data": {"url": url, **extra}, "mark": "bar",
                       "encoding": {"x": {"field": "month", "type": "quantitative"}, "y": {"field": "sales", "type": "quantitative"}}})


class TestInlineDataFiles:
    """データ定義の`url`を、ファイルの中身へ置き換える処理（#350）。ファイルを読む関数は、偽物にする。"""

    @staticmethod
    def load(url):
        return f"<{url}>", "csv"

    def test_the_url_becomes_values_with_the_detected_format(self):
        spec = json.loads(data_spec("d/sales.csv"))
        assert vega_render.inline_data_files(spec, self.load) == 1
        assert spec["data"] == {"values": "<d/sales.csv>", "format": {"type": "csv"}}

    def test_an_explicit_format_type_wins_and_other_format_keys_are_kept(self):
        spec = json.loads(data_spec("d/x.csv", format={"type": "tsv", "parse": {"month": "number"}}))
        vega_render.inline_data_files(spec, self.load)
        assert spec["data"]["format"] == {"type": "tsv", "parse": {"month": "number"}}

    @pytest.mark.parametrize("spec,count", [
        ({"layer": [{"data": {"url": "a.csv"}}, {"data": {"url": "b.csv"}}]}, 2),
        ({"data": [{"name": "t", "url": "a.csv"}, {"name": "u", "values": []}]}, 1),
        ({"transform": [{"lookup": "k", "from": {"data": {"url": "a.csv"}, "key": "k"}}]}, 1),
        ({"marks": [{"type": "group", "data": [{"name": "t", "url": "a.csv"}]}]}, 1),
    ])
    def test_data_definitions_are_found_wherever_the_spec_nests_them(self, spec, count):
        assert vega_render.inline_data_files(spec, self.load) == count
        assert vega_render.find_external_reference(spec) is None

    def test_a_url_outside_a_data_definition_is_left_for_the_check_to_reject(self):
        spec = {"layer": [{"mark": {"type": "image", "url": "a.png"}}]}
        assert vega_render.inline_data_files(spec, self.load) == 0
        with pytest.raises(vega_render.SpecError, match="External resources are not supported"):
            vega_render.parse_spec(json.dumps(spec), load=self.load)

    @pytest.mark.parametrize("data,message", [
        ({"url": 3}, "must be a file path"),
        ({"url": "a.csv", "values": []}, "both 'url' and 'values'"),
        ({"url": "a.csv", "format": "csv"}, "'format'"),
    ])
    def test_malformed_definitions_are_rejected(self, data, message):
        with pytest.raises(vega_render.SpecError, match=message):
            vega_render.parse_spec(json.dumps({"data": data}), load=self.load)


class TestDataFiles:
    """ローカルのデータファイルの参照（#350）。読める範囲（プロジェクトのルートの中）と、キャッシュ・更新の検知を確かめる。"""

    @pytest.fixture
    def project(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "sales.csv").write_bytes(CSV.encode("utf-8"))   # 改行を変換しない
        return tmp_path

    def render(self, project, url, name="doc.md", **extra):
        md = project / name
        md.write_text("# T\n\n```vega-lite\n" + data_spec(url, **extra) + "\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
        return result

    def error_detail(self, result):
        assert not result.ok
        return [d for d in result.diagnostics if d.severity == "error"][0].detail

    def test_a_csv_file_is_inlined_and_sent_to_the_renderer(self, project, fake_page):
        result = self.render(project, "data/sales.csv")
        assert result.ok, result.diagnostics
        sent = fake_page.calls[0][1][1]
        assert sent["data"] == {"values": CSV, "format": {"type": "csv"}}
        assert str(project / "data" / "sales.csv") in result.dependencies   # 保存し直すと、Viewerが更新する

    def test_a_json_and_a_tsv_file_get_their_own_format(self, project, fake_page):
        (project / "data" / "a.json").write_text('[{"month": 1, "sales": 1}]', encoding="utf-8")
        (project / "data" / "b.tsv").write_text("month" + chr(9) + "sales" + chr(10) + "1" + chr(9) + "2" + chr(10), encoding="utf-8")
        assert self.render(project, "data/a.json").ok and self.render(project, "data/b.tsv").ok
        assert [c[1][1]["data"]["format"]["type"] for c in fake_page.calls] == ["json", "tsv"]

    def test_changing_the_file_redraws_and_leaving_it_reuses_the_cache(self, project, fake_page):
        assert self.render(project, "data/sales.csv").ok
        assert self.render(project, "data/sales.csv").ok
        assert len(fake_page.calls) == 1
        (project / "data" / "sales.csv").write_text(CSV + "3,30" + chr(10), encoding="utf-8")
        assert self.render(project, "data/sales.csv").ok
        assert len(fake_page.calls) == 2

    @pytest.mark.parametrize("url,message", [
        ("http://example.com/x.csv", "External URLs are not supported"),
        ("https://example.com/x.csv", "External URLs are not supported"),
        ("file:///etc/x.csv", "External URLs are not supported"),
        ("//example.com/x.csv", "External URLs are not supported"),
        ("/etc/x.csv", "Absolute paths are not allowed"),
        ("C:/x.csv", "Absolute paths are not allowed"),
        ("../outside.csv", "outside the project"),
        ("data/notes.txt", "Unsupported data file type"),
        ("data/missing.csv", "Data file not found"),
    ])
    def test_unsafe_or_unusable_references_fail_before_touching_the_browser(self, project, fake_page, url, message):
        assert message in self.error_detail(self.render(project, url))
        assert fake_page.calls == []

    def test_the_error_points_at_the_fence_line(self, project, fake_page):
        result = self.render(project, "nope/x.csv")
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.line == 3 and error.message == "Vega-Lite diagram failed to render"

    def test_a_file_that_is_too_large_or_not_utf8_is_rejected(self, project, fake_page, monkeypatch):
        (project / "data" / "sjis.csv").write_bytes("月,売上".encode("cp932"))
        assert "not UTF-8" in self.error_detail(self.render(project, "data/sjis.csv"))
        monkeypatch.setattr(vega_render, "MAX_DATA_BYTES", 4)
        assert "too large" in self.error_detail(self.render(project, "data/sales.csv"))
        assert fake_page.calls == []

    def test_a_symlink_pointing_outside_the_project_is_rejected(self, project, tmp_path_factory, fake_page):
        outside = tmp_path_factory.mktemp("outside") / "secret.csv"
        outside.write_text(CSV, encoding="utf-8")
        link = project / "data" / "link.csv"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available")
        assert "outside the project" in self.error_detail(self.render(project, "data/link.csv"))

    def test_the_pdf_side_resolves_the_same_way(self, project, fake_page):
        renderer = TypstRenderer(str(project), typst_root=str(project), line_mapping="off")
        renderer.current_dir = str(project / "docs")
        assert renderer._vega_svg_path("vega-lite", data_spec("../data/sales.csv")) is not None
        with pytest.raises(SystemExit):
            renderer._vega_svg_path("vega-lite", data_spec("../../x.csv"))


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


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
def test_a_csv_file_is_rendered_with_the_real_browser(tmp_path):
    """CSVを埋め込んだ仕様が、実際に描画される（数値・日付の型の判定は、Vega自身が行う。#350）。"""
    (tmp_path / "sales.csv").write_bytes(b"date,sales" + bytes([10]) + b"2026-01-01,10" + bytes([10]) + b"2026-02-01,300" + bytes([10]))
    spec = {"data": {"url": "sales.csv"}, "mark": "line",
            "encoding": {"x": {"field": "date", "type": "temporal"},
                         "y": {"field": "sales", "type": "quantitative", "scale": {"type": "log"}}}}
    md = tmp_path / "doc.md"
    md.write_text("```vega-lite" + chr(10) + json.dumps(spec) + chr(10) + "```" + chr(10), encoding="utf-8")
    result = render_html(str(md), plugins={"mermaid": False, "plantuml": False, "d2": False})
    assert result.ok, result.diagnostics
    svg_path = next((tmp_path / ".text-compositor" / "cache").glob("vega-lite_*.svg"))
    svg = svg_path.read_text(encoding="utf-8")
    assert "<path" in svg and "300" in svg   # 折れ線と、y軸の値
