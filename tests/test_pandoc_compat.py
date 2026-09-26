"""Pandoc原稿の主要拡張（fenced divs・属性付きフェンスコード・footnote・citation・definition list）を
`chapters`にそのまま流し込んだときの挙動のリグレッションテスト（#84）。

目標とする互換性のレベルはMarpと同じ（`doc/spec.md`7章）: ビルドが例外で落ちたり、想定外の警告が
出たりしないこと。値を実際の脚注・参考文献として反映する（footnoteの組版、citationの文献解決等）
ことは対象外で、Marpのディレクティブと同様「認識するが反映しない」レベルに留める。
"""
from text_compositor.renderer import TypstRenderer


def render(md_text, **kw):
    return TypstRenderer(line_mapping="off", **kw).render(md_text)


class TestFencedDivs:
    def test_single_paragraph(self, capsys):
        out = render("::: {.note}\nThis is a note.\n:::\n")
        assert out == "::: {.note}#linebreak()\nThis is a note.#linebreak()\n:::\n\n"
        assert capsys.readouterr().out == ""

    def test_blank_line_separated_multi_paragraph(self, capsys):
        out = render("::: {.note}\n\nFirst paragraph.\n\nSecond paragraph.\n\n:::\n")
        assert out == "::: {.note}\n\nFirst paragraph.\n\nSecond paragraph.\n\n:::\n\n"
        assert capsys.readouterr().out == ""


class TestAttributedFencedCode:
    def test_class_and_extra_attr_extracts_first_class_as_lang(self, capsys):
        out = render("```{.python .numberLines}\nprint('hi')\n```\n")
        assert out == "#raw(\"print('hi')\\n\", lang: \"python\", block: true)\n\n"
        assert capsys.readouterr().out == ""

    def test_single_class_extracts_as_lang(self, capsys):
        out = render("```{.python}\nprint('hi')\n```\n")
        assert 'lang: "python"' in out

    def test_no_class_falls_back_to_first_attr_as_lang(self, capsys):
        # .numberLinesは言語クラスではないが、「先頭クラス=言語」というPandocの慣習どおりに渡す
        # だけに留める（値の反映はしない方針）。Typstは未知の言語として無装飾表示するだけで、
        # 壊れた文字列（旧: `lang: "{.numberLines"`）のような実害はない。
        out = render("```{.numberLines}\ncode\n```\n")
        assert out == '#raw("code\\n", lang: "numberLines", block: true)\n\n'


class TestFootnotes:
    def test_multi_word_body_renders_as_literal_text(self, capsys):
        out = render("Some text with a footnote.[^1]\n\n[^1]: This is the footnote body.\n")
        assert out == ("Some text with a footnote.\\[^1\\]\n\n"
                        "\\[^1\\]: This is the footnote body.\n\n")
        assert "#link(" not in out
        assert capsys.readouterr().out == ""

    def test_single_word_body_does_not_become_a_stray_link(self, capsys):
        """#84の本題: 本文が空白を含まない1語だと、CommonMarkの通常のリンク参照定義
        （`[label]: destination`）と構文上区別できず、[^1]が実在しないリンクに化けていた
        （警告もエラーも出ないまま、#link()が生成されていた）。"""
        out = render("Some text.[^1]\n\n[^1]: shorttext\n")
        assert out == "Some text.\\[^1\\]\n\n\\[^1\\]: shorttext\n\n"
        assert "#link(" not in out
        assert capsys.readouterr().out == ""

    def test_example_inside_fence_is_left_untouched(self):
        """使い方説明のサンプルコード（```内）まで無害化の対象にしないこと（#85と同じ保護）。"""
        out = render("```\n[^1]: shorttext\n```\n")
        assert out == '#raw("[^1]: shorttext\\n", block: true)\n\n'


class TestCitations:
    def test_renders_as_literal_text(self, capsys):
        out = render("As shown in [@doe2020], the result holds.\n")
        assert out == "As shown in \\[\\@doe2020\\], the result holds.\n\n"
        assert capsys.readouterr().out == ""


class TestDefinitionLists:
    def test_renders_as_plain_paragraphs_without_crash(self, capsys):
        out = render("Term 1\n: Definition 1a\n: Definition 1b\n\nTerm 2\n: Definition 2\n")
        assert out == ("Term 1#linebreak()\n: Definition 1a#linebreak()\n: Definition 1b\n\n"
                        "Term 2#linebreak()\n: Definition 2\n\n")
        assert capsys.readouterr().out == ""
