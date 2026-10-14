"""bizmodelのDSLの構文解析（bizmodel_render.parse、#447）のテスト。ブラウザも外部ツールも使わない。"""
import json

import pytest

from text_compositor import bizmodel_render as bm
from text_compositor.bizmodel_render import BizModelError

BASIC = '''\
title "サブスクリプション型"
company Provider "配信事業者"
person User "ユーザー"
Provider -> User : goods "視聴権" / money "月額500円"
'''


def parse_error(text):
    with pytest.raises(BizModelError) as info:
        bm.parse(text)
    return info.value


class TestParseOk:
    def test_basic_trade(self):
        ast = bm.parse(BASIC)
        assert ast["type"] == "flow" and ast["title"] == "サブスクリプション型"
        assert [(a["id"], a["kind"], a["label"]) for a in ast["actors"]] == [
            ("Provider", "company", "配信事業者"), ("User", "person", "ユーザー")]
        (group,) = ast["groups"]
        assert group["kind"] == "single"
        t = group["trades"][0]
        assert (t["seller"], t["buyer"], t["goods"], t["money"]) == ("Provider", "User", "視聴権", "月額500円")

    def test_the_ast_is_json_serializable(self):
        assert json.loads(json.dumps(bm.parse(BASIC), ensure_ascii=False))["actors"][0]["id"] == "Provider"

    def test_type_flow_is_accepted_and_optional(self):
        assert bm.parse("type flow\n" + BASIC)["type"] == "flow"

    def test_money_before_goods_is_accepted(self):
        text = BASIC.replace('goods "視聴権" / money "月額500円"', 'money "月額500円" / goods "視聴権"')
        t = bm.parse(text)["groups"][0]["trades"][0]
        assert (t["goods"], t["money"]) == ("視聴権", "月額500円")

    def test_comments_and_blank_lines(self):
        text = "# 全体のコメント\n\n" + BASIC.replace('"月額500円"', '"月額500円"  # 末尾のコメント')
        assert bm.parse(text)["groups"][0]["trades"][0]["money"] == "月額500円"

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        text = BASIC.replace("視聴権", "No.#1 視聴権")
        assert bm.parse(text)["groups"][0]["trades"][0]["goods"] == "No.#1 視聴権"

    def test_unknown_and_free_values_are_plain_strings(self):
        text = BASIC.replace('"月額500円"', '"？円"')
        assert bm.parse(text)["groups"][0]["trades"][0]["money"] == "？円"
        text = BASIC.replace('"月額500円"', '"0円"')
        assert bm.parse(text)["groups"][0]["trades"][0]["money"] == "0円"

    def test_escaped_quote_in_a_string(self):
        text = BASIC.replace("視聴権", r"\"特別\"視聴権")
        assert bm.parse(text)["groups"][0]["trades"][0]["goods"] == '"特別"視聴権'

    def test_bundle_and_timeline_groups(self):
        text = '''\
company Maker "企業"
person Customer "顧客"
bundle {
  Maker -> Customer : goods "商品A" / money "100円"
  Maker -> Customer : goods "商品B" / money "200円"
}
'''
        (group,) = bm.parse(text)["groups"]
        assert group["kind"] == "bundle" and len(group["trades"]) == 2
        group = bm.parse(text.replace("bundle", "timeline"))["groups"][0]
        assert group["kind"] == "timeline"


class TestErrors:
    def test_e01_money_is_missing(self):
        e = parse_error(BASIC.replace(' / money "月額500円"', ""))
        assert e.code == "E01" and e.line == 4

    def test_e01_goods_is_missing(self):
        e = parse_error(BASIC.replace('goods "視聴権" / ', ""))
        assert e.code == "E01" and e.line == 4

    def test_e02_empty_money(self):
        e = parse_error(BASIC.replace('"月額500円"', '""'))
        assert e.code == "E02" and e.line == 4 and e.column is not None

    def test_e03_undeclared_id(self):
        e = parse_error(BASIC.replace("-> User", "-> Nobody"))
        assert e.code == "E03" and e.line == 4

    def test_e04_same_seller_and_buyer(self):
        e = parse_error(BASIC.replace("-> User", "-> Provider"))
        assert e.code == "E04"

    def test_e05_block_with_different_buyers(self):
        text = '''\
company A "売り手"
person X "顧客X"
person Y "顧客Y"
bundle {
  A -> X : goods "商品" / money "1円"
  A -> Y : goods "商品" / money "1円"
}
'''
        e = parse_error(text)
        assert e.code == "E05" and e.line == 4

    def test_e05_block_with_one_trade(self):
        text = ('company A "売り手"\nperson X "顧客"\n'
                'bundle {\n  A -> X : goods "商品" / money "1円"\n}\n')
        assert parse_error(text).code == "E05"

    def test_e06_unknown_statement(self):
        e = parse_error(BASIC + "banana\n")
        assert e.code == "E06" and e.line == 5

    def test_e06_unterminated_string_has_a_column(self):
        e = parse_error('company A "売り手\n')
        assert e.code == "E06" and (e.line, e.column) == (1, 11)

    def test_e06_unclosed_block(self):
        e = parse_error(BASIC + "bundle {\n")
        assert e.code == "E06" and e.line == 5

    def test_e06_type_not_first(self):
        e = parse_error(BASIC + "type flow\n")
        assert e.code == "E06"

    def test_e06_unsupported_type(self):
        assert parse_error("type canvas\n" + BASIC).code == "E06"

    def test_e06_japanese_id(self):
        assert parse_error('company 会社 "x"\n').code == "E06"

    def test_e07_duplicate_id(self):
        assert parse_error(BASIC + 'person User "別人"\n').code == "E07"

    def test_e08_no_trade(self):
        assert parse_error('company A "x"\nperson B "y"\n').code == "E08"

    def test_the_message_includes_the_position(self):
        assert "line 4" in str(parse_error(BASIC.replace("-> User", "-> Nobody")))
