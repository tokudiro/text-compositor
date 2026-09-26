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

    def test_nested_divs_render_without_crash(self, capsys):
        out = render("::: {.a}\n::: {.b}\nInner content.\n:::\n:::\n")
        assert "Inner content." in out
        assert capsys.readouterr().out == ""

    def test_wrapping_a_real_diagram_fence_still_renders_the_diagram(self, capsys):
        """`layout-right`等（本ツール独自の`:::`ブロック）とは名前が一致しないため素通りするだけだが、
        中の本物の図表フェンス自体は、通常どおり検出・変換されることを確認する（#84）。"""
        out = render("::: {.note}\n```dot\ndigraph { a -> b }\n```\n:::\n")
        assert '#raw("digraph { a -> b }\\n", lang: "dot", block: true)' in out
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

    def test_no_dot_class_at_all_omits_lang(self, capsys):
        """クラス（`.foo`）を1つも持たない属性だけの指定（`{data-line="1"}`）は、言語名が
        無いのと同じ扱いにする（`lang`引数自体を渡さない）。"""
        out = render('```{data-line="1"}\ncode\n```\n')
        assert out == '#raw("code\\n", block: true)\n\n'
        assert capsys.readouterr().out == ""

    def test_dot_inside_quoted_attribute_value_does_not_leak_as_lang(self, capsys):
        """属性値に引用符付きでピリオドを含む文字列（バージョン番号等）があると、先頭クラスより
        先に見つかって誤った言語名を拾ってしまっていた（#84で発見）。引用符内は探索対象から除く。"""
        out = render('```{key="a.b" .python}\ncode\n```\n')
        assert out == '#raw("code\\n", lang: "python", block: true)\n\n'
        assert capsys.readouterr().out == ""


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

    def test_single_word_body_with_1_to_3_space_indent_does_not_leak_either(self, capsys):
        """CommonMarkはブロック要素の行頭を3スペースまでインデント扱いしない（4スペース以上で
        インデントコードブロックになる）。この範囲のインデントも、無害化の対象に含める必要がある。"""
        for indent in (1, 2, 3):
            out = render(f"Some text.[^1]\n\n{' ' * indent}[^1]: shorttext\n")
            assert "#link(" not in out, f"indent={indent}"
            assert capsys.readouterr().out == ""

    def test_example_inside_fence_is_left_untouched(self):
        """使い方説明のサンプルコード（```内）まで無害化の対象にしないこと（#85と同じ保護）。"""
        out = render("```\n[^1]: shorttext\n```\n")
        assert out == '#raw("[^1]: shorttext\\n", block: true)\n\n'

    def test_multiple_footnotes_coexist_without_leaking(self, capsys):
        """1語だけの本文と、空白を含む本文のfootnoteが同じ原稿に混在しても、それぞれ独立して
        無害化されること（片方の定義が、もう片方の参照に誤爆しない）。"""
        out = render("One[^1] and two[^2].\n\n[^1]: shortbody\n\n[^2]: A longer body with spaces.\n")
        assert "#link(" not in out
        assert "\\[^1\\]" in out and "\\[^2\\]" in out
        assert capsys.readouterr().out == ""


class TestCitations:
    def test_renders_as_literal_text(self, capsys):
        out = render("As shown in [@doe2020], the result holds.\n")
        assert out == "As shown in \\[\\@doe2020\\], the result holds.\n\n"
        assert capsys.readouterr().out == ""

    def test_followed_by_a_brace_attribute_interacts_with_the_existing_attrs_plugin(self, capsys):
        """#84のスコープ外の既知の相互作用: citationの直後に`{...}`が続くと、`[text]{attr=val}`
        記法（色指定等、#46）用の`attrs_plugin`が`[@doe2020]{.foo}`を1つのspanとして食べてしまい、
        角括弧が消える（クラッシュはしない）。citation単体（このクラスの他テストの通り）は無関係。
        単なる同時使用は稀なため、#84では対応しない。挙動が変わった場合に気付けるよう記録する。"""
        out = render("See [@doe2020]{.foo}.\n")
        assert out == "See \\@doe2020.\n\n"
        assert capsys.readouterr().out == ""


class TestDefinitionLists:
    def test_renders_as_plain_paragraphs_without_crash(self, capsys):
        out = render("Term 1\n: Definition 1a\n: Definition 1b\n\nTerm 2\n: Definition 2\n")
        assert out == ("Term 1#linebreak()\n: Definition 1a#linebreak()\n: Definition 1b\n\n"
                        "Term 2#linebreak()\n: Definition 2\n\n")
        assert capsys.readouterr().out == ""
