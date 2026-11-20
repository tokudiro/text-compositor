"""設定`document.table_font_size`（表の中の文字の大きさ）のテスト。"""
import pytest

from text_compositor.config import _validate_config_keys
from text_compositor.document import _build_document_preamble, _table_font_size_rule


def _preamble(doc):
    return _build_document_preamble({"document": doc}, "template.typ", True, ".", ".")[0]


def test_omitted_keeps_the_body_size():
    assert "show table" not in _preamble({})
    assert _table_font_size_rule(None) == ""


@pytest.mark.parametrize("value", ["9pt", "8.5pt", "12pt"])
def test_valid_value_adds_a_show_rule_after_conf(value):
    code = _preamble({"table_font_size": value})
    rule = f"#show table: set text(size: {value})"
    assert rule in code
    assert code.index("doc,\n)") < code.index(rule)   # conf()の中ではなく、本文の側に効かせる


@pytest.mark.parametrize("value", ["9", "9px", "pt", "-9pt", "9 pt", 9, True, ["9pt"], ""])
def test_invalid_value_stops(value, capsys):
    with pytest.raises(SystemExit):
        _table_font_size_rule(value)
    captured = capsys.readouterr()
    assert "table_font_size must look like" in captured.out + captured.err


def test_key_is_allowed_in_document(capsys):
    _validate_config_keys({"document": {"table_font_size": "9pt"}})   # 例外が出ない
