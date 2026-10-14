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


class TestUnsupported:
    def test_two_sellers_are_not_supported_yet(self):
        head = 'company A "A"\ncompany B "B"\nperson X "X"\n'
        with pytest.raises(BizModelError) as info:
            lay('A -> X : goods "a" / money "1円"\nB -> X : goods "b" / money "1円"\n', head=head)
        assert info.value.code == "E09"

    def test_a_chain_is_not_supported_yet(self):
        head = 'company A "A"\ncompany B "B"\nperson X "X"\n'
        with pytest.raises(BizModelError) as info:
            lay('A -> B : goods "a" / money "1円"\nB -> X : goods "a" / money "2円"\n', head=head)
        assert info.value.code == "E09"

    def test_a_buyer_in_a_bundle_and_another_group_is_not_supported(self):
        body = ('bundle {\n  S -> X : goods "A" / money "1円"\n  S -> X : goods "B" / money "2円"\n}\n'
                'S -> X : goods "C" / money "3円"\n')
        with pytest.raises(BizModelError) as info:
            lay(body)
        assert info.value.code == "E09"
