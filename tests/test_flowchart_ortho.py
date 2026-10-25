"""フローチャートの線を、水平と垂直だけで引く処理（flowchart_ortho.py。#540）のテスト。"""
import re
import xml.dom.minidom
from types import SimpleNamespace

import pytest

from text_compositor import flowchart_notation as fn
from text_compositor import flowchart_render as fr
from text_compositor.flowchart_ortho import MERGE_GAP, SNAP, route_edges


def box(x, y, width=80.0, height=30.0, shape="rect"):
    return SimpleNamespace(x=x, y=y, width=width, height=height, node=SimpleNamespace(shape=shape))


def edge(source, target, label="", arrow=True):
    return SimpleNamespace(source=source, target=target, label=label, arrow=arrow)


def axis_aligned(points):
    return all(abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01 for a, b in zip(points, points[1:]))


def diamond_with(targets, width=160.0):
    """上にひし形（x=200, y=100）、下の段（y=250）に行き先を並べた図。"""
    boxes = {"d": box(200, 100, width, 50, "diamond")}
    edges = []
    for name, x, w in targets:
        boxes[name] = box(x, 250, w)
        edges.append(edge("d", name, label=name))
    return boxes, edges


class TestExits:
    def test_wide_targets_outside_the_vertices_use_the_left_and_right_vertices(self):
        boxes, edges = diamond_with([("L", 60, 80), ("R", 340, 80)])
        left, right = route_edges(boxes, edges, {})
        assert left.points[0] == (120.0, 100.0) and right.points[0] == (280.0, 100.0)     # ひし形の左右の頂点
        assert left.points[1] == (60.0, 100.0) and right.points[1] == (340.0, 100.0)      # 水平に出る
        assert left.points[-1] == (60.0, 235.0) and right.points[-1] == (340.0, 235.0)    # 行き先の真上から、垂直に入る

    def test_three_branches_use_left_bottom_and_right(self):
        boxes, edges = diamond_with([("L", 60, 80), ("M", 200, 80), ("R", 340, 80)])
        left, middle, right = route_edges(boxes, edges, {})
        assert left.points[0] == (120.0, 100.0)
        assert middle.points[0] == (200.0, 125.0) and middle.points == [(200.0, 125.0), (200.0, 235.0)]   # 下の頂点から、まっすぐ
        assert right.points[0] == (280.0, 100.0)

    def test_targets_inside_the_diamond_leave_from_the_bottom_vertex(self):
        """行き先が頂点より内側にあると、頂点から水平に出た線が、ひし形の中を通る。下の頂点を使い、水平に折れる高さをそろえる。"""
        boxes, edges = diamond_with([("L", 150, 70), ("R", 250, 70)])
        left, right = route_edges(boxes, edges, {})
        assert left.points[0] == right.points[0] == (200.0, 125.0)
        assert left.points[1][1] == right.points[2][1] == left.points[2][1]      # 折れる高さが同じ
        assert axis_aligned(left.points) and axis_aligned(right.points)

    def test_a_target_just_inside_a_vertex_goes_straight_down_from_it(self):
        boxes, edges = diamond_with([("L", 125, 80), ("R", 340, 80)])        # 左の行き先の中心は、頂点（120）の5ptの内側
        left, _ = route_edges(boxes, edges, {})
        assert left.points == [(120.0, 100.0), (120.0, 235.0)]


class TestLines:
    def test_every_segment_is_horizontal_or_vertical(self):
        boxes, edges = diamond_with([("L", 60, 80), ("M", 200, 80), ("R", 340, 80)])
        boxes["n"] = box(200, 400)
        edges += [edge(name, "n") for name in ("L", "M", "R")]
        assert all(axis_aligned(r.points) for r in route_edges(boxes, edges, {}))

    def test_lines_into_one_symbol_merge_into_a_single_line_with_one_arrow(self):
        boxes, edges = diamond_with([("L", 60, 80), ("R", 340, 80)])
        boxes["n"] = box(200, 400)
        edges += [edge("L", "n"), edge("R", "n")]
        routes = route_edges(boxes, edges, {})
        merging = routes[2:]
        assert [r.arrow for r in merging] == [True, False]                     # 矢じりは、入るところに1つだけ
        assert merging[0].points[-2:] == merging[1].points[-2:]                # 最後の区間が重なる
        merge_height = 385.0 - MERGE_GAP
        assert all(any(abs(p[1] - merge_height) < 0.01 for p in r.points) for r in merging)

    def test_a_straight_chain_is_a_vertical_line(self):
        boxes = {"a": box(100, 50), "b": box(100, 150)}
        (route,) = route_edges(boxes, [edge("a", "b")], {})
        assert route.points == [(100.0, 65.0), (100.0, 135.0)]

    def test_a_small_offset_between_centers_does_not_make_a_jog(self):
        boxes = {"a": box(100, 50), "b": box(100 + SNAP - 2, 150)}
        (route,) = route_edges(boxes, [edge("a", "b")], {})
        assert len(route.points) == 2 and route.points[0][0] == route.points[1][0] == boxes["b"].x

    def test_a_large_offset_makes_a_down_across_down_line(self):
        boxes = {"a": box(100, 50), "b": box(200, 150)}
        (route,) = route_edges(boxes, [edge("a", "b")], {})
        assert len(route.points) == 4 and axis_aligned(route.points)

    def test_an_arrow_flag_of_false_is_kept(self):
        boxes = {"a": box(100, 50), "b": box(100, 150)}
        (route,) = route_edges(boxes, [edge("a", "b", arrow=False)], {})
        assert route.arrow is False


class TestLabels:
    def test_branch_labels_sit_above_the_horizontal_part_on_their_own_side(self):
        boxes, edges = diamond_with([("L", 60, 80), ("R", 340, 80)])
        left, right = route_edges(boxes, edges, {0: (20, 12), 1: (20, 12)})
        assert left.label_pos[0] < 120.0 and right.label_pos[0] > 280.0
        assert left.label_pos[1] < 100.0 and right.label_pos[1] < 100.0        # 水平な線の上

    def test_labels_of_branches_that_share_a_stem_do_not_overlap(self):
        boxes, edges = diamond_with([("L", 150, 70), ("R", 250, 70)])
        left, right = route_edges(boxes, edges, {0: (24, 12), 1: (30, 12)})
        assert left.label_pos[0] + 12 <= 200.0 <= right.label_pos[0] - 15       # 幹の、左右に分かれる

    def test_a_straight_down_branch_label_sits_beside_the_line(self):
        boxes, edges = diamond_with([("M", 200, 80), ("R", 340, 80)])
        middle, _ = route_edges(boxes, edges, {0: (20, 12)})
        assert middle.label_pos[0] > 200.0

    def test_no_label_position_without_a_label(self):
        boxes, edges = diamond_with([("L", 60, 80), ("R", 340, 80)])
        assert all(r.label_pos is None for r in route_edges(boxes, edges, {}))


def _edge_paths(svg):
    """矢印の線（塗りなしのpath）の、頂点の並び。MとLだけでできていることも調べる。"""
    doc = xml.dom.minidom.parseString(svg)
    result = []
    for e in doc.getElementsByTagName("path"):
        if e.getAttribute("fill") != "none" or not e.getAttribute("stroke-width") == "1.2":
            continue
        d = e.getAttribute("d")
        assert re.fullmatch(r"M[-\d., ]+( L[-\d., ]+)*", d), d
        result.append([tuple(map(float, p.split(","))) for p in re.findall(r"[-\d.]+,[-\d.]+", d)])
    return result


class TestRender:
    CODE = "start\njudge 在庫がある?\n  はい: 出荷する\n  いいえ: 取り寄せる\n請求書を作る\nend\n"

    def test_every_line_of_the_notation_is_horizontal_or_vertical(self):
        svg = fn.render_svg(self.CODE)
        paths = _edge_paths(svg)
        assert len(paths) == 6 and all(axis_aligned(p) for p in paths)

    def test_the_merge_has_one_arrow_head_per_symbol(self):
        svg = fn.render_svg(self.CODE)
        heads = len(re.findall(r'<polygon points="[^"]+" fill="#333333"/>', svg))
        assert heads == 5          # 5つの記号（開始以外）に、1つずつ

    def test_the_decision_symbol_is_left_by_lines_from_its_vertices(self):
        chart = fn.parse("judge 判断?\n  はい: 一つ目の長い名前の処理\n  いいえ: 二つ目の長い名前の処理\n")
        placed = fr.layout(chart)
        diamond = placed["boxes"]["n1"]
        starts = {(round(r["points"][0][0], 1), round(r["points"][0][1], 1)) for r in placed["routes"]}
        vertices = {(round(diamond.x - diamond.width / 2, 1), round(diamond.y, 1)),
                    (round(diamond.x + diamond.width / 2, 1), round(diamond.y, 1)),
                    (round(diamond.x, 1), round(diamond.y + diamond.height / 2, 1))}
        assert starts <= vertices

    def test_mermaid_charts_keep_the_curves_of_the_layout(self):
        svg = fr.render_svg("flowchart TD\nA --> B{x}\nB --> C\nB --> D")
        doc = xml.dom.minidom.parseString(svg)
        curves = [e for e in doc.getElementsByTagName("path") if e.getAttribute("fill") == "none" and " C" in e.getAttribute("d")]
        assert curves

    def test_a_flowchart_marks_its_lines_as_orthogonal_and_a_mermaid_one_does_not(self):
        assert fn.parse("start\nend").orthogonal is True
        assert fr.parse("flowchart TD\nA --> B").orthogonal is False
