"""Markdown基本構文のTypst変換（TypstRenderer.render/render_inline/render_tokens）の
リグレッションテスト（#96）。
"""
import os
import pytest

from text_compositor.renderer import TypstRenderer


def render(md_text, **kw):
    return TypstRenderer(line_mapping="off", **kw).render(md_text)


class TestHeadingsAndParagraphs:
    def test_heading_levels(self):
        out = render("# 見出し1\n\n## 見出し2\n")
        assert out == "= 見出し1\n\n== 見出し2\n\n"

    def test_paragraph(self):
        assert render("本文です。\n") == "本文です。\n\n"


class TestLists:
    def test_bullet_list(self):
        out = render("- 項目1\n- 項目2\n")
        assert out == "- 項目1\n- 項目2\n\n"

    def test_ordered_list(self):
        out = render("1. 項目1\n2. 項目2\n")
        assert out == "+ 項目1\n+ 項目2\n\n"

    def test_nested_bullet_list_is_indented(self):
        out = render("- 項目1\n  - 項目1a\n  - 項目1b\n- 項目2\n")
        assert out == "- 項目1\n  - 項目1a\n  - 項目1b\n- 項目2\n\n"

    def test_nested_ordered_list_is_indented(self):
        out = render("1. 項目1\n   1. 項目1a\n2. 項目2\n")
        assert out == "+ 項目1\n  + 項目1a\n+ 項目2\n\n"

    def test_task_list_checkbox_glyphs(self):
        out = render("- [ ] 未完了\n- [x] 完了\n")
        assert out == "- ☐ 未完了\n- ☑ 完了\n\n"


class TestTable:
    def test_basic_table(self):
        out = render("| a | b |\n| - | - |\n| 1 | 2 |\n")
        assert out == "#table(\n  columns: 2,\n  table.header(\n  [a], [b], \n  \n  ),\n  [1], [2], \n  \n)\n\n"


class TestBlockquoteAndAlert:
    def test_plain_blockquote(self):
        out = render("> 引用文。\n")
        assert out == "#quote(block: true)[\n引用文。\n\n]\n\n"

    def test_multiline_blockquote_uses_linebreak(self):
        out = render("> 1行目\n> 2行目\n")
        assert out == "#quote(block: true)[\n1行目#linebreak()\n2行目\n\n]\n\n"

    @pytest.mark.parametrize("marker,kind", [
        ("NOTE", "note"), ("TIP", "tip"), ("IMPORTANT", "important"),
        ("WARNING", "warning"), ("CAUTION", "caution"),
    ])
    def test_alert_kinds(self, marker, kind):
        out = render(f"> [!{marker}]\n> 本文。\n")
        assert out == f'#callout(kind: "{kind}")[\n本文。\n\n]\n\n'


class TestCodeFence:
    def test_fence_with_lang(self):
        out = render("```text\ncode here\n```\n")
        assert out == '#raw("code here\\n", lang: "text", block: true)\n\n'

    def test_fence_without_lang(self):
        out = render("```\ncode here\n```\n")
        assert out == '#raw("code here\\n", block: true)\n\n'

    def test_inline_code(self):
        assert render("`code`\n") == '#raw("code")\n\n'


class TestInlineDecoration:
    def test_bold_italic_strikethrough(self):
        out = render("**太字** *斜体* ~~取消~~\n")
        assert out == "#strong[太字] #emph[斜体] #strike[取消]\n\n"

    def test_color_attribute(self):
        assert render("[text]{color=red}\n") == "#text(fill: red)[text]\n\n"

    def test_color_attribute_hex(self):
        out = render('[text]{color="#eeeeee"}\n')
        assert out == '#text(fill: rgb("#eeeeee"))[text]\n\n'

    def test_size_attribute(self):
        assert render("[text]{size=12pt}\n") == "#text(size: 12pt)[text]\n\n"

    def test_size_and_color_combined_single_wrap(self):
        out = render("[text]{color=red size=12pt}\n")
        assert out == "#text(fill: red, size: 12pt)[text]\n\n"

    def test_invalid_size_is_ignored_with_warning(self, capsys):
        out = render("[text]{size=12}\n")
        assert out == "text\n\n"
        assert "[Warning]" in capsys.readouterr().out

    def test_html_span_color(self):
        out = render('<span style="color:red">赤字</span>\n')
        assert out == "#text(fill: red)[赤字]\n\n"

    def test_link(self):
        assert render("[リンク](https://example.com)\n") == '#link("https://example.com")[リンク]\n\n'


class TestGlossary:
    def test_wikilink_registers_term_when_enabled(self):
        renderer = TypstRenderer(line_mapping="off", glossary_enabled=True)
        out = renderer.render("[[用語]]\n")
        assert out == "用語#metadata(none)<gloss-0>\n\n"
        assert renderer.glossary_terms == {"用語": ["gloss-0"]}

    def test_wikilink_is_left_as_plain_text_when_disabled(self):
        out = render("[[用語]]\n")
        assert out == "\\[\\[用語\\]\\]\n\n"


class TestImages:
    def test_basic_image_uses_fit_image_for_natural_sizing(self, tmp_path):
        """#69: width/height未指定時は#image()に段幅いっぱいへ引き伸ばされず、fit-image()で
        実寸基準（はみ出す場合のみ自動縮小）になること。"""
        (tmp_path / "a.png").write_bytes(b"\x89PNG")
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        out = renderer.render("![alt](a.png)\n", filepath=str(tmp_path / "doc.md"))
        assert out == '#fit-image("/a.png")\n\n'

    def test_image_with_size_and_align(self, tmp_path):
        (tmp_path / "a.png").write_bytes(b"\x89PNG")
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        out = renderer.render("![alt|width=50%|align=center](a.png)\n", filepath=str(tmp_path / "doc.md"))
        assert out == '#align(center)[#image("/a.png", width: 50%)]\n\n'

    def test_missing_image_exits(self, tmp_path):
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        with pytest.raises(SystemExit):
            renderer.render("![alt](missing.png)\n", filepath=str(tmp_path / "doc.md"))


class TestHorizontalRule:
    """#92: document.marp_compat（既定false）でhr（---/***/___）の挙動を切り替える。"""

    def test_default_is_plain_line_not_pagebreak(self):
        assert render("---\n") == "#line(length: 100%)\n\n"

    def test_asterisk_and_underscore_variants_are_plain_line_too(self):
        assert render("***\n") == "#line(length: 100%)\n\n"
        assert render("___\n") == "#line(length: 100%)\n\n"

    def test_marp_compat_true_treats_hr_as_weak_pagebreak(self):
        renderer = TypstRenderer(line_mapping="off", marp_compat=True)
        assert renderer.render("---\n") == "#pagebreak(weak: true)\n\n"

    def test_marp_compat_true_applies_to_asterisk_and_underscore_too(self):
        """実際のMarpitも---/***/___を区別なくスライド区切りとして扱うため、marp_compat時は
        マークアップ文字で区別しない（区別する案は#92のコメントで検討したが撤回した）。"""
        renderer = TypstRenderer(line_mapping="off", marp_compat=True)
        assert renderer.render("***\n") == "#pagebreak(weak: true)\n\n"
        assert renderer.render("___\n") == "#pagebreak(weak: true)\n\n"


class TestPagebreakDirective:
    """#92: document.marp_compat: falseのとき、hrが水平線になる代わりに使う明示的な改ページ記法。"""

    def test_pagebreak_directive_emits_weak_pagebreak(self):
        assert render("<!-- pagebreak -->\n") == "#pagebreak(weak: true)\n\n"

    def test_pagebreak_directive_works_regardless_of_marp_compat(self):
        renderer = TypstRenderer(line_mapping="off", marp_compat=True)
        assert renderer.render("<!-- pagebreak -->\n") == "#pagebreak(weak: true)\n\n"


class TestHtmlHandling:
    def test_unsupported_html_is_dropped_with_warning(self, capsys):
        out = render("<div>hi</div>\n")
        assert out == ""
        assert "[Warning]" in capsys.readouterr().out


class TestEscaping:
    def test_special_characters_are_escaped(self):
        out = render("特殊文字 # $ @ * _ ` ~ [ ] < > をテスト\n")
        assert out == "特殊文字 \\# \\$ \\@ \\* \\_ \\` \\~ \\[ \\] \\< \\> をテスト\n\n"
