"""区切り記号・CamelCase境界へのソフト改行点挿入のリグレッションテスト（#269）。

aggregateの表の列幅を広げても、スペースを含まない長い識別子（テストパス・
関数名等）はTypstが1語として扱い、折り返さずセルからはみ出す。
insert_soft_break_hints()がゼロ幅スペース(U+200B)を挿入し、折り返せるようにする。
"""
from text_compositor.chapters import _render_aggregate_chapter
from text_compositor.renderer import TypstRenderer
from text_compositor.typst_literal import insert_soft_break_hints

ZW = "​"


class TestInsertSoftBreakHints:
    def test_inserts_after_delimiters(self):
        out = insert_soft_break_hints("tests/test_config.py::TestDeepUpdate")
        assert out == f"tests/{ZW}test_{ZW}config.{ZW}py:{ZW}:{ZW}Test{ZW}Deep{ZW}Update"

    def test_inserts_at_camel_case_boundary(self):
        out = insert_soft_break_hints("TestDeepUpdate")
        assert out == f"Test{ZW}Deep{ZW}Update"

    def test_inserts_around_parentheses(self):
        out = insert_soft_break_hints("deep_update()")
        assert out == f"deep_{ZW}update({ZW}){ZW}"

    def test_plain_word_is_unchanged(self):
        assert insert_soft_break_hints("render") == "render"

    def test_sentence_with_spaces_is_unchanged(self):
        text = "通常の段落を含む Markdown を render() に渡す"
        assert insert_soft_break_hints(text) == text.replace(
            "render()", f"render({ZW}){ZW}")


class TestCodeInlineGetsSoftBreakHints:
    def test_code_inline_raw_contains_zero_width_space(self):
        renderer = TypstRenderer(line_mapping="off")
        out = renderer.render("`deep_update()`を確認する。", filepath="a.md")
        assert f"deep_{ZW}update({ZW}){ZW}" in out


class TestAggregateTitleGetsSoftBreakHints:
    def test_long_title_identifier_gets_soft_break_hints(self, tmp_path):
        import yaml

        agg_dir = tmp_path / "tc"
        agg_dir.mkdir()
        (agg_dir / "tc001.yaml").write_text(
            yaml.safe_dump({
                "id": "TC-001",
                "title": "設定値の再帰的マージ（tests/test_config.py::TestDeepUpdate）",
                "priority": "High",
                "steps": "手順",
                "expected": "結果",
            }, allow_unicode=True),
            encoding="utf-8",
        )

        renderer = TypstRenderer(line_mapping="off")
        typst_code, *_ = _render_aggregate_chapter(
            {"aggregate": "tc", "title": "Test Cases"}, "tc", str(tmp_path), renderer,
            current_landscape=False, current_paper="a4",
            global_landscape=False, global_paper="a4",
            current_header=None, current_footer=None, current_paginate=True,
            global_header=None, global_footer=None, global_paginate=True,
            current_background=None, global_background=None,
            current_logo=None, global_logo=None,
        )

        assert f"test\\_{ZW}config.{ZW}py:{ZW}:{ZW}Test{ZW}Deep{ZW}Update" in typst_code
