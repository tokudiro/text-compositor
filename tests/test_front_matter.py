"""front-matterの解析（strip_front_matter）と、landscape/paper_size/header/footer/paginate/
font_sizeの優先順位（chapters[] > front-matter > グローバル、#17・#42）のリグレッションテスト（#96）。
"""
import os

from text_compositor.chapters import _render_markdown_chapter
from text_compositor.renderer import TypstRenderer


class TestStripFrontMatter:
    def test_parses_yaml_front_matter(self):
        renderer = TypstRenderer(line_mapping="off")
        text, meta = renderer.strip_front_matter("---\ntitle: t\nlandscape: true\n---\n\n# 見出し\n")
        assert meta == {"title": "t", "landscape": True}
        assert text.endswith("# 見出し\n")

    def test_no_front_matter_returns_empty_meta(self):
        renderer = TypstRenderer(line_mapping="off")
        text, meta = renderer.strip_front_matter("# 見出し\n")
        assert meta == {}
        assert text == "# 見出し\n"

    def test_removed_lines_keep_line_numbers(self):
        """front-matterを除去しても改行数を維持し、以降の行番号がずれないこと。"""
        renderer = TypstRenderer(line_mapping="off")
        text, _ = renderer.strip_front_matter("---\ntitle: t\n---\n\n# 見出し\n")
        assert text == "\n\n\n\n# 見出し\n"

    def test_invalid_font_size_is_dropped_with_warning(self, capsys):
        renderer = TypstRenderer(line_mapping="off")
        _, meta = renderer.strip_front_matter("---\nfont_size: abc\n---\n本文\n")
        assert "font_size" not in meta
        assert "[Warning]" in capsys.readouterr().out

    def test_unknown_key_warns_but_is_kept(self, capsys):
        renderer = TypstRenderer(line_mapping="off")
        _, meta = renderer.strip_front_matter("---\nunknown_key: 1\n---\n本文\n")
        assert meta == {"unknown_key": 1}
        assert "[Warning]" in capsys.readouterr().out


def _render_chapter(tmp_path, md_text, ch_dict=None, **overrides):
    """_render_markdown_chapter()を、テストに必要な引数だけ差し替えて呼び出すヘルパー。
    既定値はグローバル設定と現在値が一致した状態（#set pageが出ない状態）から始める。"""
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    ch_file = "chapter.md"
    (inputs_dir / ch_file).write_text(md_text, encoding="utf-8")
    renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
    kwargs = dict(
        ch_dict=ch_dict or {}, ch_file=ch_file, inputs_dir=str(inputs_dir), renderer=renderer,
        current_landscape=False, current_paper="a4",
        global_landscape=False, global_paper="a4",
        is_first_chapter=False, cover_mode="none", global_table_header={},
        current_header="Global Title", current_footer=None, current_paginate=True,
        global_header="Global Title", global_footer=None, global_paginate=True,
        current_background=None, global_background=None,
        current_logo=None, global_logo=None,
    )
    kwargs.update(overrides)
    return _render_markdown_chapter(**kwargs)


class TestLandscapePriority:
    def test_global_is_used_when_nothing_overrides(self, tmp_path):
        _, landscape, *_ = _render_chapter(tmp_path, "本文\n")
        assert landscape is False

    def test_front_matter_overrides_global(self, tmp_path):
        md = "---\nlandscape: true\n---\n本文\n"
        _, landscape, *_ = _render_chapter(tmp_path, md)
        assert landscape is True

    def test_chapters_entry_overrides_front_matter(self, tmp_path):
        md = "---\nlandscape: true\n---\n本文\n"
        _, landscape, *_ = _render_chapter(tmp_path, md, ch_dict={"landscape": False})
        assert landscape is False

    def test_set_page_emitted_when_value_changes(self, tmp_path):
        md = "---\nlandscape: true\n---\n本文\n"
        typst_code, *_ = _render_chapter(tmp_path, md, current_landscape=False)
        assert "flipped: true" in typst_code

    def test_no_set_page_emitted_when_value_unchanged(self, tmp_path):
        typst_code, *_ = _render_chapter(tmp_path, "本文\n", current_landscape=False)
        assert "#set page(" not in typst_code


class TestHeaderFooterPaginatePriority:
    def test_front_matter_header_overrides_global(self, tmp_path):
        md = "---\nheader: FM Header\n---\n本文\n"
        _, _, _, header, *_ = _render_chapter(tmp_path, md)
        assert header == "FM Header"

    def test_chapters_entry_header_overrides_front_matter(self, tmp_path):
        md = "---\nheader: FM Header\n---\n本文\n"
        _, _, _, header, *_ = _render_chapter(tmp_path, md, ch_dict={"header": "Chapter Header"})
        assert header == "Chapter Header"

    def test_chapters_entry_can_explicitly_disable_header(self, tmp_path):
        md = "---\nheader: FM Header\n---\n本文\n"
        _, _, _, header, *_ = _render_chapter(tmp_path, md, ch_dict={"header": None})
        assert header is None

    def test_front_matter_footer_and_paginate(self, tmp_path):
        md = "---\nfooter: FM Footer\npaginate: false\n---\n本文\n"
        _, _, _, _, footer, paginate, *_ = _render_chapter(tmp_path, md)
        assert footer == "FM Footer"
        assert paginate is False


class TestFontSize:
    def test_front_matter_font_size_wraps_chapter_in_scoped_text_size(self, tmp_path):
        md = "---\nfont_size: 12pt\n---\n本文\n"
        typst_code, *_ = _render_chapter(tmp_path, md)
        assert "#set text(size: 12pt)" in typst_code

    def test_no_font_size_means_no_wrapping(self, tmp_path):
        typst_code, *_ = _render_chapter(tmp_path, "本文\n")
        assert "#set text(size:" not in typst_code
