"""行番号マッピング（#27）のリグレッションテスト。

Typstコンパイルエラーの行番号を元のMarkdownの行番号へ逆引きする機能について、
実機検証で見つけた不具合（document.diagnostics: の値がNoneになるケースでのクラッシュ、
TypstError.diagnosticとmessageの取り違え）を中心に、壊れたら気づけるように固定する。
"""
from text_compositor.compiler import _annotate_typst_error, _build_srcmap, _resolve_srcmap
from text_compositor.config import _resolve_line_mapping
from text_compositor.renderer import TypstRenderer


PREFIX = TypstRenderer.SRCMAP_PREFIX


class TestResolveLineMapping:
    def test_default_is_block(self):
        assert _resolve_line_mapping({}) == "block"

    def test_document_without_diagnostics_key(self):
        assert _resolve_line_mapping({"document": {"title": "x"}}) == "block"

    def test_explicit_off(self):
        config = {"document": {"diagnostics": {"line_mapping": "off"}}}
        assert _resolve_line_mapping(config) == "off"

    def test_explicit_block(self):
        config = {"document": {"diagnostics": {"line_mapping": "block"}}}
        assert _resolve_line_mapping(config) == "block"

    def test_diagnostics_key_present_but_none(self):
        """YAMLで`diagnostics:`とだけ書くと値がNoneになる（実機検証で見つけたクラッシュの再現）。"""
        config = {"document": {"diagnostics": None}}
        assert _resolve_line_mapping(config) == "block"

    def test_unsupported_value_falls_back_with_warning(self, capsys):
        config = {"document": {"diagnostics": {"line_mapping": "fine"}}}
        assert _resolve_line_mapping(config) == "block"
        captured = capsys.readouterr()
        assert "[Warning]" in captured.out
        assert "fine" in captured.out


class TestBuildSrcmap:
    def test_extracts_markers_in_order(self):
        typst_code = (
            '#import "x.typ": y\n'
            "\n"
            f"{PREFIX}sample/a.md:3\n"
            "本文1\n"
            "\n"
            f"{PREFIX}sample/a.md:7\n"
            "本文2\n"
        )
        assert _build_srcmap(typst_code) == [(3, "sample/a.md", 3), (6, "sample/a.md", 7)]

    def test_no_markers_returns_empty(self):
        assert _build_srcmap("#foo()\n本文\n") == []

    def test_windows_path_with_colon_is_parsed_correctly(self):
        # Windowsの絶対パス自体に':'（C:\...）を含むため、行番号側の':'と混同しないことを確認する。
        typst_code = f"{PREFIX}C:\\work\\sample\\a.md:12\n本文\n"
        assert _build_srcmap(typst_code) == [(1, "C:\\work\\sample\\a.md", 12)]


class TestResolveSrcmap:
    SRC_MAP = [(5, "a.md", 10), (20, "b.md", 3)]

    def test_exact_marker_line(self):
        assert _resolve_srcmap(self.SRC_MAP, 5) == ("a.md", 10)

    def test_between_markers_resolves_to_earlier_one(self):
        assert _resolve_srcmap(self.SRC_MAP, 19) == ("a.md", 10)

    def test_after_last_marker(self):
        assert _resolve_srcmap(self.SRC_MAP, 100) == ("b.md", 3)

    def test_before_first_marker_returns_none(self):
        assert _resolve_srcmap(self.SRC_MAP, 1) is None

    def test_empty_src_map_returns_none(self):
        assert _resolve_srcmap([], 5) is None


class TestAnnotateTypstError:
    def test_appends_hint_for_resolvable_location(self):
        error_text = "error: foo\n  \u250c\u2500 temp_build.typ:20:5\n  \u2502\n"
        src_map = [(5, "a.md", 10), (20, "b.md", 3)]
        annotated = _annotate_typst_error(error_text, src_map)
        assert error_text in annotated
        assert "[Hint] temp_build.typ:20 corresponds to around b.md:3" in annotated

    def test_duplicate_locations_produce_one_hint(self):
        error_text = "temp_build.typ:20:5 ... temp_build.typ:20:9"
        src_map = [(20, "b.md", 3)]
        annotated = _annotate_typst_error(error_text, src_map)
        assert annotated.count("[Hint]") == 1

    def test_empty_src_map_returns_text_unchanged(self):
        error_text = "error: foo\n  \u250c\u2500 temp_build.typ:20:5\n"
        assert _annotate_typst_error(error_text, []) == error_text

    def test_location_before_any_marker_adds_no_hint(self):
        error_text = "temp_build.typ:1:1"
        src_map = [(5, "a.md", 10)]
        assert _annotate_typst_error(error_text, src_map) == error_text


class TestEmitSrcmapIntegration:
    """TypstRenderer.render()が実際に生成するTypstコードへマーカーが挿し込まれるかを検証する。"""

    def _render(self, md_text, line_mapping="block", filepath="chapter.md"):
        renderer = TypstRenderer(line_mapping=line_mapping)
        return renderer.render(md_text, filepath=filepath)

    def test_block_mode_marks_heading_paragraph_list_table(self):
        md = (
            "# 見出し\n"
            "\n"
            "段落本文です。\n"
            "\n"
            "- 項目1\n"
            "- 項目2\n"
            "\n"
            "| a | b |\n"
            "| - | - |\n"
            "| 1 | 2 |\n"
        )
        out = self._render(md)
        assert f"{PREFIX}chapter.md:1" in out
        assert f"{PREFIX}chapter.md:3" in out
        assert f"{PREFIX}chapter.md:5" in out

    def test_off_mode_emits_no_markers(self):
        out = self._render("# 見出し\n\n段落。\n", line_mapping="off")
        assert PREFIX not in out

    def test_list_items_are_not_individually_marked(self):
        md = "- 項目1\n- 項目2\n- 項目3\n"
        out = self._render(md)
        assert out.count(PREFIX) == 1

    def test_front_matter_removal_keeps_line_numbers(self):
        md = (
            "---\n"
            "title: t\n"
            "---\n"
            "\n"
            "# 見出し\n"
        )
        out = self._render(md)
        assert f"{PREFIX}chapter.md:5" in out

    def test_hr_and_fence_are_marked(self):
        md = (
            "段落。\n"
            "\n"
            "---\n"
            "\n"
            "```text\n"
            "code\n"
            "```\n"
        )
        out = self._render(md)
        assert f"{PREFIX}chapter.md:1" in out  # 段落
        assert f"{PREFIX}chapter.md:3" in out  # hr
        assert f"{PREFIX}chapter.md:5" in out  # fence
