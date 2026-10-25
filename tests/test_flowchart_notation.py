"""JIS X 0121に準じたフローチャートの独自記法（flowchart_notation.py。#536）の解析のテスト。"""
import xml.dom.minidom

import pytest

from text_compositor import flowchart_notation as fn
from text_compositor.flowchart_render import FlowchartError


def shapes(chart):
    return [(n.label, n.shape) for n in chart.nodes.values()]


def links(chart):
    """矢印を、(元の文字, 先の文字, 矢印の文字)にする。idではなく文字で比べる。"""
    label = {i: n.label + ("/" + n.shape if n.shape.startswith("loop") else "") for i, n in chart.nodes.items()}
    return [(label[e.source], label[e.target], e.label) for e in chart.edges]


class TestSymbols:
    def test_keywords_map_to_shapes(self):
        chart = fn.parse("start\ndata 入力\nprocess 計算\nsub 呼ぶ\nprep 初期化\ndoc 帳票\nterminal 中断\nend")
        assert shapes(chart) == [
            ("start", "stadium"), ("入力", "parallelogram"), ("計算", "rect"), ("呼ぶ", "subroutine"),
            ("初期化", "hexagon"), ("帳票", "document"), ("中断", "stadium"), ("end", "stadium")]

    def test_a_line_without_a_keyword_is_a_process(self):
        chart = fn.parse("消費税を計算する")
        assert shapes(chart) == [("消費税を計算する", "rect")]

    def test_start_and_end_show_their_own_word_when_text_is_omitted(self):
        assert fn.parse("start\nend").nodes["n1"].label == "start"
        assert fn.parse("start 開始\nend 終了").nodes["n2"].label == "終了"

    def test_other_keywords_need_text(self):
        with pytest.raises(FlowchartError, match="'data' needs text") as e:
            fn.parse("start\ndata")
        assert e.value.line == 2

    def test_quotes_avoid_a_keyword_collision(self):
        chart = fn.parse('"data cleanup を実行する"\nprocess data cleanup を実行する\ndata "end user に通知する"')
        assert shapes(chart) == [
            ("data cleanup を実行する", "rect"), ("data cleanup を実行する", "rect"), ("end user に通知する", "parallelogram")]

    def test_escapes(self):
        chart = fn.parse('二行に\\nする\n"引用\\"符\\"と\\n改行"')
        assert [n.label for n in chart.nodes.values()] == ["二行に\nする", '引用"符"と\n改行']

    def test_a_keyword_must_be_followed_by_a_space(self):
        assert shapes(fn.parse("datastore を更新")) == [("datastore を更新", "rect")]

    def test_blank_lines_and_comments_are_ignored(self):
        chart = fn.parse("// 注釈\nstart\n\n  \n// もう一つ\nend")
        assert [n.label for n in chart.nodes.values()] == ["start", "end"]

    def test_symbols_are_chained_top_to_bottom(self):
        assert links(fn.parse("start\n処理A\ndata 出力\nend")) == [
            ("start", "処理A", ""), ("処理A", "出力", ""), ("出力", "end", "")]

    def test_nothing_follows_an_end(self):
        chart = fn.parse("start\nend\n後ろ")
        assert links(chart) == [("start", "end", "")]


class TestJudge:
    def test_branches_merge_at_the_next_line(self):
        chart = fn.parse("judge 在庫がある?\n  はい: 出荷する\n  いいえ: 取り寄せる\n請求書を作る")
        assert links(chart) == [
            ("在庫がある?", "出荷する", "はい"), ("在庫がある?", "取り寄せる", "いいえ"),
            ("出荷する", "請求書を作る", ""), ("取り寄せる", "請求書を作る", "")]
        assert chart.nodes["n1"].shape == "diamond"

    def test_a_branch_can_continue_on_deeper_lines(self):
        chart = fn.parse("judge 在庫がある?\n  はい:\n    出荷する\n    data 通知を表示\n  いいえ: 取り寄せる\n終わり")
        assert links(chart) == [
            ("在庫がある?", "出荷する", "はい"), ("出荷する", "通知を表示", ""),
            ("在庫がある?", "取り寄せる", "いいえ"),
            ("通知を表示", "終わり", ""), ("取り寄せる", "終わり", "")]

    def test_a_branch_with_a_symbol_and_deeper_lines(self):
        chart = fn.parse("judge a?\n  はい: 一つ目\n    二つ目\n  いいえ: 別\n次")
        assert ("一つ目", "二つ目", "") in links(chart)

    def test_an_empty_branch_goes_straight_to_the_next_symbol(self):
        chart = fn.parse("judge 必要?\n  はい: 処理する\n  いいえ:\n次へ")
        assert ("必要?", "次へ", "いいえ") in links(chart)
        assert ("処理する", "次へ", "") in links(chart)

    def test_a_branch_ending_with_end_does_not_merge(self):
        chart = fn.parse("judge 承認?\n  はい: 続ける\n  却下: end 却下\n次")
        assert links(chart) == [
            ("承認?", "続ける", "はい"), ("承認?", "却下", "却下"), ("続ける", "次", "")]

    def test_three_branches_and_nesting(self):
        chart = fn.parse("judge x?\n  A: 処理A\n  B:\n    judge y?\n      はい: 処理B1\n      いいえ: 処理B2\n  C: 処理C\n合流")
        merged = [(s, t) for s, t, _ in links(chart) if t == "合流"]
        assert sorted(merged) == [("処理A", "合流"), ("処理B1", "合流"), ("処理B2", "合流"), ("処理C", "合流")]

    def test_a_judge_inline_after_a_branch_label(self):
        chart = fn.parse("judge a?\n  はい: judge b?\n    はい: X\n    いいえ: Y\n  いいえ: Z\n次")
        assert ("b?", "X", "はい") in links(chart) and ("Z", "次", "") in links(chart)

    def test_one_branch_is_an_error(self):
        with pytest.raises(FlowchartError, match="at least two branches") as e:
            fn.parse("start\njudge 1つだけ?\n  はい: 処理")
        assert e.value.line == 2

    def test_a_judge_without_branches_is_an_error(self):
        with pytest.raises(FlowchartError, match="at least two branches"):
            fn.parse("judge どうする?\n次")

    def test_a_line_without_a_label_in_the_branches_is_an_error(self):
        with pytest.raises(FlowchartError, match="'label:'") as e:
            fn.parse("judge a?\n  はい: X\n  ラベルなし")
        assert e.value.line == 3

    def test_judge_needs_text(self):
        with pytest.raises(FlowchartError, match="'judge' needs text"):
            fn.parse("judge")


class TestLoop:
    def test_a_loop_pair_with_the_same_name_and_the_condition_at_the_start(self):
        chart = fn.parse("loop 注文処理: 注文がなくなるまで\n  注文を1件処理する\nendloop\n終わり")
        assert [(n.label, n.shape, n.condition) for n in chart.nodes.values()] == [
            ("注文処理", "loop_start", "注文がなくなるまで"), ("注文を1件処理する", "rect", ""),
            ("注文処理", "loop_end", ""), ("終わり", "rect", "")]
        assert links(chart) == [
            ("注文処理/loop_start", "注文を1件処理する", ""),
            ("注文を1件処理する", "注文処理/loop_end", ""),
            ("注文処理/loop_end", "終わり", "")]

    def test_the_condition_at_the_end(self):
        chart = fn.parse("loop 入力待ち\n  data 入力\nendloop: 入力が正しいまで")
        start, _, end = chart.nodes.values()
        assert start.condition == "" and end.condition == "入力が正しいまで" and end.label == "入力待ち"

    def test_a_loop_without_a_condition(self):
        chart = fn.parse("loop 主ループ\n  処理\nendloop")
        assert [n.condition for n in chart.nodes.values()] == ["", "", ""]

    def test_no_back_arrow_is_drawn(self):
        chart = fn.parse("loop L: 条件\n  処理\nendloop")
        assert len(chart.edges) == 2

    def test_an_empty_body(self):
        chart = fn.parse("loop L\nendloop")
        assert links(chart) == [("L/loop_start", "L/loop_end", "")]

    def test_nested_loops_and_a_judge_inside(self):
        chart = fn.parse(
            "loop 外: 外の条件\n  loop 内: 内の条件\n    judge x?\n      はい: A\n      いいえ: B\n  endloop\nendloop\n後")
        assert ("内/loop_end", "外/loop_end", "") in links(chart)
        assert ("A", "内/loop_end", "") in links(chart) and ("B", "内/loop_end", "") in links(chart)

    def test_a_loop_inside_a_branch(self):
        chart = fn.parse("judge x?\n  はい:\n    loop L: c\n      処理\n    endloop\n  いいえ: 何もしない\n次")
        assert ("L/loop_end", "次", "") in links(chart) and ("x?", "L/loop_start", "はい") in links(chart)

    def test_a_quoted_name_may_contain_a_colon(self):
        chart = fn.parse('loop "時刻: 毎時": 止めるまで\n  処理\nendloop')
        start = chart.nodes["n1"]
        assert (start.label, start.condition) == ("時刻: 毎時", "止めるまで")

    def test_the_condition_at_both_ends_is_an_error(self):
        with pytest.raises(FlowchartError, match="either the start or the end") as e:
            fn.parse("loop L: 始め\n  処理\nendloop: 終わり")
        assert e.value.line == 3

    def test_a_missing_endloop_is_an_error(self):
        with pytest.raises(FlowchartError, match="no matching endloop") as e:
            fn.parse("start\nloop L: c\n  処理")
        assert e.value.line == 2

    def test_an_endloop_without_a_loop_is_an_error(self):
        with pytest.raises(FlowchartError, match="no matching loop") as e:
            fn.parse("処理\nendloop")
        assert e.value.line == 2

    def test_a_loop_needs_a_name(self):
        with pytest.raises(FlowchartError, match="needs a name"):
            fn.parse("loop\n  処理\nendloop")
        with pytest.raises(FlowchartError, match="needs a name"):
            fn.parse("loop : 条件だけ\n  処理\nendloop")

    def test_endloop_takes_no_name(self):
        with pytest.raises(FlowchartError, match="takes no name"):
            fn.parse("loop L\n  処理\nendloop L")

    def test_a_nested_loop_may_not_reuse_an_enclosing_name(self):
        with pytest.raises(FlowchartError, match="already used") as e:
            fn.parse("loop L\n  loop L\n    処理\n  endloop\nendloop")
        assert e.value.line == 2

    def test_sibling_loops_may_share_a_name(self):
        chart = fn.parse("loop L\n  処理\nendloop\nloop L\n  処理\nendloop")
        assert len(chart.nodes) == 6

    def test_loop_after_a_branch_label_must_be_on_its_own_line(self):
        with pytest.raises(FlowchartError, match="own lines"):
            fn.parse("judge x?\n  はい: loop L\n  いいえ: 何か")


class TestIndentationAndErrors:
    def test_tabs_are_an_error(self):
        with pytest.raises(FlowchartError, match="Tabs") as e:
            fn.parse("judge x?\n\tはい: A\n\tいいえ: B")
        assert e.value.line == 2

    def test_the_indent_unit_is_set_by_the_first_indent(self):
        fn.parse("judge x?\n    はい: A\n    いいえ: B")           # 4つでもよい
        with pytest.raises(FlowchartError, match="multiple of 4") as e:
            fn.parse("judge x?\n    はい: A\n      いいえ: B")
        assert e.value.line == 3

    def test_an_unexpected_indent_is_an_error(self):
        with pytest.raises(FlowchartError, match="Unexpected indentation") as e:
            fn.parse("start\n  処理")
        assert e.value.line == 2

    def test_the_first_line_may_not_be_indented(self):
        with pytest.raises(FlowchartError, match="first line"):
            fn.parse("  start")

    def test_an_unclosed_quote_is_an_error(self):
        with pytest.raises(FlowchartError, match="Unclosed quote") as e:
            fn.parse('start\n"閉じ忘れ')
        assert e.value.line == 2

    def test_text_after_a_closing_quote_is_an_error(self):
        with pytest.raises(FlowchartError, match="after the closing quote"):
            fn.parse('"処理" 余分')

    def test_an_empty_diagram_is_an_error(self):
        for code in ("", "\n  \n// 注釈だけ"):
            with pytest.raises(FlowchartError, match="empty"):
                fn.parse(code)


def _polygons(svg):
    """SVGの多角形を、頂点の並び[(x, y), ...]にして返す。"""
    doc = xml.dom.minidom.parseString(svg)
    return [[tuple(map(float, p.split(","))) for p in e.getAttribute("points").split()]
            for e in doc.getElementsByTagName("polygon")]


def _texts(svg):
    doc = xml.dom.minidom.parseString(svg)
    return [e.firstChild.data for e in doc.getElementsByTagName("text")]


class TestRender:
    def test_loop_limits_have_two_cut_corners_on_the_inner_side(self):
        """始端は上の2つの角、終端は下の2つの角を落とす（JIS X 0121 8.2.2(6)）。"""
        svg = fn.render_svg("loop L\n  処理\nendloop")
        hexes = [p for p in _polygons(svg) if len(p) == 6]
        start, end = sorted(hexes, key=lambda p: min(y for _, y in p))     # 上にある方が、始端
        top, bottom = min(y for _, y in start), max(y for _, y in start)
        top_edge = [x for x, y in start if y == top]
        bottom_edge = [x for x, y in start if y == bottom]
        assert max(top_edge) - min(top_edge) < max(bottom_edge) - min(bottom_edge)      # 始端: 上の辺が短い
        top, bottom = min(y for _, y in end), max(y for _, y in end)
        top_edge = [x for x, y in end if y == top]
        bottom_edge = [x for x, y in end if y == bottom]
        assert max(top_edge) - min(top_edge) > max(bottom_edge) - min(bottom_edge)      # 終端: 下の辺が短い

    def test_the_loop_name_is_drawn_at_both_ends_and_the_condition_at_one(self):
        texts = _texts(fn.render_svg("loop 注文処理: 注文がなくなるまで\n  処理\nendloop"))
        assert texts.count("注文処理") == 2 and texts.count("注文がなくなるまで") == 1

    def test_the_condition_at_the_end_is_drawn_in_the_end_symbol(self):
        svg = fn.render_svg("loop 入力待ち\n  処理\nendloop: 正しいまで")
        texts = _texts(svg)
        assert texts.count("入力待ち") == 2 and texts.index("正しいまで") > texts.index("処理")

    def test_a_document_has_a_wavy_bottom(self):
        svg = fn.render_svg("doc 帳票を出力")
        doc = xml.dom.minidom.parseString(svg)
        paths = [e.getAttribute("d") for e in doc.getElementsByTagName("path")]
        assert any(d.startswith("M") and " C" in d and d.endswith("Z") for d in paths)

    def test_every_symbol_renders_as_valid_svg(self):
        svg = fn.render_svg(
            "start\nprep 準備\ndata 入力\nsub 呼ぶ\ndoc 帳票\njudge 続ける?\n  はい: 処理\n  いいえ: terminal 中断\nend")
        xml.dom.minidom.parseString(svg)
        assert "<svg" in svg and "続ける?" in _texts(svg)

    def test_errors_are_reported_with_the_line_when_rendering(self):
        with pytest.raises(FlowchartError) as e:
            fn.render_svg("start\nloop L")
        assert e.value.line == 2


def test_the_example_in_the_design_doc():
    chart = fn.parse(
        "start\n"
        "loop 10回まで\n"
        "  data 金額を入力\n"
        "  消費税を計算する\n"
        "  judge 1万円以上?\n"
        "    はい: 送料を無料にする\n"
        "    いいえ: 送料を加算する\n"
        "  data 合計を表示\n"
        "endloop\n"
        "end\n")
    assert links(chart) == [
        ("start", "10回まで/loop_start", ""),
        ("10回まで/loop_start", "金額を入力", ""),
        ("金額を入力", "消費税を計算する", ""),
        ("消費税を計算する", "1万円以上?", ""),
        ("1万円以上?", "送料を無料にする", "はい"),
        ("1万円以上?", "送料を加算する", "いいえ"),
        ("送料を無料にする", "合計を表示", ""),
        ("送料を加算する", "合計を表示", ""),
        ("合計を表示", "10回まで/loop_end", ""),
        ("10回まで/loop_end", "end", "")]
