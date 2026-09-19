"""HTML出力（html_output.py・api.render_html、#161）のテスト。

図のうち、外部ツール（ブラウザ・Java・D2）が要るものは、無効にして試す。Mermaidの実描画だけは、ブラウザが
ある環境でだけ実行する。"""
import os
import re

import pytest

import text_compositor.build as build
from text_compositor.api import HtmlResult, Session, render_html

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as f:
        f.write(text)


def convert(tmp_path, markdown, name="doc.md", plugins=PLAIN, output=None, **options):
    """markdownをHTMLにして、(結果, HTML文字列)を返す。"""
    md = tmp_path / name
    write(md, markdown)
    result = render_html(str(md), output, plugins=plugins, **options)
    html = ""
    if result.ok:
        with open(result.html_path, encoding="utf-8") as f:
            html = f.read()
    return result, html


def body(html):
    """<main>の中だけ（CSSを含まない）。"""
    return html.split("<main>", 1)[1].split("</main>", 1)[0]


def messages(result, severity):
    return [d.message for d in result.diagnostics if d.severity == severity]


class TestApi:
    def test_writes_a_standalone_document_next_to_the_markdown(self, tmp_path):
        result, html = convert(tmp_path, "# 見出し\n\n本文。\n")
        assert isinstance(result, HtmlResult)
        assert result.ok and not result.errors
        assert result.html_path == str(tmp_path / ".text-compositor" / "preview.html")
        assert html.startswith("<!DOCTYPE html>")
        assert "<title>見出し</title>" in html
        assert "<h1>見出し</h1>" in html
        assert "<script" not in html and "http-equiv" not in html
        assert set(result.timings_ms) >= {"render", "total"}

    def test_the_title_falls_back_to_the_file_name(self, tmp_path):
        _, html = convert(tmp_path, "本文だけ\n", name="memo.md")
        assert "<title>memo</title>" in html

    def test_the_output_goes_where_requested_and_creates_directories(self, tmp_path):
        out = tmp_path / "out" / "deep" / "x.html"
        result, _ = convert(tmp_path, "# a\n", output=str(out))
        assert result.html_path == str(out) and out.is_file()
        assert not (tmp_path / ".text-compositor" / "preview.html").exists()

    def test_the_output_is_deterministic(self, tmp_path):
        _, first = convert(tmp_path, "# a\n\n[x]{color=red}\n")
        _, second = convert(tmp_path, "# a\n\n[x]{color=red}\n")
        assert first == second

    def test_a_missing_file_is_a_failed_result_not_an_exception(self, tmp_path):
        result = render_html(str(tmp_path / "nope.md"))
        assert not result.ok and result.html_path is None
        assert result.errors and "not found" in result.errors[0].message

    def test_an_unsupported_file_type_is_an_error(self, tmp_path):
        md = tmp_path / "data.csv"
        write(md, "a,b\n1,2\n")
        result = render_html(str(md), plugins=PLAIN)
        assert not result.ok and "Unsupported" in result.errors[0].message

    def test_a_closed_session_fails_cleanly(self, tmp_path):
        md = tmp_path / "a.md"
        write(md, "# a\n")
        session = Session()
        session.close()
        assert not session.render_html(str(md)).ok

    def test_to_dict_has_the_worker_response_shape(self, tmp_path):
        result, _ = convert(tmp_path, "# a\n")
        d = result.to_dict()
        assert d["ok"] is True and d["html"] == result.html_path
        assert set(d) == {"ok", "html", "diagnostics", "timings_ms"}

    def test_variables_are_substituted_and_an_undefined_one_fails(self, tmp_path):
        result, html = convert(tmp_path, "v={{VER}}\n", variables={"VER": "1.2"})
        assert "v=1.2" in html
        failed, _ = convert(tmp_path, "v={{NOPE}}\n", variables={"VER": "1"})
        assert not failed.ok and failed.errors

    def test_nothing_is_printed_to_stdout(self, tmp_path, capfd):
        convert(tmp_path, "# a\n\n<div>x</div>\n")
        assert capfd.readouterr().out == ""


class TestMarkdown:
    def test_common_elements(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n**b** *i* ~~s~~ `c` [l](https://example.com)\n\n- a\n- b\n\n1. x\n\n```python\nprint(1)\n```\n")
        b = body(html)
        assert "<strong>b</strong>" in b and "<em>i</em>" in b and "<s>s</s>" in b and "<code>c</code>" in b
        assert '<a href="https://example.com">l</a>' in b
        assert "<ul>" in b and "<ol>" in b
        assert '<pre><code class="language-python">print(1)\n</code></pre>' in b

    def test_line_breaks_are_kept_like_the_pdf(self, tmp_path):
        _, html = convert(tmp_path, "one\ntwo\n")
        assert "one<br />\ntwo" in html

    def test_text_is_escaped_and_dangerous_links_are_not_links(self, tmp_path):
        _, html = convert(tmp_path, "a <b> & \"q\"\n\n[x](javascript:alert(1))\n\n`<i>`\n")
        b = body(html)
        assert "&amp;" in b and "&quot;q&quot;" in b
        assert "<a " not in b  # javascript: のリンクは、リンクにならない
        assert "<b>" not in b  # 生のタグは、通らない（コードスパンの中だけが、エスケープされて残る）
        assert "<code>&lt;i&gt;</code>" in b

    def test_front_matter_is_not_shown_and_page_keys_are_only_info(self, tmp_path):
        result, html = convert(tmp_path, "---\ntitle: X\npaper_size: a3\nlandscape: true\nfont_size: 12pt\n---\n\n# 本文\n")
        assert "paper_size" not in body(html) and "<hr" not in body(html)
        assert not result.warnings
        assert any("paper_size" in m and "landscape" in m for m in messages(result, "info"))

    def test_an_unknown_front_matter_key_still_warns(self, tmp_path):
        result, _ = convert(tmp_path, "---\nfoo: 1\n---\n\n# a\n")
        assert any("foo" in m for m in messages(result, "warning"))

    def test_pagebreak_and_directives_are_ignored_without_warnings(self, tmp_path):
        result, html = convert(tmp_path, "<!-- header: X -->\n\na\n\n<!-- pagebreak -->\n\nb\n")
        assert not result.warnings
        assert "<!--" not in html
        assert any("pagebreak" in m for m in messages(result, "info"))

    def test_a_horizontal_rule_is_always_an_hr(self, tmp_path):
        _, html = convert(tmp_path, "a\n\n---\n\nb\n")
        assert "<hr />" in html

    def test_raw_html_is_dropped_with_a_warning_and_its_line(self, tmp_path):
        result, html = convert(tmp_path, "a\n\n<div>raw</div>\n\nx <br> y\n")
        assert "<div>raw</div>" not in body(html)
        warnings = [d for d in result.warnings if "HTML" in d.message]
        assert {d.line for d in warnings} >= {3}
        assert len(warnings) == 2

    @pytest.mark.parametrize("kind", ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"])
    def test_alerts(self, tmp_path, kind):
        _, html = convert(tmp_path, f"> [!{kind}]\n> text\n")
        b = body(html)
        assert f'class="alert alert-{kind.lower()}"' in b and kind.capitalize() in b
        assert "[!" not in b and "<blockquote>" not in b

    def test_a_plain_quote_stays_a_blockquote(self, tmp_path):
        _, html = convert(tmp_path, "> plain\n\n> [!NOTE]\n> n\n\n> again\n")
        assert body(html).count("<blockquote>") == 2 and body(html).count("</blockquote>") == 2

    def test_color_and_size_spans(self, tmp_path):
        _, html = convert(tmp_path, '[a]{color=red} [b]{color="#00f"} [c]{size=10pt} [d]{color=red size=12pt} <span style="color:green">g</span>\n')
        b = body(html)
        assert '<span style="color:red">a</span>' in b
        assert '<span style="color:#00f">b</span>' in b
        assert '<span style="font-size:10pt">c</span>' in b
        assert '<span style="color:red;font-size:12pt">d</span>' in b
        assert '<span style="color:green">g</span>' in b

    def test_invalid_span_values_are_ignored_with_a_warning_and_cannot_inject_css(self, tmp_path):
        result, html = convert(tmp_path, '[a]{color="red;background:url(x)"} [b]{size=big}\n')
        b = body(html)
        assert "background" not in b and "url(" not in b and "font-size" not in b
        assert len(result.warnings) == 2

    def test_an_unclosed_html_span_is_closed_with_a_warning(self, tmp_path):
        result, html = convert(tmp_path, 'x <span style="color:red">open\n')
        assert body(html).count("<span") == body(html).count("</span>") == 1
        assert any("Unclosed" in m for m in messages(result, "warning"))

    def test_task_lists_become_disabled_checkboxes(self, tmp_path):
        result, html = convert(tmp_path, "- [x] done\n- [ ] todo\n")
        assert '<input type="checkbox" disabled checked>' in html
        assert '<input type="checkbox" disabled>' in html
        assert not result.warnings

    def test_table_cells_can_have_background_and_border(self, tmp_path):
        _, html = convert(tmp_path, '| a | b |\n| :-- | --: |\n| [x]{bg="#d9f2d9"} | [y]{bg=red border=dashed} |\n')
        b = body(html)
        assert 'style="text-align:left;background:#d9f2d9"' in b
        assert "background:red;border:1px dashed currentColor" in b
        assert "text-align:right" in b

    def test_bg_outside_a_whole_cell_warns(self, tmp_path):
        result, _ = convert(tmp_path, "text [x]{bg=red} text\n")
        assert any("bg/border" in m for m in messages(result, "warning"))

    def test_the_line_of_a_warning_counts_from_the_top_of_the_file(self, tmp_path):
        text = "# a\n\n::: align {align=right}\nx\n:::\n\ntext\n\n<div>raw</div>\n"
        result, _ = convert(tmp_path, text)
        warning = next(d for d in result.warnings if "HTML" in d.message)
        assert warning.line == 9


class TestImages:
    def test_size_and_alignment_from_the_alt_text(self, tmp_path):
        write(tmp_path / "p.png", "x")
        _, html = convert(tmp_path, "![説明|width=50%|height=8cm|align=center](p.png)\n")
        b = body(html)
        assert 'alt="説明"' in b
        assert "width:50%;height:8cm;display:block;margin-left:auto;margin-right:auto" in b

    def test_the_url_is_relative_to_the_html_and_quoted(self, tmp_path):
        write(tmp_path / "img" / "画像 1.png", "x")
        result, html = convert(tmp_path, "![a](<img/画像 1.png>)\n", output=str(tmp_path / "out" / "d.html"))
        assert 'src="../img/%E7%94%BB%E5%83%8F%201.png"' in html
        assert not result.warnings

    def test_a_missing_image_warns_but_the_page_is_still_produced(self, tmp_path):
        result, html = convert(tmp_path, "a\n\n![x](missing.png)\n")
        assert result.ok
        assert '<img src="../missing.png"' in html
        warning = result.warnings[0]
        assert "Image not found" in warning.message and warning.line == 3

    def test_external_urls_are_kept(self, tmp_path):
        result, html = convert(tmp_path, "![x](https://example.com/a.png)\n")
        assert 'src="https://example.com/a.png"' in html and not result.warnings

    def test_invalid_size_units_are_ignored_with_a_warning(self, tmp_path):
        write(tmp_path / "p.png", "x")
        result, html = convert(tmp_path, "![x|width=3fr|align=diagonal](p.png)\n")
        assert "style=" not in body(html)
        assert len(result.warnings) == 2


class TestFences:
    def test_an_svg_fence_becomes_an_img_of_a_cached_file(self, tmp_path):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
        result, html = convert(tmp_path, f"```svg {{width=200pt}}\n{svg}\n```\n")
        m = re.search(r'<img src="([^"]+)" alt="svg diagram" style="width:200pt">', html)
        assert m, html
        cached = (tmp_path / ".text-compositor" / "preview.html").parent / m.group(1)
        assert cached.read_text(encoding="utf-8").startswith("<svg")
        assert not result.warnings

    @pytest.mark.parametrize("lang", ["dot", "graphviz"])
    def test_graphviz_is_shown_as_code_with_a_warning(self, tmp_path, lang):
        result, html = convert(tmp_path, f"a\n\n```{lang}\ndigraph {{ a -> b }}\n```\n")
        assert f'<code class="language-{lang}">digraph {{ a -&gt; b }}' in html
        warning = result.warnings[0]
        assert "#181" in warning.message and warning.line == 3

    def test_typst_exec_is_shown_as_code_and_never_executed(self, tmp_path):
        # reviewed/ の外でも、実行しないため、エラーにならない
        result, html = convert(tmp_path, "```typst-exec\n#lorem(3)\n```\n")
        assert result.ok and "#lorem(3)" in html
        assert any("#182" in m for m in messages(result, "warning"))

    def test_a_disabled_plugin_falls_back_to_code_without_a_warning(self, tmp_path):
        result, html = convert(tmp_path, "```mermaid\ngraph TD\n A-->B\n```\n\n```plantuml\n@startuml\n@enduml\n```\n\n```d2\na -> b\n```\n")
        assert body(html).count("<pre>") == 3 and "<img" not in html
        assert not result.warnings

    def test_other_languages_are_plain_code_blocks(self, tmp_path):
        _, html = convert(tmp_path, "```\n<b>&\n```\n")
        assert "<pre><code>&lt;b&gt;&amp;\n</code></pre>" in html

    def test_a_diagram_source_file_is_a_page_with_that_diagram(self, tmp_path):
        result, html = convert(tmp_path, "graph TD\n A-->B\n", name="flow.mmd")
        assert result.ok
        assert "<title>flow</title>" in html and "language-mermaid" in body(html)  # プラグイン無効: コード表示

    def test_a_graphviz_source_file_warns(self, tmp_path):
        result, html = convert(tmp_path, "digraph { a -> b }\n", name="g.dot")
        assert result.ok and any("#181" in m for m in messages(result, "warning"))


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return build.find_system_browser() is not None


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
class TestMermaid:
    def test_a_mermaid_fence_becomes_an_svg_image_and_is_cached(self, tmp_path):
        md = tmp_path / "doc.md"
        write(md, "# T\n\n```mermaid\ngraph LR\n  A[開始] --> B[終了]\n```\n")
        with Session() as session:
            first = session.render_html(str(md), plugins={"plantuml": False, "d2": False})
            assert first.ok, first.diagnostics
            html = open(first.html_path, encoding="utf-8").read()
            m = re.search(r'<img src="([^"]+\.svg)" alt="mermaid diagram">', html)
            assert m
            svg_path = os.path.join(os.path.dirname(first.html_path), m.group(1))
            assert "<svg" in open(svg_path, encoding="utf-8").read()
            mtime = os.path.getmtime(svg_path)

            second = session.render_html(str(md), plugins={"plantuml": False, "d2": False})
            assert second.ok and os.path.getmtime(svg_path) == mtime  # 再描画しない
            assert second.timings_ms["render"] < first.timings_ms["render"]


class TestLayoutBlocks:
    SVG = '```svg\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>\n```'

    def test_layout_right_puts_the_text_left_and_the_diagram_right(self, tmp_path):
        _, html = convert(tmp_path, f"::: layout-right {{left=30 right=70}}\n説明文\n\n{self.SVG}\n:::\n")
        cells = re.findall(r'<td style="width:([\d.]+)%">(.*?)</td>', body(html), re.S)
        assert [c[0] for c in cells] == ["30.0", "70.0"]
        assert "説明文" in cells[0][1] and "<img" in cells[1][1]

    def test_layout_left_flips_the_columns_and_the_default_ratio(self, tmp_path):
        _, html = convert(tmp_path, f"::: layout-left\n説明文\n\n{self.SVG}\n:::\n")
        cells = re.findall(r'<td style="width:([\d.]+)%">(.*?)</td>', body(html), re.S)
        assert [c[0] for c in cells] == ["65.0", "35.0"]
        assert "<img" in cells[0][1] and "説明文" in cells[1][1]

    def test_layout_compare_needs_exactly_two_figures(self, tmp_path):
        ok, html = convert(tmp_path, f"::: layout-compare\nA\n\n{self.SVG}\n\nB\n\n{self.SVG}\n:::\n")
        assert ok.ok and body(html).count("<img") == 2 and 'width:50%' in body(html)
        bad, _ = convert(tmp_path, f"::: layout-compare\n{self.SVG}\n:::\n")
        assert not bad.ok and "exactly two" in bad.errors[0].message

    def test_a_layout_block_without_a_figure_is_an_error(self, tmp_path):
        result, _ = convert(tmp_path, "::: layout-right\ntext only\n:::\n")
        assert not result.ok and "layout-right" in result.errors[0].message

    def test_layout_feature_overlays_the_caption(self, tmp_path):
        write(tmp_path / "p.png", "x")
        _, html = convert(tmp_path, "::: layout-feature\nキャッチ\n\n![](p.png)\n:::\n")
        assert '<div class="feature">' in html and "feature-caption" in html and "キャッチ" in html

    def test_layout_columns_takahashi_and_align(self, tmp_path):
        _, html = convert(tmp_path, "::: layout-columns {n=3}\na\n:::\n\n::: layout-takahashi {size=40pt}\nb\n:::\n\n::: align {align=right}\nc\n:::\n")
        b = body(html)
        assert 'column-count:3' in b and 'font-size:40pt' in b and 'text-align:right' in b

    def test_invalid_layout_attributes_fall_back_with_a_warning(self, tmp_path):
        result, html = convert(tmp_path, "::: layout-columns {n=x}\na\n:::\n\n::: align {align=up}\nb\n:::\n\n::: layout-takahashi {size=big}\nc\n:::\n")
        b = body(html)
        assert 'column-count:2' in b and 'text-align:left' in b and 'font-size:96pt' in b
        assert len(result.warnings) == 3

    def test_a_block_look_alike_inside_a_code_fence_is_not_a_block(self, tmp_path):
        _, html = convert(tmp_path, "````\n::: align {align=right}\nx\n:::\n````\n")
        assert "text-align:right" not in body(html) and "::: align" in html
