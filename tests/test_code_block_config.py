"""設定`code_block`（#511）の、読み込み・検証・合成のテスト。描画への反映は、次の段階。"""
import sys

import pytest
import typst

import text_compositor.build as build_mod
from text_compositor import log
from text_compositor.chapters import ChapterDefaults, _chapter_code_block_style, _expand_chapters
from text_compositor.code_block_style import (
    DEFAULT_BORDER_COLOR, DEFAULT_BORDER_WIDTH, TYPST_COLOR_NAMES, CodeBlockStyle,
    merge_code_block, parse_code_block, resolve_code_block)
from text_compositor.config import _validate_config_keys


@pytest.fixture(autouse=True)
def _restore_verbosity():
    yield
    log.set_verbosity(False, False)


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def fails(value, capsys, where="document"):
    with pytest.raises(SystemExit):
        parse_code_block(value, where)
    return output(capsys)


class TestParse:
    def test_omitted_is_empty(self):
        assert parse_code_block(None, "document") == {}

    def test_false_disables(self):
        assert parse_code_block(False, "document") == {"enabled": False}

    def test_true_and_mappings_enable(self):
        """`code_block`を書いた階層は、上の階層が`false`でも、有効にする。"""
        assert parse_code_block(True, "document") == {"enabled": True}
        assert parse_code_block({}, "document") == {"enabled": True}

    def test_border_forms(self):
        assert parse_code_block({"border": True}, "d")["border"] == {}          # 既定の色・太さ
        assert parse_code_block({"border": False}, "d")["border"] is False
        assert parse_code_block({"border": {"color": "#d1d9e0", "width": "0.75pt"}}, "d")["border"] == {
            "color": "#d1d9e0", "width": "0.75pt"}
        assert parse_code_block({"border": {"width": "1pt"}}, "d")["border"] == {"width": "1pt"}

    def test_font_size(self):
        assert parse_code_block({"font_size": "8pt"}, "d")["font_size"] == "8pt"
        assert parse_code_block({"font_size": "7.5pt"}, "d")["font_size"] == "7.5pt"

    @pytest.mark.parametrize("value", ["yes", 1, ["border"], 0.5])
    def test_a_wrong_type_is_an_error(self, value, capsys):
        message = fails(value, capsys)
        assert "code_block must be true, false or a mapping" in message and "document" in message

    def test_an_unknown_key_is_an_error_and_names_the_allowed_keys(self, capsys):
        message = fails({"bordr": True}, capsys, "chapter 'a.md'")
        assert "unknown key(s) bordr" in message and "border, font_size" in message and "chapter 'a.md'" in message

    @pytest.mark.parametrize("border", ["yes", 1, ["x"]])
    def test_a_wrong_border_type_is_an_error(self, border, capsys):
        assert "border must be true, false or a mapping" in fails({"border": border}, capsys)

    def test_an_unknown_border_key_is_an_error(self, capsys):
        assert "border has unknown key(s) colour" in fails({"border": {"colour": "red"}}, capsys)

    @pytest.mark.parametrize("color", ["banana", "#12", "#12345", 123, True, None, ""])
    def test_a_wrong_color_is_an_error(self, color, capsys):
        assert "border color must be" in fails({"border": {"color": color}}, capsys)

    @pytest.mark.parametrize("color", ["#d1d9e0", "#abc", "#abcd", "#AABBCCDD", "gray", "red"])
    def test_valid_colors(self, color):
        assert parse_code_block({"border": {"color": color}}, "d")["border"] == {"color": color}

    @pytest.mark.parametrize("width", ["1px", "0.75", "-1pt", ".5pt", 1, True, None, "1 pt"])
    def test_a_wrong_border_width_is_an_error(self, width, capsys):
        assert "border width must look like" in fails({"border": {"width": width}}, capsys)

    @pytest.mark.parametrize("size", ["8", "8px", "1em", 8, True, None])
    def test_a_wrong_font_size_is_an_error(self, size, capsys):
        assert "font_size must look like" in fails({"font_size": size}, capsys)


class TestMergeAndResolve:
    def test_a_lower_level_overrides_key_by_key(self):
        base = parse_code_block({"font_size": "8pt", "border": {"color": "red"}}, "d")
        chapter = parse_code_block({"border": {"width": "1pt"}}, "c")
        merged = merge_code_block(base, chapter)
        assert merged["font_size"] == "8pt"                                    # 書かなかった項目は、上の階層のまま
        assert merged["border"] == {"color": "red", "width": "1pt"}            # 色・太さも、キー単位

    def test_border_true_keeps_the_colors_of_the_upper_level(self):
        base = parse_code_block({"border": {"color": "red"}}, "d")
        assert merge_code_block(base, parse_code_block({"border": True}, "c"))["border"] == {"color": "red"}

    def test_border_false_removes_the_border_of_the_upper_level(self):
        base = parse_code_block({"border": True}, "d")
        assert merge_code_block(base, parse_code_block({"border": False}, "c"))["border"] is False

    def test_border_on_top_of_no_border(self):
        base = parse_code_block({"border": False}, "d")
        assert merge_code_block(base, parse_code_block({"border": {"width": "2pt"}}, "c"))["border"] == {"width": "2pt"}

    def test_false_below_disables_and_a_mapping_below_enables_again(self):
        doc = parse_code_block(False, "d")
        assert merge_code_block(doc, {})["enabled"] is False
        assert merge_code_block(doc, parse_code_block({"border": True}, "c"))["enabled"] is True
        assert merge_code_block(parse_code_block({}, "d"), parse_code_block(False, "c"))["enabled"] is False

    def test_merge_does_not_change_its_inputs(self):
        base = parse_code_block({"border": {"color": "red"}}, "d")
        merge_code_block(base, parse_code_block({"border": {"width": "1pt"}}, "c"))
        assert base["border"] == {"color": "red"}

    def test_resolve_defaults(self):
        assert resolve_code_block({}) == CodeBlockStyle(enabled=True)         # 枠線なし・大きさは、Typstの既定
        assert resolve_code_block({"border": False}).border_color is None
        style = resolve_code_block({"border": {}})
        assert (style.border_color, style.border_width) == (DEFAULT_BORDER_COLOR, DEFAULT_BORDER_WIDTH) == ("#d1d9e0", "0.75pt")

    def test_resolve_fills_the_missing_key_with_its_default(self):
        only_color = resolve_code_block({"border": {"color": "red"}})
        assert (only_color.border_color, only_color.border_width) == ("red", DEFAULT_BORDER_WIDTH)
        only_width = resolve_code_block({"border": {"width": "2pt"}})
        assert (only_width.border_color, only_width.border_width) == (DEFAULT_BORDER_COLOR, "2pt")

    def test_resolve_keeps_font_size_and_enabled(self):
        style = resolve_code_block({"enabled": False, "font_size": "8pt"})
        assert style.enabled is False and style.font_size == "8pt"


def defaults(code_block):
    return ChapterDefaults(landscape=False, paper="a4", header=None, footer=None, paginate=True, background=None,
                           logo=None, table_header={}, heading_offset=0, code_block=code_block)


class TestHierarchy:
    """章 ＞ section ＞ `document:`の優先順位（`table_header`と同じ）。"""

    def expand(self, chapters, document):
        root = defaults(parse_code_block(document, "document"))
        return _expand_chapters(chapters, root, ".", ".")

    def style_of(self, entries, index, ch_dict=None):
        kind, entry, d = entries[index]
        return _chapter_code_block_style(d, ch_dict if ch_dict is not None else (entry if isinstance(entry, dict) else {}), "x.md")

    def test_a_flat_chapter_inherits_the_document(self):
        entries = self.expand(["a.md"], {"border": True, "font_size": "8pt"})
        style = self.style_of(entries, 0)
        assert (style.border_color, style.font_size) == ("#d1d9e0", "8pt")

    def test_a_section_overrides_the_document_and_its_chapters_override_the_section(self):
        entries = self.expand([
            {"section": "S", "code_block": {"font_size": "7pt", "border": {"color": "red"}}, "chapters": [
                "a.md", {"file": "b.md", "code_block": {"font_size": "9pt"}}, {"file": "c.md", "code_block": False}]},
            "d.md",
        ], {"border": {"width": "2pt"}, "font_size": "8pt"})
        # entries: section見出し, a, b, c, d
        a, b, c, d = (self.style_of(entries, i) for i in (1, 2, 3, 4))
        assert (a.font_size, a.border_color, a.border_width) == ("7pt", "red", "2pt")     # section ＞ document、キー単位
        assert (b.font_size, b.border_color) == ("9pt", "red")                            # 章 ＞ section
        assert c.enabled is False                                                         # 章で、無効にする
        assert (d.font_size, d.border_color, d.border_width) == ("8pt", "#d1d9e0", "2pt")  # sectionの外は、documentだけ

    def test_a_chapter_can_enable_again_after_the_document_disabled_it(self):
        entries = self.expand([{"file": "a.md", "code_block": {"border": True}}, "b.md"], False)
        assert self.style_of(entries, 0).enabled is True
        assert self.style_of(entries, 1).enabled is False

    def test_a_wrong_value_in_a_chapter_or_a_section_is_reported_before_rendering(self, capsys):
        with pytest.raises(SystemExit):
            self.expand([{"file": "a.md", "code_block": {"bordr": True}}], None)
        assert "chapter 'a.md'" in output(capsys)
        with pytest.raises(SystemExit):
            self.expand([{"section": "S", "code_block": "yes", "chapters": ["a.md"]}], None)


class TestConfigFile:
    def test_document_code_block_is_an_allowed_key(self, capsys):
        _validate_config_keys({"document": {"code_block": {"border": True}}})   # 未知キーのエラーにならない

    def write_project(self, tmp_path, document_extra="", chapters='["a.md"]'):
        (tmp_path / "a.md").write_text("# A\n\n```python\nprint(1)\n```\n", encoding="utf-8")
        (tmp_path / "text-compositor.config.yaml").write_text(
            'document:\n  title: "t"\n  cover: "none"\n  toc: false\n' + document_extra +
            'inputs: {dir: "."}\noutput: {filename: "out.pdf", dir: "."}\n'
            f'chapters: {chapters}\n', encoding="utf-8")
        return tmp_path / "text-compositor.config.yaml"

    def build(self, config, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["text-compositor", "--config", str(config), "-q"])
        build_mod.build()

    def test_a_valid_setting_builds(self, tmp_path, monkeypatch):
        from text_compositor.deps import ensure_fonts
        try:
            ensure_fonts()
        except SystemExit:
            pytest.skip("fonts are not available")
        config = self.write_project(tmp_path, '  code_block:\n    font_size: 8pt\n    border: {color: "#d1d9e0", width: 0.75pt}\n')
        self.build(config, monkeypatch)
        assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")

    def test_a_wrong_document_setting_stops_the_build(self, tmp_path, monkeypatch, capsys):
        config = self.write_project(tmp_path, '  code_block:\n    bordr: true\n')
        with pytest.raises(SystemExit):
            self.build(config, monkeypatch)
        assert "unknown key(s) bordr" in output(capsys)

    def test_a_wrong_chapter_setting_stops_the_build(self, tmp_path, monkeypatch, capsys):
        config = self.write_project(tmp_path, chapters='[{file: "a.md", code_block: {font_size: "8px"}}]')
        with pytest.raises(SystemExit):
            self.build(config, monkeypatch)
        assert "font_size must look like" in output(capsys)


@pytest.mark.parametrize("name", sorted(TYPST_COLOR_NAMES))
def test_every_accepted_color_name_exists_in_typst(name):
    """受け付ける色の名前は、Typstの色の定数と、実際に一致する（一致しない名前を受け付けると、Typstのエラーになる）。"""
    pdf = typst.compile(f'#rect(width: 10pt, height: 10pt, fill: {name})'.encode(), format="pdf")
    assert pdf.startswith(b"%PDF")
