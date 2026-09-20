"""config.yamlの読み込み・デフォルト値マージ・chaptersエントリ解析のリグレッションテスト（#96）。"""
import pytest

from text_compositor.chapters import _parse_chapter_entry
from text_compositor.config import deep_update, default_config


class TestDeepUpdate:
    def test_merges_flat_keys(self):
        d = {"a": 1, "b": 2}
        result = deep_update(d, {"b": 20, "c": 3})
        assert result == {"a": 1, "b": 20, "c": 3}

    def test_merges_nested_dict_without_dropping_untouched_keys(self):
        d = {"document": {"title": "t", "author": "a"}}
        result = deep_update(d, {"document": {"title": "new"}})
        assert result == {"document": {"title": "new", "author": "a"}}

    def test_overwriting_nested_dict_with_non_dict_replaces_it(self):
        d = {"a": {"b": 1}}
        result = deep_update(d, {"a": "scalar"})
        assert result == {"a": "scalar"}

    def test_mutates_and_returns_same_object(self):
        d = {"a": 1}
        assert deep_update(d, {"b": 2}) is d


class TestDefaultConfig:
    def test_has_expected_top_level_sections(self):
        config = default_config()
        assert set(config.keys()) == {"document", "output", "template", "inputs"}

    def test_default_line_mapping_is_block(self):
        assert default_config()["document"]["diagnostics"]["line_mapping"] == "block"

    def test_default_template_is_named_template(self):
        assert default_config()["template"]["path"] == "template"

    def test_returns_a_fresh_dict_each_call(self):
        """既定値を呼び出し元が書き換えても、他の呼び出しに影響しないこと（共有可変状態のバグ防止）。"""
        a = default_config()
        a["document"]["title"] = "changed"
        b = default_config()
        assert b["document"]["title"] != "changed"


class TestParseChapterEntry:
    def test_string_entry_is_a_plain_file_chapter(self):
        assert _parse_chapter_entry("a.md") == ("a.md", {}, "file")

    def test_dict_with_file_key(self):
        ch = {"file": "a.md", "landscape": True}
        assert _parse_chapter_entry(ch) == ("a.md", ch, "file")

    def test_dict_with_aggregate_key(self):
        ch = {"aggregate": "data.yaml"}
        assert _parse_chapter_entry(ch) == ("data.yaml", ch, "aggregate")

    def test_dict_without_file_or_aggregate_exits(self):
        with pytest.raises(SystemExit):
            _parse_chapter_entry({"landscape": True})

    def test_non_string_non_dict_entry_exits(self):
        with pytest.raises(SystemExit):
            _parse_chapter_entry(123)
