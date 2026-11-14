"""bizmodelのSVG出力（bizmodel_render.render_svg、#447）のテスト。"""
import xml.etree.ElementTree as ET

from text_compositor import bizmodel_render as bm

NS = {"s": "http://www.w3.org/2000/svg"}
BASIC = '''\
company Provider "配信事業者"
person User "ユーザー"
Provider -> User : goods "視聴権" / money "月額500円"
'''


def root(text):
    return ET.fromstring(bm.render_svg(text))


def texts(r):
    return ["".join(t.itertext()) for t in r.iter("{http://www.w3.org/2000/svg}text")]


class TestSvg:
    def test_is_well_formed_xml_with_a_viewbox(self):
        r = root(BASIC)
        assert r.tag == "{http://www.w3.org/2000/svg}svg"
        x, y, w, h = map(float, r.attrib["viewBox"].split())
        assert (x, y) == (0, 0) and w > 0 and h > 0

    def test_has_goods_and_money_marks(self):
        r = root(BASIC)
        assert "¥" in texts(r) and "視聴権" in texts(r) and "月額500円" in texts(r)
        assert len(r.findall(".//s:circle", NS)) == 2          # モノの円と、人型の頭
        assert len(r.findall(".//s:polygon", NS)) == 1         # 先端を塗りつぶした販売の矢印
        assert len(r.findall(".//s:polyline", NS)) == 1        # 先端が開いた支払の矢印

    def test_company_name_is_one_vertical_text(self):
        r = root(BASIC)
        (name,) = [t for t in r.iter("{http://www.w3.org/2000/svg}text") if t.text == "配信事業者"]
        assert name.attrib["writing-mode"] == "tb" and name.attrib["text-anchor"] == "middle"

    def test_a_bundle_adds_a_brace_and_a_timeline_adds_t(self):
        body = ('company S "企業"\nperson X "顧客"\n{kind} {{\n'
                '  S -> X : goods "A" / money "1円"\n  S -> X : goods "B" / money "2円"\n}}\n')
        bundled = root(body.format(kind="bundle"))
        timed = root(body.format(kind="timeline"))
        assert len(bundled.findall(".//s:path", NS)) == 2      # 人型の体と、波括弧
        assert "T" not in texts(bundled) and "T" in texts(timed)

    def test_xml_special_characters_are_escaped(self):
        text = BASIC.replace("視聴権", "A&B <c> \\\"d\\\"")
        r = root(text)
        assert 'A&B <c> "d"' in texts(r)

    def test_a_title_is_drawn_and_used_as_the_accessible_name(self):
        r = root('title "題名"\n' + BASIC)
        assert "題名" in texts(r) and r.find("s:title", NS).text == "題名"

    def test_the_output_is_deterministic(self):
        assert bm.render_svg(BASIC) == bm.render_svg(BASIC)

    def test_punctuation_and_the_long_vowel_mark_stay_in_the_same_vertical_text(self):
        r = root(BASIC.replace("配信事業者", "メーカー（株）「東京」"))
        assert "メーカー（株）「東京」" in texts(r)

    def test_a_long_company_name_shrinks_to_fit_the_rectangle(self):
        name = "とても長い名前の会社のサービス部門"
        r = root(BASIC.replace("配信事業者", name))
        (el,) = [t for t in r.iter("{http://www.w3.org/2000/svg}text") if t.text == name]
        assert float(el.attrib["font-size"]) < 14


class TestThreeOrMoreParties:
    CHAIN = ('company A "A"\ncompany B "B"\nperson X "X"\n'
             'A -> B : goods "g1" / money "m1"\nB -> X : goods "g2" / money "m2"\n')

    def test_a_chain_is_drawn_with_every_label_once(self):
        r = root(self.CHAIN)
        t = texts(r)
        for label in ("A", "B", "X", "g1", "m1", "g2", "m2"):
            assert t.count(label) == 1
        assert t.count("\u00a5") == 2   # yen mark per pair

    def test_the_cache_version_is_bumped(self):
        assert int(bm.CACHE_VERSION) >= 7

    def test_the_diagram_without_highlight_has_no_filled_shapes_except_arrowheads(self):
        r = root(BASIC)
        assert not any(e.get("fill") == "#111" for e in r.iter("{http://www.w3.org/2000/svg}rect"))
        assert not any(e.get("fill") == "#fff" for e in r.iter("{http://www.w3.org/2000/svg}text"))

    def test_highlighted_company_is_filled_with_white_text(self):
        r = root('company A "AAA"\nperson B "BBB"\nhighlight A\nA -> B : goods "g" / money "m"\n')
        rects = [e for e in r.iter("{http://www.w3.org/2000/svg}rect") if e.get("width") != "100%"]
        assert [e.get("fill") for e in rects] == ["#111"]
        white = [e for e in r.iter("{http://www.w3.org/2000/svg}text") if e.get("fill") == "#fff"]
        assert ["".join(e.itertext()) for e in white] == ["AAA"]

    def test_highlighted_person_is_filled_and_the_name_stays_dark(self):
        r = root('company A "AAA"\nperson B "BBB"\nhighlight B\nA -> B : goods "g" / money "m"\n')
        ns = "{http://www.w3.org/2000/svg}"
        assert [e.get("fill") for e in r.iter(ns + "circle") if e.get("r") == "13"] == ["#111"]
        assert [e.get("fill") for e in r.iter(ns + "path")] == ["#111"]
        assert not [e for e in r.iter(ns + "text") if e.get("fill") == "#fff"]

    def test_highlighted_money_has_a_dark_band_and_white_text(self):
        r = root('company A "a"\nperson B "b"\nA -> B : goods "g" / money "month 500" highlight\n')
        ns = "{http://www.w3.org/2000/svg}"
        bands = [e for e in r.iter(ns + "rect") if e.get("rx") == "4"]
        assert len(bands) == 1 and bands[0].get("fill") == "#111"
        white = [e for e in r.iter(ns + "text") if e.get("fill") == "#fff"]
        assert ["".join(e.itertext()) for e in white] == ["month 500"]

    def test_only_the_marked_trade_is_highlighted(self):
        text = ('company A "a"\ncompany B "b"\nbundle {\n'
                '  A -> B : goods "g1" / money "m1" highlight\n  A -> B : goods "g2" / money "m2"\n}\n')
        r = root(text)
        white = [e for e in r.iter("{http://www.w3.org/2000/svg}text") if e.get("fill") == "#fff"]
        assert ["".join(e.itertext()) for e in white] == ["m1"]

    def test_currency_defaults_to_yen(self):
        t = texts(root(BASIC))
        assert t.count("¥") == 1

    def test_currency_switches_the_money_mark(self):
        t = texts(root('currency "$"\n' + BASIC))
        assert t.count("$") == 1 and "¥" not in t

    def test_currency_applies_to_every_pair(self):
        text = ('currency "€"\ncompany A "a"\ncompany B "b"\ncompany C "c"\n'
                'A -> B : goods "g1" / money "m1"\nB -> C : goods "g2" / money "m2"\n')
        assert texts(root(text)).count("€") == 2

    def test_currency_is_escaped_in_the_svg(self):
        ET.fromstring(bm.render_svg('currency "<&>"\n' + BASIC))
