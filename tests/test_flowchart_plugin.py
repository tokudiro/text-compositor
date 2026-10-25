"""フローチャートのプラグイン（plugins/flowchart.py。登録簿への接続、#536）のテスト。

記法の解析は`test_flowchart_notation.py`、描画は同じファイルの`TestRender`、試作は`test_flowchart_render.py`が調べる。
ここでは、フェンス・章ファイル・設定・キャッシュ・診断の行が、登録簿を通ってつながっていることを調べる。
"""
import re

import pytest

from text_compositor import diagnostics, flowchart_render
from text_compositor.api import render_html
from text_compositor.renderer import TypstRenderer

PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}
SAMPLE = "start\nloop 注文処理: 注文がなくなるまで\n  data 注文を入力\n  judge 在庫がある?\n    はい: 出荷する\n    いいえ: 取り寄せる\nendloop\nend\n"


def _html(tmp_path, text, name="doc.md", plugins=PLAIN):
    md = tmp_path / name
    md.write_text(text, encoding="utf-8")
    result = render_html(str(md), plugins=plugins)
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class TestHtmlOutput:
    def test_a_flowchart_fence_becomes_a_cached_svg_img(self, tmp_path):
        result, html = _html(tmp_path, f"a\n\n```flowchart {{width=300pt}}\n{SAMPLE}```\n")
        assert result.ok and not result.warnings
        m = re.search(r'<img src="([^"]+)" alt="[^"]*" style="width:300pt">', html)
        assert m, html
        svg = (tmp_path / ".text-compositor" / m.group(1)).read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "注文処理" in svg

    def test_a_flow_source_file_is_a_page_with_that_diagram(self, tmp_path):
        result, html = _html(tmp_path, SAMPLE, name="order.flow")
        assert result.ok and 'class="diagram diagram-flowchart"' in html

    def test_a_syntax_error_is_reported_at_the_line_in_the_manuscript(self, tmp_path):
        # フェンスは3行目。コードの2行目（`loop`の行）は、原稿の5行目
        result, _ = _html(tmp_path, "a\n\n```flowchart\nstart\nloop L\n```\n")
        assert not result.ok
        error = result.errors[0]
        assert error.message == "Flowchart diagram failed to render"
        assert error.line == 5 and "no matching endloop" in error.detail

    def test_a_syntax_error_in_a_source_file_is_reported_at_the_line_of_the_file(self, tmp_path):
        result, _ = _html(tmp_path, "start\njudge x?\n  はい: 処理\nend\n", name="bad.flow")
        assert not result.ok and result.errors[0].line == 2

    def test_the_plugin_setting_falls_back_to_a_code_block_without_a_warning(self, tmp_path):
        result, html = _html(tmp_path, f"```flowchart\n{SAMPLE}```\n", plugins={**PLAIN, "flowchart": False})
        assert result.ok and 'class="language-flowchart"' in html and not result.warnings

    def test_a_mermaid_flowchart_is_still_a_mermaid_fence(self, tmp_path):
        """Mermaidの`flowchart`は、従来どおり、`mermaid`フェンスで書く。新しいフェンス名は、これに触れない。"""
        result, html = _html(tmp_path, "```mermaid\nflowchart TD\n  A --> B\n```\n", plugins={**PLAIN, "mermaid": False})
        assert result.ok and 'class="language-mermaid"' in html


class TestPdfCode:
    """PDFでも、HTMLと同じく、SVGを作って（キャッシュを共有）、画像として埋め込む。"""

    def _render(self, text, **kwargs):
        renderer = TypstRenderer(line_mapping="off", **kwargs)
        with diagnostics.collect():
            return renderer.render(text, filepath="doc.md")

    def test_the_fence_becomes_an_image_of_the_cached_svg(self):
        code = self._render(f"```flowchart\n{SAMPLE}```\n")
        assert re.search(r'fit-image\("/([^"]+flowchart_[0-9a-f]+\.svg)"\)', code), code

    def test_a_flow_chapter_becomes_the_same_image(self):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect():
            code = renderer.render_chapter(SAMPLE, filepath="order.flow")
        assert re.search(r'fit-image\("/([^"]+flowchart_[0-9a-f]+\.svg)"\)', code), code

    def test_a_size_attribute_skips_the_automatic_shrink(self):
        code = self._render(f"```flowchart {{width=5cm}}\n{SAMPLE}```\n")
        assert re.search(r'image\("/[^"]+\.svg", width: 5cm\)', code) and "fit-image" not in code

    def test_the_same_code_reuses_the_same_svg(self):
        first = self._render(f"```flowchart\n{SAMPLE}```\n")
        assert self._render(f"```flowchart\n{SAMPLE}```\n") == first
        assert self._render("```flowchart\nstart\nend\n```\n") != first

    def test_a_syntax_error_is_reported_at_the_line_in_the_manuscript(self):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as sink:
            with pytest.raises(SystemExit):
                renderer.render("a\n\n```flowchart\nstart\nloop L\n```\n", filepath="doc.md")
        errors = sink.errors
        assert errors and errors[0].message == "Flowchart diagram failed to render"
        assert errors[0].line == 5 and "no matching endloop" in errors[0].detail

    def test_the_plugin_setting_leaves_a_plain_code_block(self):
        code = self._render(f"```flowchart\n{SAMPLE}```\n", flowchart_enabled=False)
        assert ".svg" not in code and "注文処理" in code


class TestRegistered:
    def test_the_registry_describes_the_flowchart(self):
        from text_compositor.plugins import registry
        plugin = registry.get("flowchart")
        assert plugin.langs == ("flowchart",) and plugin.file_exts == (".flow",) and plugin.label == "Flowchart"
        assert registry.by_lang("flowchart") is plugin and registry.by_ext(".flow") is plugin
        assert list(plugin.backends) == ["native"] and plugin.default_enabled is True

    def test_the_only_backend_is_native_with_no_fallback(self):
        from text_compositor.plugins import registry
        backend = registry.get("flowchart").backends["native"]
        assert backend.outputs == ("svg",)
        assert backend.version() == flowchart_render.cache_version()

    def test_the_hand_kept_tables_agree_with_the_registry(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        from text_compositor.plugins import registry
        from text_compositor.renderer_options import PLUGIN_FLAGS
        assert TypstRenderer.DIAGRAM_FILE_EXTS[".flow"] == "flowchart"
        assert "flowchart" in _ALLOWED_PLUGINS_KEYS and "flowchart" in registry.allowed_plugin_keys()
        flag = next(f for f in PLUGIN_FLAGS if f.config_key == "flowchart")
        assert flag.default is registry.get("flowchart").default_enabled
        assert registry.resolve_enabled({})["flowchart"] is flag.default
