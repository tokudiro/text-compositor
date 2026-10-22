"""Pikchr（Typstのパッケージ`kip`。pikchr_render.py・図のフェンスの変換、#213）のテスト。"""
import os
import re

import pytest

from text_compositor import diagnostics, pikchr_render
from text_compositor.api import render_html
from text_compositor.pikchr_render import PikchrRenderError, render_svg
from text_compositor.renderer import TypstRenderer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}


def _read(relative):
    with open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as f:
        return f.read()


def test_the_kip_version_is_the_same_in_the_source_and_the_bundle():
    """生成コードが読み込む版と、ZIPに同梱するパッケージの版が、ずれると、配布物で、取得（ネットワーク）が起きる。"""
    bundled = re.search(r"name: 'kip', version: '([\d.]+)'", _read("viewer/scripts/build-dist.js")).group(1)
    assert pikchr_render.KIP_VERSION == bundled


class TestRender:
    def test_pikchr_becomes_an_svg_without_a_page_background(self):
        svg = render_svg('box "日本語" fit; arrow; circle "終了"')
        assert svg.startswith("<svg") and "viewBox" in svg
        assert 'fill="#ffffff"' not in svg   # ページの背景（白）を、敷かない（ダークの文書で、白い四角にならない）

    def test_it_is_the_pikchr_svg_itself_with_the_size_of_the_drawing(self):
        """Typstが書き出した入れ物（SVGを画像として入れ子にしたもの）ではない。入れ子の文字は、PDFへ埋め込むと、描かれない（#474）。"""
        svg = render_svg('box "日本語" fit; arrow; circle "終了"')
        assert 'class="pikchr"' in svg and "<text" in svg and "<image" not in svg
        m = re.match(r'<svg width="([\d.]+)pt" height="([\d.]+)pt" ', svg)
        assert m and float(m.group(1)) > 0 and float(m.group(2)) > 0   # viewBoxの0.75倍（px→pt）

    def test_the_compiler_is_reused_and_a_later_diagram_is_not_a_leftover(self):
        first = render_svg('box "a"')
        assert render_svg('box "a"; arrow; box "b"') != first
        assert render_svg('box "a"') == first

    def test_a_syntax_error_carries_pikchrs_own_message_and_the_line(self):
        with pytest.raises(PikchrRenderError) as e:
            render_svg('box "ok"\nbox "unterminated\n')
        assert "ERROR: unrecognized token" in str(e.value)
        assert e.value.code_line == 2   # 文脈の行（1行目）ではなく、エラーの行
        assert render_svg('box "ok"').startswith("<svg")   # エラーの後でも、同じCompilerで、次の図が描ける

    def test_the_code_is_passed_as_data_so_quotes_and_typst_syntax_are_harmless(self):
        assert render_svg('box "#panic(\\"x\\") $ \\\\ \\""').startswith("<svg")


def _html(tmp_path, text, name="doc.md", plugins=PLAIN):
    md = tmp_path / name
    md.write_text(text, encoding="utf-8")
    result = render_html(str(md), plugins=plugins)
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class TestHtmlOutput:
    def test_a_pikchr_fence_becomes_a_cached_svg_img(self, tmp_path):
        result, html = _html(tmp_path, 'a\n\n```pikchr {width=300pt}\nbox "開始"; arrow; box "終了"\n```\n')
        assert result.ok and not result.warnings
        m = re.search(r'<img src="([^"]+)" alt="pikchr diagram" style="width:300pt">', html)
        assert m, html
        assert (tmp_path / ".text-compositor" / m.group(1)).read_text(encoding="utf-8").startswith("<svg")

    def test_a_pikchr_source_file_is_a_page_with_that_diagram(self, tmp_path):
        result, html = _html(tmp_path, 'box "x"\n', name="p.pikchr")
        assert result.ok and 'class="diagram diagram-pikchr"' in html

    def test_a_syntax_error_is_reported_at_the_line_in_the_manuscript(self, tmp_path):
        # フェンスは3行目。Pikchrの2行目は、原稿の5行目
        result, _ = _html(tmp_path, 'a\n\n```pikchr\nbox "ok"\nbox "unterminated\n```\n')
        assert not result.ok
        error = result.errors[0]
        assert error.message == "Pikchr diagram failed to render"
        assert error.line == 5 and "unrecognized token" in error.detail

    def test_a_syntax_error_in_a_source_file_is_reported_at_the_line_of_the_file(self, tmp_path):
        result, _ = _html(tmp_path, 'box "ok"\nbox "unterminated\n', name="bad.pikchr")
        assert not result.ok and result.errors[0].line == 2

    def test_the_plugin_setting_falls_back_to_a_code_block_without_a_warning(self, tmp_path):
        result, html = _html(tmp_path, '```pikchr\nbox "x"\n```\n', plugins={**PLAIN, "pikchr": False})
        assert result.ok and 'class="language-pikchr"' in html and not result.warnings


class TestPdfCode:
    """PDFでも、HTMLと同じく、SVGを作って（キャッシュを共有）、画像として埋め込む（#474。登録簿のPikchrプラグイン）。"""

    def _render(self, text, **kwargs):
        renderer = TypstRenderer(line_mapping="off", **kwargs)
        with diagnostics.collect():
            return renderer.render(text, filepath="doc.md")

    def test_the_fence_becomes_an_image_of_the_cached_svg(self):
        code = self._render('```pikchr\nbox "日本語"\n```\n')
        m = re.search(r'fit-image\("/([^"]+pikchr_[0-9a-f]+\.svg)"\)', code)   # はみ出し防止の自動縮小つき
        assert m, code
        assert "kip" not in code and "panic" not in code   # Typstの中で、Pikchrを動かさない
    def test_a_size_attribute_skips_the_automatic_shrink(self):
        code = self._render('```pikchr {width=5cm}\nbox "x"\n```\n')
        assert re.search(r'image\("/[^"]+\.svg", width: 5cm\)', code) and "fit-image" not in code

    def test_the_same_code_reuses_the_same_svg(self):
        first = self._render('```pikchr\nbox "a"\n```\n')
        assert self._render('```pikchr\nbox "a"\n```\n') == first
        assert self._render('```pikchr\nbox "b"\n```\n') != first

    def test_it_is_generated_without_touching_the_templates_public_names(self):
        """カスタムテンプレートが、`render-pikchr`のような、新しい公開名を、持たなくても、動く。"""
        assert "render-pikchr" not in self._render('```pikchr\nbox "x"\n```\n')

    def test_a_syntax_error_is_reported_at_the_line_in_the_manuscript(self):
        # フェンスは3行目。Pikchrの2行目は、原稿の5行目（HTML出力と同じ）
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as sink:
            with pytest.raises(SystemExit):
                renderer.render('a\n\n```pikchr\nbox "ok"\nbox "unterminated\n```\n', filepath="doc.md")
        errors = sink.errors
        assert errors and errors[0].message == "Pikchr diagram failed to render"
        assert errors[0].line == 5 and "unrecognized token" in errors[0].detail

    def test_the_plugin_setting_leaves_a_plain_code_block(self):
        code = self._render('```pikchr\nbox "x"\n```\n', pikchr_enabled=False)
        assert ".svg" not in code and "box" in code


class TestRegistered:
    """Pikchrは、登録簿（plugins/）に載っている（#474）。"""

    def test_the_registry_describes_pikchr(self):
        from text_compositor.plugins import registry
        plugin = registry.get("pikchr")
        assert plugin.langs == ("pikchr",) and plugin.file_exts == (".pikchr",) and plugin.label == "Pikchr"
        assert registry.by_lang("pikchr") is plugin and registry.by_ext(".pikchr") is plugin

    def test_the_cache_version_is_unchanged_so_existing_caches_stay_valid(self):
        """設計書3.6: 現行のバックエンドの版の文字列は、変えない。"""
        from text_compositor.plugins import registry
        assert registry.get("pikchr").backends["kip"].version() == pikchr_render.cache_version()

    def test_the_hand_kept_tables_agree_with_the_registry(self):
        """周辺の統合（設計書4章のステップ5）までは、手で持つ表が残る。ずれたら、ここで気づく。"""
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        from text_compositor.plugins import registry
        from text_compositor.renderer_options import PLUGIN_FLAGS
        assert all(TypstRenderer.DIAGRAM_FILE_EXTS[ext] == name for ext, name in registry.file_exts().items())
        assert "pikchr" in _ALLOWED_PLUGINS_KEYS and "pikchr" in registry.allowed_plugin_keys()
        flag = next(f for f in PLUGIN_FLAGS if f.config_key == "pikchr")
        assert flag.default is registry.get("pikchr").default_enabled
        assert registry.resolve_enabled({})["pikchr"] is flag.default
