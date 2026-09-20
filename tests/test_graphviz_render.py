"""HTML出力のGraphviz（Typstの`diagraph`。graphviz_render.py、#264）のテスト。"""
import os
import re

import pytest

from text_compositor import graphviz_render
from text_compositor.graphviz_render import GraphvizRenderError, find_unsupported, render_svg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(relative):
    with open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as f:
        return f.read()


class TestPinnedVersion:
    def test_the_diagraph_version_is_the_same_in_every_place_it_is_pinned(self):
        """PDFのテンプレート・ZIPに同梱するパッケージ・HTML出力の、3か所の版が、ずれると、図が変わる・取得が起きる。"""
        template = re.search(r'@preview/diagraph:([\d.]+)', _read("text_compositor/templates/_common.typ")).group(1)
        bundled = re.search(r"name: 'diagraph', version: '([\d.]+)'", _read("viewer/scripts/build-dist.js")).group(1)
        assert graphviz_render.DIAGRAPH_VERSION == template == bundled

    def test_the_cache_version_names_diagraph_typst_and_the_wrapper(self, monkeypatch):
        version = graphviz_render.cache_version()
        assert f"diagraph{graphviz_render.DIAGRAPH_VERSION}" in version and "+typst0." in version
        monkeypatch.setattr(graphviz_render, "DIAGRAPH_VERSION", "9.9.9")
        assert graphviz_render.cache_version() != version


class TestRender:
    def test_dot_becomes_an_svg_with_glyph_outlines(self):
        svg = render_svg("digraph { 開始 -> 終了 }")
        assert svg.startswith("<svg") and "viewBox" in svg
        assert "<text" not in svg   # 文字は、輪郭（フォントに依存しない）

    def test_the_compiler_is_reused_and_a_later_diagram_is_not_a_leftover_of_the_first(self):
        first = render_svg("digraph { a -> b }")
        second = render_svg("digraph { a -> b -> c }")
        assert first != second
        assert render_svg("digraph { a -> b }") == first

    def test_a_syntax_error_carries_the_diagraph_message_and_the_dot_line(self):
        with pytest.raises(GraphvizRenderError) as e:
            render_svg("digraph {\n  a -> b\n  b -> \n}")
        assert str(e.value).startswith("Diagraph error: syntax error") and e.value.dot_line is not None
        # エラーの後でも、同じCompilerで、次の図が描ける
        assert render_svg("digraph { a -> b }").startswith("<svg")


class TestFindUnsupported:
    @pytest.mark.parametrize("dot, expected", [
        ('digraph { a [shape=record label="{x|y}"] }', [("record", 1)]),
        ('digraph { a [shape="Mrecord"] }', [("record", 1)]),
        ('digraph {\n node [shape = record]\n a\n}', [("record", 2)]),
        ('digraph {\n label="タイトル"\n a\n}', [("graph-label", 2)]),
        ('digraph {\n a\n graph [label="タイトル" labelloc=t]\n}', [("graph-label", 3)]),
        ('digraph {\n label="t"\n a [shape=record]\n}', [("graph-label", 2), ("record", 3)]),
        ('graph {\n label=x\n a -- b\n}', [("graph-label", 2)]),
    ])
    def test_detects_what_diagraph_cannot_draw(self, dot, expected):
        assert find_unsupported(dot) == expected

    @pytest.mark.parametrize("dot", [
        'digraph { a [label="ノード"] }',
        'digraph { a -> b [label="辺"] }',
        'digraph { node [label="n"] }',
        'digraph { edge [label="e"] }',
        'digraph { subgraph cluster_a { label="グループ"; a } }',
        'digraph { subgraph cluster_a { graph [label="グループ"]; a } }',
        'digraph { a [shape=box] b [shape=ellipse] c [shape=hexagon] }',
        'digraph { a [label="shape=record"] }',                      # 文字列の中
        'digraph { a [label=<<b>shape=record</b>>] }',                # HTMLラベルの中
        'digraph {\n // label="コメント"\n /* shape=record */\n# label=x\n a\n}',
        'digraph { a [xlabel="label"] }',
        'digraph { a [shape=recordish] }',
        'digraph { label_of_a -> b }',
        'digraph { 日本語 -> 別のノード [label="辺"] }',
    ])
    def test_does_not_flag_what_is_drawn(self, dot):
        assert find_unsupported(dot) == []

    def test_an_unterminated_string_or_comment_does_not_raise(self):
        assert find_unsupported('digraph { a [label="x') == []
        assert find_unsupported('digraph { /* x') == []
        assert find_unsupported('digraph { a [label=<<b>x') == []
        assert find_unsupported('') == []
