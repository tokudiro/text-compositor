"""Mermaidのフローチャートの、自作の変換器（flowchart_render.py。#532）のテスト。"""
import re
import xml.dom.minidom
from pathlib import Path

import pytest

from text_compositor import flowchart_render as fr

GALLERY = Path(__file__).resolve().parent.parent / "doc" / "usage" / "14_gallery_mermaid.md"


class TestParse:
    def test_header_direction(self):
        assert fr.parse("flowchart LR\nA --> B").direction == "LR"
        assert fr.parse("graph TD\nA --> B").direction == "TB"      # TDは、TBと同じ
        assert fr.parse("graph\nA --> B").direction == "TB"          # 向きを省くと、TB

    def test_nodes_edges_and_shapes(self):
        chart = fr.parse('flowchart TD\n  A[受付] --> B{承認?}\n  B --> C(丸) --> D([角丸]) --> E((円))')
        assert [(n.id, n.label, n.shape) for n in chart.nodes.values()] == [
            ("A", "受付", "rect"), ("B", "承認?", "diamond"), ("C", "丸", "round"), ("D", "角丸", "stadium"), ("E", "円", "circle")]
        assert [(e.source, e.target) for e in chart.edges] == [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]

    def test_flowchart_shapes(self):
        """流れ図の定番: 端子・処理・判断・入出力・ループ（六角形）・定義済み処理・データベース。"""
        chart = fr.parse(
            "flowchart TD\n  A[/入力/] --> B[\\戻し\\] --> C[/台形\\] --> D[\\逆台形/] --> E{{ループ}} --> F[[定義済み]] --> G[(DB)] --> H(((二重)))")
        assert [n.shape for n in chart.nodes.values()] == [
            "parallelogram", "parallelogram_alt", "trapezoid", "trapezoid_alt", "hexagon", "subroutine", "cylinder", "doublecircle"]
        assert [n.label for n in chart.nodes.values()][:3] == ["入力", "戻し", "台形"]

    def test_a_node_without_a_label_shows_its_id(self):
        chart = fr.parse("flowchart TD\nA --> B")
        assert chart.nodes["A"].label == "" and chart.nodes["B"].shape == "rect"

    def test_a_later_label_names_a_node_first_written_without_one(self):
        chart = fr.parse("flowchart TD\nA --> B\nB[名前]")
        assert chart.nodes["B"].label == "名前"

    @pytest.mark.parametrize("arrow, line, has_arrow", [
        ("-->", "solid", True), ("---", "solid", False), ("-.->", "dotted", True),
        ("-.-", "dotted", False), ("==>", "thick", True), ("===", "thick", False)])
    def test_edge_forms(self, arrow, line, has_arrow):
        edge = fr.parse(f"flowchart TD\nA {arrow} B").edges[0]
        assert (edge.line, edge.arrow) == (line, has_arrow)

    def test_edge_labels_in_both_forms(self):
        chart = fr.parse('flowchart TD\nA -->|はい| B\nA -- いいえ --> C\nB -. 点線 .-> C')
        assert [e.label for e in chart.edges] == ["はい", "いいえ", "点線"]

    def test_ampersand_makes_every_pair(self):
        chart = fr.parse("flowchart TD\nA & B --> C & D")
        assert [(e.source, e.target) for e in chart.edges] == [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]

    def test_no_space_around_the_arrow_and_semicolons(self):
        chart = fr.parse("flowchart TD\nA-->B; B-->C")
        assert [(e.source, e.target) for e in chart.edges] == [("A", "B"), ("B", "C")]

    def test_comments_and_blank_lines_are_ignored(self):
        assert len(fr.parse("flowchart TD\n%% 注釈\n\nA --> B %% 行末\n").edges) == 1

    def test_quoted_labels_may_hold_brackets_and_br(self):
        chart = fr.parse('flowchart TD\nA["a (b) [c]"] --> B[x<br/>y]')
        assert chart.nodes["A"].label == "a (b) [c]" and chart.nodes["B"].label == "x\ny"

    @pytest.mark.parametrize("code, word", [
        ("flowchart TD\nsubgraph X\nA-->B\nend", "subgraph"),
        ("flowchart TD\nA-->B\nstyle A fill:#f9f", "style"),
        ("flowchart TD\nA-->B\nclassDef x fill:#f9f", "classDef"),
        ("flowchart TD\nA-->B\nclick A href", "click"),
        ("flowchart TD\nA-->B\nlinkStyle 0 stroke:red", "linkStyle"),
        ("flowchart TD\nA>flag] --> B", "'>'"),
        ("flowchart TD\nA((x)) <--> B", "arrow"),
        ("flowchart TD\nA:::cls --> B", "Class"),
        ("sequenceDiagram\nA->>B: hi", "flowchart"),
    ])
    def test_unsupported_syntax_is_declared_not_failed(self, code, word):
        """対応しない書き方は、失敗ではなく、従来のMermaidへ任せるための、宣言（設計書3.3）。"""
        with pytest.raises(fr.FlowchartUnsupported) as e:
            fr.parse(code)
        assert word.lower() in str(e.value).lower()
        assert fr.supports(code) == (False, str(e.value))

    @pytest.mark.parametrize("code, message", [
        ("flowchart TD\nA -->", "no target"),
        ("flowchart TD\nA[open --> B", "closing"),
        ("flowchart TD\nA -->|x B", "closing '|'"),
        ("flowchart TD\n", "no nodes"),
    ])
    def test_syntax_errors_are_errors_with_the_line(self, code, message):
        with pytest.raises(fr.FlowchartError) as e:
            fr.parse(code)
        assert not isinstance(e.value, fr.FlowchartUnsupported) and message in str(e.value)
        assert fr.supports(code)[0] is True     # 誤りは、描画が、行つきで報告する

    def test_the_error_carries_the_line_in_the_code(self):
        with pytest.raises(fr.FlowchartError) as e:
            fr.parse("flowchart TD\nA --> B\nC -->")
        assert e.value.line == 3


def test_every_flowchart_in_the_gallery_is_supported():
    """Mermaidのギャラリーの例は、すべて、自作の変換器が描ける。"""
    text = GALLERY.read_text(encoding="utf-8")
    codes = [m.group(1) for m in re.finditer(r"^```mermaid\n(.*?)^```", text, re.S | re.M)
             if re.match(r"\s*(flowchart|graph)\b", m.group(1))]
    assert len(codes) >= 2
    for code in codes:
        assert fr.supports(code) == (True, ""), code
        _svg(code)


class TestWrap:
    def setup_method(self):
        text = "ユーザーが、長い名前のファイルを、アプリケーションのメニューから選択して開く。Hello world"
        fr._measure([text])

    def test_katakana_words_and_latin_words_are_not_split(self):
        lines = fr.wrap("ユーザーが、長い名前のファイルを、アプリケーションのメニューから選択して開く", 11, 150)
        assert len(lines) >= 2
        assert any("ファイル" in ln for ln in lines) and any("アプリケーション" in ln for ln in lines)

    def test_a_punctuation_mark_does_not_start_a_line(self):
        lines = fr.wrap("ユーザーが、長い名前のファイルを、アプリケーションのメニューから選択して開く。", 11, 150)
        assert all(ln[0] not in "、。" for ln in lines if ln)

    def test_latin_words_break_at_spaces(self):
        lines = fr.wrap("Hello world", 11, 40)
        assert lines == ["Hello", "world"]

    def test_explicit_newlines_are_kept(self):
        assert fr.wrap("a\nb", 11, 150) == ["a", "b"]

    def test_a_short_text_stays_on_one_line(self):
        assert fr.wrap("受付", 11, 150) == ["受付"]


def _svg(code):
    svg = fr.render_svg(code)
    xml.dom.minidom.parseString(svg)    # 正しいXMLであること
    return svg


class TestRender:
    def test_it_draws_every_node_and_edge(self):
        svg = _svg('flowchart TD\n  A[受付] --> B{承認?}\n  B -->|はい| C[発送]\n  B -->|いいえ| D[差し戻し]\n  D --> A')
        assert svg.count("<path ") == 4                      # 矢印
        assert svg.count("<polygon") == 4 + 1                # 矢じり4つと、ひし形1つ
        assert svg.count("<rect") == 3
        for text in ("受付", "承認?", "はい", "いいえ", "発送", "差し戻し"):
            assert f">{text}<" in svg

    def test_it_is_the_same_every_time(self):
        """同じ入力なら、同じSVG（決定論。仕様9章）。"""
        code = "flowchart LR\nA --> B & C\nB --> D\nC --> D"
        assert fr.render_svg(code) == fr.render_svg(code)

    def test_the_size_is_in_points_and_matches_the_view_box(self):
        svg = _svg("flowchart TD\nA --> B")
        m = re.search(r'width="([\d.]+)pt" height="([\d.]+)pt" viewBox="-8 -8 ([\d.]+) ([\d.]+)"', svg)
        assert m and m.group(1) == m.group(3) and m.group(2) == m.group(4)

    def test_edge_styles(self):
        svg = _svg("flowchart TD\nA -.-> B\nB ==> C\nC --- D")
        assert 'stroke-dasharray="4 3"' in svg and 'stroke-width="2.6"' in svg
        assert svg.count("<polygon") == 2                    # 矢じりは、`---`にない

    def test_the_font_and_colors_are_fixed_and_there_is_no_label_background(self):
        svg = _svg("flowchart TD\nA -->|文字| B")
        assert "Noto Sans JP" in svg
        assert svg.count("<rect") == 2                       # 箱だけ。矢印の文字に、背景の四角を付けない

    def test_a_long_label_is_wrapped_inside_the_box(self):
        svg = _svg("flowchart TD\nA[ユーザーが、長い名前のファイルを、アプリケーションのメニューから選択して開く]")
        assert svg.count("<text") >= 3

    def test_every_direction_lays_out(self):
        for direction in ("TB", "BT", "LR", "RL"):
            assert "<svg" in _svg(f"flowchart {direction}\nA --> B --> C")

    def test_a_loop_and_a_repeated_pair_keep_all_edges(self):
        svg = _svg("flowchart TD\nA --> B\nB --> A\nA --> B")
        assert svg.count("<path ") == 3

    def test_a_syntax_error_is_raised_at_render_time(self):
        with pytest.raises(fr.FlowchartError):
            fr.render_svg("flowchart TD\nA -->")

    def test_unsupported_syntax_is_raised_as_unsupported(self):
        with pytest.raises(fr.FlowchartUnsupported):
            fr.render_svg("flowchart TD\nsubgraph X\nA-->B\nend")


class TestEdgeEnds:
    """矢印の端は、箱の、実際の形の縁にある（Graphvizは、箱の大きさだけを知っているため、形に合わせて直す）。"""

    @pytest.mark.parametrize("shape_open, shape_close", [
        ("{", "}"), ("[", "]"), ("(", ")"), ("([", "])"), ("((", "))"), ("{{", "}}"), ("[/", "/]"), ("[/", "\\]"), ("[(", ")]"), ("[[", "]]")])
    def test_every_end_touches_the_outline_of_its_shape(self, shape_open, shape_close):
        chart = fr.parse(f"flowchart TD\n  A[上] --> M{shape_open}真ん中{shape_close}\n  M --> L[左]\n  M --> R[右]\n  L --> M")
        placed = fr.layout(chart)
        for route in placed["routes"]:
            edge = route["edge"]
            start, end = route["points"][0], route["points"][-1]
            for point, name in ((start, edge.source), (end, edge.target)):
                box = placed["boxes"][name]
                assert fr._inside(box, *point), (edge.source, edge.target, name, point)       # 縁の上（内側を含む）
                # 縁の、すぐ外側（中心から離れる向きに、0.6pt）は、外
                dx, dy = point[0] - box.x, point[1] - box.y
                norm = (dx * dx + dy * dy) ** 0.5 or 1.0
                assert not fr._inside(box, point[0] + dx / norm * 0.6, point[1] + dy / norm * 0.6), (edge.source, edge.target, name)

    def test_the_slanted_and_hexagon_shapes_are_drawn_as_polygons(self):
        svg = _svg("flowchart TD\nA[/入力/] --> B{{ループ}} --> C[[処理]] --> D[(DB)] --> E(((終)))")
        assert svg.count("<polygon") >= 2 + 4          # 平行四辺形・六角形と、矢じり
        assert svg.count("<ellipse") == 2              # 二重丸


def test_the_cache_version_names_the_pieces_that_change_the_output():
    version = fr.cache_version()
    assert version.startswith(f"flowchart{fr.FLOWCHART_VERSION}+layout{fr.DIAGRAPH_LAYOUT_VERSION}+typst")
