"""bizmodelのHTML出力（` ```bizmodel `フェンスと、`.bizmodel`の単体ファイル。#447）のテスト。外部ツールは使わない。"""
import os
import re

import pytest

from tests.test_html_output import PLAIN, body, convert

DSL = ('company A "売り手"\nperson B "買い手"\n'
       'A -> B : goods "商品" / money "100円"\n')


def plugins(**extra):
    return {**PLAIN, **extra}


def svg_of(result, html):
    """HTMLの`<img src>`が指す、SVGの文字列（srcは、HTMLのあるフォルダが基準）。"""
    src = re.search(r'<img src="([^"]+)"', body(html)).group(1)
    path = os.path.normpath(os.path.join(os.path.dirname(result.html_path), src))
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestFence:
    def test_a_fence_becomes_a_diagram_image(self, tmp_path):
        result, html = convert(tmp_path, f"# T\n\n```bizmodel\n{DSL}```\n")
        assert result.ok and not result.warnings
        assert 'class="diagram diagram-bizmodel"' in body(html)
        svg = svg_of(result, html)
        assert svg.startswith("<svg") and "商品" in svg and "100円" in svg

    def test_the_default_alt_is_the_kind_and_an_explicit_alt_wins(self, tmp_path):
        _, html = convert(tmp_path, f"# T\n\n```bizmodel\n{DSL}```\n")
        assert 'alt="bizmodel diagram"' in body(html)
        _, html = convert(tmp_path, f'# T\n\n```bizmodel {{alt="取引の流れ"}}\n{DSL}```\n')
        assert 'alt="取引の流れ"' in body(html)

    def test_the_same_source_reuses_the_cached_svg(self, tmp_path):
        convert(tmp_path, f"# T\n\n```bizmodel\n{DSL}```\n")
        cache = os.path.join(str(tmp_path), ".text-compositor", "cache")
        before = {f: os.path.getmtime(os.path.join(cache, f)) for f in os.listdir(cache) if f.startswith("bizmodel_")}
        convert(tmp_path, f"# T\n\n```bizmodel\n{DSL}```\n")
        after = {f: os.path.getmtime(os.path.join(cache, f)) for f in os.listdir(cache) if f.startswith("bizmodel_")}
        assert before and before == after

    def test_a_syntax_error_is_reported_at_the_line_in_the_document(self, tmp_path):
        bad = 'company A "x"\nperson B "y"\nA -> B : goods "z"\n'   # E01（moneyがない）。図の3行目
        result, _ = convert(tmp_path, f"# T\n\n本文\n\n```bizmodel\n{bad}```\n")
        assert not result.ok
        (error,) = [d for d in result.errors if d.detail and "E01" in d.detail]
        assert error.line == 8   # フェンスは5行目。図の3行目は、原稿の8行目

    def test_the_plugin_off_shows_the_source_as_code(self, tmp_path):
        result, html = convert(tmp_path, f"# T\n\n```bizmodel\n{DSL}```\n", plugins=plugins(bizmodel=False))
        assert result.ok and "language-bizmodel" in html and "diagram-bizmodel" not in body(html)

    def test_bizmodel_is_an_allowed_plugins_key(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        assert "bizmodel" in _ALLOWED_PLUGINS_KEYS


class TestFile:
    @pytest.mark.parametrize("name", ["flow.bizmodel", "flow.bmv", "FLOW.BMV"])
    def test_a_bizmodel_file_is_a_diagram_page(self, tmp_path, name):
        result, html = convert(tmp_path, DSL, name=name)
        assert result.ok and not result.warnings
        assert 'class="diagram diagram-bizmodel"' in body(html)

    def test_a_syntax_error_in_a_file_points_at_its_line(self, tmp_path):
        bad = 'company A "x"\nperson B "y"\nA -> B : goods "z"\n'
        result, _ = convert(tmp_path, bad, name="bad.bizmodel")
        assert not result.ok
        (error,) = [d for d in result.errors if d.detail and "E01" in d.detail]
        assert error.line == 3

    @pytest.mark.parametrize("name", ["flow.bizmodel", "flow.bmv"])
    def test_the_plugin_off_shows_the_file_as_code(self, tmp_path, name):
        result, html = convert(tmp_path, DSL, name=name, plugins=plugins(bizmodel=False))
        assert result.ok and "language-bizmodel" in html


class TestCanvas:
    CANVAS = 'type canvas\ntitle "ダイソー"\nvalue "手軽さ、安さ！"\nsegments "一般顧客"\n'

    def test_a_canvas_fence_becomes_a_diagram_with_the_credit(self, tmp_path):
        result, html = convert(tmp_path, f"# T\n\n```bizmodel\n{self.CANVAS}```\n")
        assert result.ok and not result.warnings
        svg = svg_of(result, html)
        assert "価値提案（VP）" in svg and "Strategyzer.com (CC BY-SA 3.0)" in svg

    def test_a_canvas_file_is_a_diagram_page(self, tmp_path):
        result, html = convert(tmp_path, self.CANVAS, name="model.bmv")
        assert result.ok and 'class="diagram diagram-bizmodel"' in body(html)

    def test_a_canvas_error_is_reported_at_the_line_in_the_document(self, tmp_path):
        bad = 'type canvas\nvalue "a"\nbanana "x"\n'   # E06。図の3行目
        result, _ = convert(tmp_path, f"# T\n\n```bizmodel\n{bad}```\n")
        assert not result.ok
        (error,) = [d for d in result.errors if d.detail and "E06" in d.detail]
        assert error.line == 6   # フェンスは3行目。図の3行目は、原稿の6行目

