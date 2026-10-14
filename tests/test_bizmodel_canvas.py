"""bizmodelの記法2（ビジネスモデルキャンバス。`type canvas`、#458）のテスト。ブラウザも外部ツールも使わない。"""
import json
import xml.etree.ElementTree as ET

import pytest

from text_compositor import bizmodel_canvas as cv
from text_compositor import bizmodel_render as bm
from text_compositor.bizmodel_render import BizModelError

SRC = '''\
type canvas
title "ダイソー"
partners "メーカー"
value "手軽さ、安さ！"
value "全100円"
segments "一般顧客"
revenue "商品売り上げ"
'''
NS = {"s": "http://www.w3.org/2000/svg"}


def parse_error(text):
    with pytest.raises(BizModelError) as info:
        bm.parse(text)
    return info.value


def cell(layout, key):
    return next(c for c in layout.cells if c["key"] == key)


class TestParse:
    def test_items_are_collected_per_key_in_order(self):
        ast = bm.parse(SRC)
        assert ast["type"] == "canvas" and ast["title"] == "ダイソー"
        assert [i["text"] for i in ast["blocks"]["value"]] == ["手軽さ、安さ！", "全100円"]
        assert ast["blocks"]["value"][0]["line"] == 4

    def test_all_nine_keys_exist_in_the_fixed_order(self):
        ast = bm.parse(SRC)
        assert list(ast["blocks"]) == ["partners", "activities", "resources", "value", "relationships",
                                       "channels", "segments", "costs", "revenue"]
        assert ast["blocks"]["costs"] == []

    def test_the_ast_is_json_serializable(self):
        assert json.loads(json.dumps(bm.parse(SRC), ensure_ascii=False))["type"] == "canvas"

    def test_comments_blank_lines_and_free_order(self):
        text = '# 先頭のコメント\n\ntype canvas\nrevenue "A"  # 末尾\nvalue "B"\n'
        ast = bm.parse(text)
        assert ast["blocks"]["revenue"][0]["text"] == "A" and ast["blocks"]["value"][0]["text"] == "B"

    def test_flow_notation_is_still_the_default(self):
        assert bm.parse('company A "x"\nperson B "y"\nA -> B : goods "z" / money "1円"\n')["type"] == "flow"


class TestErrors:
    def test_e02_empty_item(self):
        e = parse_error('type canvas\nvalue ""\n')
        assert e.code == "E02" and e.line == 2

    def test_e06_unknown_key_lists_the_valid_keys(self):
        e = parse_error('type canvas\nbanana "x"\n')
        assert e.code == "E06" and "partners" in e.message and e.line == 2

    def test_e06_missing_text(self):
        assert parse_error("type canvas\nvalue\n").code == "E06"

    def test_e06_two_texts_on_a_line(self):
        assert parse_error('type canvas\nvalue "a" "b"\n').code == "E06"

    def test_e06_flow_statements_are_rejected_with_a_hint(self):
        e = parse_error('type canvas\ncompany A "x"\n')
        assert e.code == "E06" and "flow" in e.message
        assert parse_error('type canvas\nA -> B : goods "x" / money "1円"\n').code == "E06"

    def test_e06_title_twice_and_type_not_first(self):
        assert parse_error('type canvas\ntitle "a"\ntitle "b"\n').code == "E06"
        assert parse_error('type canvas\nvalue "a"\ntype canvas\n').code == "E06"

    def test_e08_no_item(self):
        assert parse_error('type canvas\ntitle "題"\n').code == "E08"


class TestWrap:
    def test_a_short_text_is_one_line(self):
        assert cv.wrap("一般顧客", 12, 158) == ["一般顧客"]

    def test_japanese_wraps_between_characters_within_the_width(self):
        lines = cv.wrap("あ" * 30, 12, 158)
        assert len(lines) > 1 and all(len(l) * 12 <= 158 for l in lines)

    def test_a_closing_mark_or_long_vowel_never_starts_a_line(self):
        for text in ("開発、運用、カスタマーサポート、マーケティング、採用、法務、経理など、多くの活動を継続して行う",
                     "あ" * 12 + "。" + "い" * 14 + "ー" + "う"):
            for line in cv.wrap(text, 12, 158)[1:]:
                assert line[0] not in "、。ー）」"

    def test_ascii_words_wrap_at_spaces_and_long_words_are_cut(self):
        lines = cv.wrap("alpha beta gamma delta epsilon zeta eta theta", 12, 80)
        assert len(lines) > 1 and all(" " not in l.strip() or len(l) > 0 for l in lines)
        cut = cv.wrap("x" * 60, 12, 80)
        assert len(cut) > 1 and "".join(cut) == "x" * 60


class TestLayout:
    def test_standard_grid_positions(self):
        lay = bm.layout(bm.parse(SRC))
        kp, ka, kr, vp = cell(lay, "partners"), cell(lay, "activities"), cell(lay, "resources"), cell(lay, "value")
        cr, ch, cs = cell(lay, "relationships"), cell(lay, "channels"), cell(lay, "segments")
        costs, rev = cell(lay, "costs"), cell(lay, "revenue")
        assert kp["x"] < ka["x"] < vp["x"] < cr["x"] < cs["x"]
        assert ka["x"] == kr["x"] and cr["x"] == ch["x"]
        assert kr["y"] == ka["y"] + ka["h"] and ch["y"] == cr["y"] + cr["h"]
        assert kp["h"] == vp["h"] == cs["h"] == ka["h"] + kr["h"]
        assert costs["y"] == kp["y"] + kp["h"] == rev["y"] and rev["x"] == costs["x"] + costs["w"]
        assert costs["w"] + rev["w"] == 5 * cv.COL_W

    def test_a_block_grows_with_its_content(self):
        many = SRC + "".join(f'resources "項目{i}"\n' for i in range(20))
        small, big = bm.layout(bm.parse(SRC)), bm.layout(bm.parse(many))
        assert cell(big, "resources")["h"] > cell(small, "resources")["h"]
        assert big.height > small.height

    def test_tall_spanning_block_distributes_the_extra_height(self):
        many = SRC + "".join(f'partners "項目{i}"\n' for i in range(30))
        lay = bm.layout(bm.parse(many))
        ka, kr, kp = cell(lay, "activities"), cell(lay, "resources"), cell(lay, "partners")
        assert ka["h"] + kr["h"] == kp["h"] and ka["h"] == kr["h"]

    def test_a_title_adds_space_on_top(self):
        titled = bm.layout(bm.parse(SRC))
        plain = bm.layout(bm.parse(SRC.replace('title "ダイソー"\n', "")))
        assert cell(titled, "partners")["y"] > cell(plain, "partners")["y"]


class TestSvg:
    def root(self, text=SRC):
        return ET.fromstring(bm.render_svg(text))

    def texts(self, r):
        return ["".join(t.itertext()) for t in r.iter("{http://www.w3.org/2000/svg}text")]

    def test_is_well_formed_with_nine_cells(self):
        r = self.root()
        assert r.tag == "{http://www.w3.org/2000/svg}svg"
        assert len(r.findall(".//s:rect", NS)) == 1 + 9   # 背景と、9つの枠

    def test_headings_and_items_are_drawn(self):
        t = self.texts(self.root())
        assert "価値提案（VP）" in t and "コスト構造（C$）" in t and "手軽さ、安さ！" in t and "メーカー" in t

    def test_the_credit_is_always_drawn_and_readable(self):
        r = self.root()
        credit = [e for e in r.iter("{http://www.w3.org/2000/svg}text") if "".join(e.itertext()) == cv.CREDIT]
        assert len(credit) == 1 and float(credit[0].attrib["font-size"]) >= cv.BODY_SIZE * 0.85
        assert "Strategyzer.com" in cv.CREDIT and "CC BY-SA 3.0" in cv.CREDIT

    def test_the_credit_is_below_every_cell(self):
        lay = bm.layout(bm.parse(SRC))
        assert lay.credit_y > max(c["y"] + c["h"] for c in lay.cells)

    def test_xml_special_characters_are_escaped(self):
        r = self.root('type canvas\nvalue "A&B <c>"\n')
        assert "A&B <c>" in "".join(self.texts(r))

    def test_the_output_is_deterministic(self):
        assert bm.render_svg(SRC) == bm.render_svg(SRC)
