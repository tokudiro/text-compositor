"""bizmodelのレイアウト（bizmodel_render.layout、#447）のテスト。座標の関係だけを検査する。"""
import pytest

from text_compositor import bizmodel_render as bm
from text_compositor.bizmodel_render import BizModelError

HEAD = 'company S "企業"\nperson X "顧客X"\nperson Y "顧客Y"\n'


def lay(body, head=HEAD):
    return bm.layout(bm.parse(head + body))


def actor(layout, actor_id):
    return next(a for a in layout.actors if a["id"] == actor_id)


class TestTwoParties:
    def test_the_seller_is_on_the_left_and_the_buyer_on_the_right(self):
        l = lay('S -> X : goods "商品" / money "100円"\n')
        assert actor(l, "S")["cx"] < l.pairs[0]["x1"] < l.pairs[0]["x2"] < actor(l, "X")["cx"]

    def test_everything_is_inside_the_canvas(self):
        l = lay('S -> X : goods "商品" / money "100円"\n')
        for a in l.actors:
            assert 0 <= a["x"] and a["x"] + a["w"] <= l.width
            assert 0 <= a["y"] and a["y"] + a["h"] <= l.height
        p = l.pairs[0]
        assert 0 <= p["x1"] and p["x2"] <= l.width and p["y"] + bm.PAIR_H <= l.height + bm.MARGIN

    def test_the_company_rectangle_spans_all_rows(self):
        l = lay('S -> X : goods "A" / money "1円"\nS -> Y : goods "B" / money "2円"\n')
        s = actor(l, "S")
        assert s["kind"] == "company" and s["h"] == 2 * bm.PAIR_H - 20

    def test_trades_are_stacked_at_equal_intervals(self):
        l = lay('S -> X : goods "A" / money "1円"\nS -> Y : goods "B" / money "2円"\n')
        assert l.pairs[1]["y"] - l.pairs[0]["y"] == bm.PAIR_H

    def test_separate_buyers_are_separate_symbols(self):
        l = lay('S -> X : goods "A" / money "1円"\nS -> Y : goods "B" / money "2円"\n')
        x, y = actor(l, "X"), actor(l, "Y")
        assert y["cy"] - x["cy"] == bm.PAIR_H and x["cx"] == y["cx"]

    def test_the_same_buyer_is_one_symbol(self):
        l = lay('S -> X : goods "A" / money "1円"\nS -> X : goods "B" / money "2円"\n')
        assert len([a for a in l.actors if a["id"] == "X"]) == 1 and len(l.pairs) == 2

    def test_rows_are_grouped_by_buyer(self):
        l = lay('S -> X : goods "A1" / money "1円"\nS -> Y : goods "B" / money "2円"\nS -> X : goods "A2" / money "3円"\n')
        assert [p["goods"] for p in l.pairs] == ["A1", "A2", "B"]


class TestOptions:
    BUNDLE = 'bundle {\n  S -> X : goods "A" / money "1円"\n  S -> X : goods "B" / money "2円"\n}\n'

    def test_a_bundle_has_a_brace_to_the_right_of_the_arrows(self):
        l = lay(self.BUNDLE)
        (brace,) = l.braces
        assert brace["x"] > l.pairs[0]["x2"] and actor(l, "X")["cx"] > brace["x"]
        assert brace["top"] < brace["bottom"] and not l.timelines

    def test_the_bundled_buyer_is_centered_on_the_brace(self):
        l = lay(self.BUNDLE)
        (brace,) = l.braces
        assert actor(l, "X")["cy"] == pytest.approx((brace["top"] + brace["bottom"]) / 2)

    def test_a_timeline_starts_below_the_buyer_and_goes_down(self):
        l = lay(self.BUNDLE.replace("bundle", "timeline"))
        (tl,) = l.timelines
        x = actor(l, "X")
        assert tl["x"] == x["cx"] and tl["y_from"] > x["cy"] and tl["y_to"] > tl["y_from"] and not l.braces
        assert x["cy"] < l.pairs[1]["y"]   # 買い手は、最初の取引の高さ

    def test_the_canvas_is_wider_with_a_bundle(self):
        plain = lay('S -> X : goods "A" / money "1円"\n')
        bundled = lay(self.BUNDLE)
        assert bundled.width > plain.width


class TestLabelsAndTitle:
    def test_a_long_label_widens_the_arrows(self):
        short = lay('S -> X : goods "商品" / money "1円"\n')
        long = lay('S -> X : goods "とても長い商品の名前をここに書きます" / money "1円"\n')
        assert long.pairs[0]["x2"] - long.pairs[0]["x1"] > short.pairs[0]["x2"] - short.pairs[0]["x1"]

    def test_a_title_adds_space_on_top(self):
        plain = lay('S -> X : goods "A" / money "1円"\n')
        titled = lay('S -> X : goods "A" / money "1円"\n', head='title "題"\n' + HEAD)
        assert titled.title == "題" and titled.pairs[0]["y"] > plain.pairs[0]["y"]

    def test_a_person_seller_and_a_company_buyer(self):
        head = 'person P "個人"\ncompany C "法人"\n'
        l = lay('P -> C : goods "仕事" / money "1万円"\n', head=head)
        assert actor(l, "P")["kind"] == "person" and actor(l, "C")["kind"] == "company"


CHAIN_HEAD = 'company A "メーカー"\ncompany B "卸"\ncompany C "小売"\nperson X "顧客"\n'
CHAIN = ('A -> B : goods "商品" / money "100円"\nB -> C : goods "商品" / money "150円"\n'
         'C -> X : goods "商品" / money "200円"\n')


class TestChain:
    """一列（A → B → C → X）。列は取引の向きに沿って、左から右へ増える。"""

    def test_columns_increase_from_left_to_right(self):
        l = lay(CHAIN, head=CHAIN_HEAD)
        xs = [actor(l, i)["cx"] for i in "ABCX"]
        assert xs == sorted(xs) and len(set(xs)) == 4

    def test_each_arrow_pair_sits_between_its_two_companies(self):
        l = lay(CHAIN, head=CHAIN_HEAD)
        for p, (s, b) in zip(l.pairs, [("A", "B"), ("B", "C"), ("C", "X")]):
            assert actor(l, s)["cx"] < p["x1"] < p["x2"] < actor(l, b)["cx"]

    def test_a_middle_company_is_both_a_buyer_and_a_seller(self):
        l = lay(CHAIN, head=CHAIN_HEAD)
        b = actor(l, "B")
        assert b["kind"] == "company" and b["h"] == bm.PAIR_H - 20
        assert l.pairs[0]["y"] == l.pairs[1]["y"]   # 同じ高さに並ぶ

    def test_everything_is_inside_the_canvas(self):
        l = lay(CHAIN, head=CHAIN_HEAD)
        for a in l.actors:
            assert 0 <= a["x"] and a["x"] + a["w"] <= l.width
        assert max(p["x2"] for p in l.pairs) <= l.width

    def test_the_order_of_the_statements_does_not_matter(self):
        lines = CHAIN.splitlines(keepends=True)
        a = lay("".join(lines), head=CHAIN_HEAD)
        b = lay("".join(reversed(lines)), head=CHAIN_HEAD)
        assert [actor(a, i)["cx"] for i in "ABCX"] == [actor(b, i)["cx"] for i in "ABCX"]


class TestPlatform:
    """複数の供給者 → 企業 → 複数の顧客。企業の高さは、取引の多いほうに合わせる。"""

    HEAD = 'person S1 "供給者1"\nperson S2 "供給者2"\ncompany P "基盤"\nperson X "顧客X"\nperson Y "顧客Y"\nperson Z "顧客Z"\n'
    BODY = ('S1 -> P : goods "a" / money "1円"\nS2 -> P : goods "b" / money "2円"\n'
            'P -> X : goods "c" / money "3円"\nP -> Y : goods "d" / money "4円"\nP -> Z : goods "e" / money "5円"\n')

    def test_the_platform_spans_the_taller_side(self):
        l = lay(self.BODY, head=self.HEAD)
        assert actor(l, "P")["h"] == 3 * bm.PAIR_H - 20

    def test_the_shorter_side_is_centered(self):
        l = lay(self.BODY, head=self.HEAD)
        left, right = l.pairs[:2], l.pairs[2:]
        mid_left = (left[0]["y"] + left[1]["y"] + bm.PAIR_H) / 2
        mid_right = (right[0]["y"] + right[2]["y"] + bm.PAIR_H) / 2
        assert mid_left == pytest.approx(mid_right)

    def test_suppliers_share_a_column_and_customers_share_a_column(self):
        l = lay(self.BODY, head=self.HEAD)
        assert actor(l, "S1")["cx"] == actor(l, "S2")["cx"] < actor(l, "P")["cx"]
        assert actor(l, "P")["cx"] < actor(l, "X")["cx"] == actor(l, "Y")["cx"] == actor(l, "Z")["cx"]

    def test_a_supplier_used_only_on_the_right_is_placed_next_to_its_buyer(self):
        head = 'company A "A"\ncompany B "B"\ncompany C "C"\ncompany D "D"\nperson X "X"\n'
        body = ('A -> B : goods "a" / money "1円"\nB -> C : goods "b" / money "2円"\n'
                'D -> C : goods "d" / money "3円"\nC -> X : goods "c" / money "4円"\n')
        l = lay(body, head=head)
        assert actor(l, "D")["cx"] == actor(l, "B")["cx"]

    def test_a_bundle_into_a_middle_company(self):
        head = 'company A "A"\ncompany B "B"\nperson X "X"\n'
        body = ('bundle {\n  A -> B : goods "a" / money "1円"\n  A -> B : goods "b" / money "2円"\n}\n'
                'B -> X : goods "c" / money "3円"\n')
        l = lay(body, head=head)
        (brace,) = l.braces
        assert l.pairs[0]["x2"] < brace["x"] < actor(l, "B")["cx"]
        assert actor(l, "B")["h"] == 2 * bm.PAIR_H - 20


class TestSkipColumn:
    """列を飛ばす取引（メーカー → 顧客の直販など）は、中間の企業の下の行を、横に渡す（#524）。"""
    HEAD3 = 'company Maker "メーカー"\ncompany Shop "小売"\nperson User "顧客"\n'
    BODY3 = ('Maker -> Shop : goods "商品" / money "卸値"\nShop -> User : goods "商品" / money "定価"\n'
             'Maker -> User : goods "直販品" / money "直販価格"\n')

    def test_the_diagram_is_laid_out_and_rendered(self):
        text = self.HEAD3 + self.BODY3
        import xml.etree.ElementTree as ET
        ET.fromstring(bm.render_svg(text))
        assert len(bm.layout(bm.parse(text)).pairs) == 3

    def test_the_skipping_arrow_runs_in_a_row_below_the_middle_company(self):
        l = lay(self.BODY3, head=self.HEAD3)
        direct = next(p for p in l.pairs if p["goods"] == "直販品")
        shop = actor(l, "Shop")
        assert direct["y"] >= shop["y"] + shop["h"]            # 小売の長方形の下の行
        assert direct["y"] == max(p["y"] for p in l.pairs)     # 通常の行より下

    def test_the_arrow_does_not_touch_the_middle_company(self):
        l = lay(self.BODY3, head=self.HEAD3)
        direct = next(p for p in l.pairs if p["goods"] == "直販品")
        shop = actor(l, "Shop")
        # 矢印の行（記号を含めた高さ）が、小売の長方形・名前の範囲と、縦に重ならない
        assert direct["y"] > shop["y"] + shop["h"] - 1

    def test_the_arrow_spans_from_the_seller_to_the_buyer(self):
        l = lay(self.BODY3, head=self.HEAD3)
        direct = next(p for p in l.pairs if p["goods"] == "直販品")
        maker, user = actor(l, "Maker"), actor(l, "User")
        first, last = l.pairs[0], l.pairs[1]
        assert maker["cx"] < direct["x1"] == first["x1"]
        assert direct["x2"] == last["x2"] < user["cx"]

    def test_the_end_companies_cover_the_extra_row(self):
        l = lay(self.BODY3, head=self.HEAD3)
        direct = next(p for p in l.pairs if p["goods"] == "直販品")
        maker = actor(l, "Maker")
        assert maker["y"] + maker["h"] >= direct["y"] + bm.PAIR_H - 20 - 1

    def test_the_canvas_holds_the_extra_row(self):
        l = lay(self.BODY3, head=self.HEAD3)
        direct = next(p for p in l.pairs if p["goods"] == "直販品")
        assert direct["y"] + bm.PAIR_H <= l.height + bm.MARGIN
        assert 0 <= direct["x1"] and direct["x2"] <= l.width

    def test_each_skipping_trade_has_its_own_row(self):
        body = self.BODY3 + 'Maker -> User : goods "直販品2" / money "価格2"\n'
        l = lay(body, head=self.HEAD3)
        ys = sorted(p["y"] for p in l.pairs if p["goods"].startswith("直販品"))
        assert len(ys) == 2 and ys[1] - ys[0] == bm.PAIR_H

    def test_a_trade_can_skip_two_columns(self):
        head = 'company A "A"\ncompany B "B"\ncompany C "C"\nperson D "D"\n'
        body = ('A -> B : goods "a" / money "1円"\nB -> C : goods "b" / money "2円"\nC -> D : goods "c" / money "3円"\n'
                'A -> D : goods "z" / money "9円"\n')
        l = lay(body, head=head)
        z = next(p for p in l.pairs if p["goods"] == "z")
        for mid in ("B", "C"):
            a = actor(l, mid)
            assert z["y"] >= a["y"] + a["h"]
        assert z["x1"] == l.pairs[0]["x1"] and z["x2"] == l.pairs[2]["x2"]

    def test_diagrams_without_a_skipping_trade_are_unchanged(self):
        body = 'Maker -> Shop : goods "商品" / money "卸値"\nShop -> User : goods "商品" / money "定価"\n'
        l = lay(body, head=self.HEAD3)
        assert l.height == bm.MARGIN + bm.PAIR_H + bm.MARGIN - 10


class TestUnsupported:
    def head(self):
        return 'company A "A"\ncompany B "B"\ncompany C "C"\nperson X "X"\n'

    def test_a_bundle_that_skips_a_column_is_not_supported(self):
        body = ('A -> B : goods "a" / money "1円"\nB -> C : goods "a" / money "2円"\n'
                'bundle {\n  A -> C : goods "x" / money "3円"\n  A -> C : goods "y" / money "4円"\n}\n')
        with pytest.raises(BizModelError) as info:
            lay(body, head=self.head())
        assert info.value.code == "E09" and "skips" in info.value.message

    def test_interleaved_skipping_trades_are_not_supported(self):
        # A -> C と B -> D は、互いの企業（B・C）の下を通るため、矢印が企業を貫く
        head = 'company A "A"\ncompany B "B"\ncompany C "C"\nperson D "D"\n'
        body = ('A -> B : goods "a" / money "1円"\nB -> C : goods "b" / money "2円"\nC -> D : goods "c" / money "3円"\n'
                'A -> C : goods "d" / money "4円"\nB -> D : goods "e" / money "5円"\n')
        with pytest.raises(BizModelError) as info:
            lay(body, head=head)
        assert info.value.code == "E09" and "pass through" in info.value.message

    def test_a_circle_is_not_supported_yet(self):
        body = 'A -> B : goods "a" / money "1円"\nB -> A : goods "a" / money "2円"\n'
        with pytest.raises(BizModelError) as info:
            lay(body, head=self.head())
        assert info.value.code == "E09" and "circle" in info.value.message

    def test_crossing_arrows_are_not_supported_yet(self):
        body = ('A -> B : goods "a" / money "1円"\nA -> C : goods "a" / money "2円"\n'
                'X -> B : goods "a" / money "3円"\n')
        with pytest.raises(BizModelError) as info:
            lay(body, head=self.head())
        assert info.value.code == "E09" and "cross" in info.value.message

    def test_a_timeline_buyer_that_also_sells_is_not_supported_yet(self):
        body = ('timeline {\n  A -> B : goods "a" / money "1円"\n  A -> B : goods "b" / money "2円"\n}\n'
                'B -> X : goods "c" / money "3円"\n')
        with pytest.raises(BizModelError) as info:
            lay(body, head=self.head())
        assert info.value.code == "E09" and "timeline" in info.value.message

    def test_a_buyer_in_a_bundle_and_another_group_is_not_supported(self):
        body = ('bundle {\n  S -> X : goods "A" / money "1円"\n  S -> X : goods "B" / money "2円"\n}\n'
                'S -> X : goods "C" / money "3円"\n')
        with pytest.raises(BizModelError) as info:
            lay(body)
        assert info.value.code == "E09"
