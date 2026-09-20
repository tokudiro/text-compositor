"""HTML出力（html_output.py・api.render_html、#161）のテスト。

図のうち、外部ツール（ブラウザ・Java・D2）が要るものは、無効にして試す。Mermaidの実描画だけは、ブラウザが
ある環境でだけ実行する。"""
import os
import re

import pytest

import text_compositor.host_renderers as host_renderers_mod
import text_compositor.renderer as renderer_mod
from text_compositor.deps import find_system_browser
from text_compositor.renderer import TypstRenderer
import subprocess
from text_compositor.api import HtmlResult, Session, render_html
from text_compositor import html_output
from text_compositor.html_output import DOCUMENT_CSS

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


class FakeGraphvizHost:
    """ViewerのElectronの代わりに、Graphvizの描画を引き受ける。"""

    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>graphviz from the host</text></svg>'

    def __init__(self):
        self.calls = []
        self.error = None

    def __call__(self, diagram_id, code, js_path):
        self.calls.append({"diagram_id": diagram_id, "code": code, "js": js_path})
        if self.error:
            raise RuntimeError(self.error)
        return self.svg


@pytest.fixture
def graphviz_host(monkeypatch):
    host = FakeGraphvizHost()
    monkeypatch.setattr(host_renderers_mod, "_graphviz_host_renderer", host)
    monkeypatch.setattr(renderer_mod, "ensure_viz_js", lambda: "fake-viz-global.js")
    return host


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
        assert "<script" not in html
        # スクリプトは、ブラウザ側でも禁止する（Viewerは、JavaScriptを有効にしたビューで開く）
        assert "script-src 'none'" in html and "object-src 'none'" in html
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

    def test_an_unsupported_file_type_is_an_error_that_says_what_can_be_opened(self, tmp_path):
        other = tmp_path / "data.bin"
        other.write_bytes(b"\x00\x01\x02binary\x00")
        result = render_html(str(other), plugins=PLAIN)
        assert not result.ok and "not supported" in result.errors[0].message
        assert "Markdown（.md）" in result.errors[0].detail

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
        assert set(d) == {"ok", "html", "diagnostics", "timings_ms", "dependencies"}

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


class TestDependencies:
    """参照しているローカルのファイル（画像など）を返す。Viewerが、変更を検知して、自動で更新するために使う（#170）。"""

    def test_referenced_images_are_returned_as_absolute_sorted_paths(self, tmp_path):
        write(tmp_path / "b.png", "x")
        write(tmp_path / "img" / "a.png", "x")
        result, _ = convert(tmp_path, "![a](img/a.png)\n\n![b](b.png)\n\n![again](img/a.png)\n")
        assert result.ok
        assert result.dependencies == sorted([str(tmp_path / "b.png"), str(tmp_path / "img" / "a.png")])
        assert all(os.path.isabs(p) for p in result.dependencies)

    def test_the_markdown_itself_and_external_urls_are_not_included(self, tmp_path):
        result, _ = convert(tmp_path, "# a\n\n![x](https://example.com/a.png)\n")
        assert result.dependencies == []

    def test_a_missing_image_is_included_so_that_creating_it_triggers_an_update(self, tmp_path):
        result, _ = convert(tmp_path, "![x](missing.png)\n")
        assert result.dependencies == [str(tmp_path / "missing.png")]

    def test_layout_feature_images_are_included(self, tmp_path):
        write(tmp_path / "p.png", "x")
        result, _ = convert(tmp_path, "::: layout-feature\nキャッチ\n\n![](p.png)\n:::\n")
        assert result.dependencies == [str(tmp_path / "p.png")]

    def test_dependencies_do_not_leak_between_conversions(self, tmp_path):
        write(tmp_path / "p.png", "x")
        with Session() as session:
            md = tmp_path / "doc.md"
            write(md, "![x](p.png)\n")
            first = session.render_html(str(md), plugins=PLAIN)
            write(md, "# no images\n")
            second = session.render_html(str(md), plugins=PLAIN)
        assert first.dependencies and second.dependencies == []

    def test_a_failed_conversion_returns_none(self, tmp_path):
        result = render_html(str(tmp_path / "nope.md"))
        assert not result.ok and result.dependencies == []


class TestOutsideTheDocumentFolder:
    """Viewerは、原稿のフォルダに何も書かないため、HTMLと図のキャッシュを、別の場所に出す（#258）。"""

    SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'

    def test_nothing_is_written_next_to_the_document(self, tmp_path):
        docs = tmp_path / "docs"
        work = tmp_path / "work"
        result, html = convert(docs, f"```svg\n{self.SVG}\n```\n",
                               output=str(work / "html" / "a.html"), cache_dir=str(work / "cache"))
        assert result.ok
        assert result.html_path == str(work / "html" / "a.html")
        assert sorted(os.listdir(str(docs))) == ["doc.md"]          # .text-compositor/ が無い
        m = re.search(r'<img src="([^"]+)" alt="svg diagram"', html)
        assert m, html
        cached = (work / "html" / m.group(1)).resolve()               # HTMLからの相対URLで、キャッシュに届く
        assert cached.parent == (work / "cache").resolve() and cached.read_text(encoding="utf-8").startswith("<svg")

    def test_a_document_image_is_still_found_from_the_moved_html(self, tmp_path):
        docs = tmp_path / "docs"
        write(docs / "img" / "p.png", "x")
        result, html = convert(docs, "![p](img/p.png)\n", output=str(tmp_path / "work" / "a.html"),
                               cache_dir=str(tmp_path / "work" / "cache"))
        m = re.search(r'<img src="([^"]+)"', html)
        assert (tmp_path / "work" / m.group(1)).resolve() == (docs / "img" / "p.png").resolve()

    def test_without_cache_dir_the_cache_stays_next_to_the_document(self, tmp_path):
        result, html = convert(tmp_path, f"```svg\n{self.SVG}\n```\n")
        assert list((tmp_path / ".text-compositor" / "cache").glob("svg_*.svg"))


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
    def test_graphviz_without_a_host_is_shown_as_code_with_a_warning(self, tmp_path, lang):
        # Viewer（Electron）以外には、Graphvizを描く手段がない（#181）
        result, html = convert(tmp_path, f"a\n\n```{lang}\ndigraph {{ a -> b }}\n```\n")
        assert f'<code class="language-{lang}">digraph {{ a -&gt; b }}' in html
        warning = result.warnings[0]
        assert "Viewer" in warning.message and warning.line == 3

    def test_graphviz_is_disabled_by_the_plugin_setting_without_a_warning(self, tmp_path, graphviz_host):
        result, html = convert(tmp_path, "```dot\ndigraph { a -> b }\n```\n", plugins={**PLAIN, "graphviz": False})
        assert 'class="language-dot"' in html and not result.warnings
        assert graphviz_host.calls == []

    @pytest.mark.parametrize("lang", ["dot", "graphviz"])
    def test_graphviz_with_a_host_becomes_a_cached_img(self, tmp_path, graphviz_host, lang):
        result, html = convert(tmp_path, f"a\n\n```{lang} {{width=300pt}}\ndigraph {{ a -> b }}\n```\n")
        assert result.ok and not result.warnings
        m = re.search(r'<img src="([^"]+)" alt="' + lang + r' diagram" style="width:300pt">', html)
        assert m, html
        cached = tmp_path / ".text-compositor" / m.group(1)
        assert cached.read_text(encoding="utf-8") == graphviz_host.svg
        assert [c["code"] for c in graphviz_host.calls] == ["digraph { a -> b }\n"]
        assert graphviz_host.calls[0]["js"] == "fake-viz-global.js"
        assert graphviz_host.calls[0]["diagram_id"].startswith("graphviz-")

    def test_a_graphviz_result_is_cached_and_the_cache_key_follows_the_viz_version(self, tmp_path, graphviz_host, monkeypatch):
        doc = "```dot\ndigraph { a -> b }\n```\n"
        convert(tmp_path, doc)
        convert(tmp_path, doc)
        assert len(graphviz_host.calls) == 1   # 2回目は、キャッシュ
        monkeypatch.setattr(renderer_mod, "VIZ_JS_SHA256", "0" * 64)   # Viz.jsが変われば、描き直す
        convert(tmp_path, doc)
        assert len(graphviz_host.calls) == 2
        monkeypatch.setattr(renderer_mod, "GRAPHVIZ_FIT_REVISION", 99)   # 文字幅の補正が変わっても、描き直す
        convert(tmp_path, doc)
        assert len(graphviz_host.calls) == 3

    def test_a_graphviz_error_from_the_host_is_a_diagnostic_with_the_fence_line(self, tmp_path, graphviz_host):
        graphviz_host.error = "syntax error in line 1 near '}'"
        result, _ = convert(tmp_path, "a\n\n```dot\ngraph { a -- b -- }\n```\n")
        assert not result.ok
        error = result.errors[0]
        assert error.message == "Graphviz diagram failed to render"
        assert error.line == 3 and "syntax error in line 1" in error.detail

    def test_a_graphviz_source_file_is_a_page_with_that_diagram(self, tmp_path, graphviz_host):
        result, html = convert(tmp_path, "digraph { a -> b }\n", name="g.gv")
        assert result.ok and not result.warnings
        assert 'class="diagram diagram-graphviz"' in body(html) and 'alt="graphviz diagram"' in body(html)

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

    def test_a_graphviz_source_file_without_a_host_warns(self, tmp_path):
        result, html = convert(tmp_path, "digraph { a -> b }\n", name="g.dot")
        assert result.ok and any("Viewer" in m for m in messages(result, "warning"))
        assert 'class="language-graphviz"' in body(html)


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)

def plain(html):
    """テキストファイルのページの、`<pre>`の中身（エスケープされたまま）。"""
    return html.split('<pre class="plain-text">', 1)[1].split("</pre>", 1)[0]


def error_of(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    result = render_html(str(path), plugins=PLAIN)
    assert not result.ok, name
    return result.errors[0]


class TestTextFiles:
    """`.txt`・`.csv`・`.svg`の表示と、対象外のファイルの案内（#196）。"""

    def test_a_txt_file_is_shown_as_plain_text_not_as_markdown(self, tmp_path):
        text = "# not a heading\n- not a list\n    indented **not bold**\n\n<b>tag</b> & more\n"
        result, html = convert(tmp_path, text, name="memo.txt")
        assert result.ok and not result.warnings
        assert "<h1>" not in html and "<ul>" not in html and "<strong>" not in html
        assert plain(html) == "# not a heading\n- not a list\n    indented **not bold**\n\n&lt;b&gt;tag&lt;/b&gt; &amp; more\n"
        assert "<title>memo</title>" in html

    def test_an_empty_txt_file_is_shown_empty(self, tmp_path):
        result, html = convert(tmp_path, "", name="empty.txt")
        assert result.ok and plain(html) == ""

    @pytest.mark.parametrize("name", ["settings.yaml", "data.json", "script.py", "page.html", "README", "app.log", "image.png", "doc.pdf"])
    def test_other_files_are_an_error_with_a_guide(self, tmp_path, name):
        error = error_of(tmp_path, name, "content")
        assert "cannot be opened" in error.message
        assert "Markdown（.md）" in error.detail and "テキスト（.txt）" in error.detail

    def test_settings_files_and_source_code_point_to_the_follow_up_issue(self, tmp_path):
        for name in ("a.yaml", "a.yml", "a.json", "a.py"):
            assert "#218" in error_of(tmp_path, name, "x").detail, name

    def test_html_is_never_opened(self, tmp_path):
        error = error_of(tmp_path, "page.html", "<script>alert(1)</script>")
        assert "スクリプトを実行しない" in error.detail

    def test_only_utf8_without_bom_is_accepted(self, tmp_path):
        bom = error_of(tmp_path, "bom.txt", b"\xef\xbb\xbfabc")
        assert "not UTF-8" in bom.message and "BOMつきのUTF-8" in bom.detail
        utf16 = error_of(tmp_path, "u16.txt", "hello".encode("utf-16"))
        assert "not UTF-8" in utf16.message and "UTF-16" in utf16.detail
        sjis = error_of(tmp_path, "sjis.txt", "日本語のメモ".encode("cp932"))
        assert "not UTF-8" in sjis.message and "Shift_JIS" in sjis.detail
        assert "UTF-8（BOMなし）で保存し直して" in sjis.detail

    def test_a_txt_file_with_nul_bytes_is_a_binary_error(self, tmp_path):
        error = error_of(tmp_path, "a.txt", b"text\x00with a nul")
        assert "binary file" in error.message

    def test_a_large_txt_file_is_cut_at_the_limit_with_a_note_and_a_warning(self, tmp_path, monkeypatch):
        monkeypatch.setattr(html_output, "TEXT_MAX_BYTES", 1000)
        md = tmp_path / "big.txt"
        md.write_text("あ" * 2000, encoding="utf-8")   # 1文字3バイト。1000バイトは、文字の途中で切れる
        result = render_html(str(md), plugins=PLAIN)
        html = open(result.html_path, encoding="utf-8").read()
        assert result.ok and any("large" in w.message for w in result.warnings)
        assert "ファイルが大きいため、先頭の約" in html
        shown = plain(html)
        assert set(shown) == {"あ"} and len(shown) == 333   # 切れた1文字は、捨てる

    def test_the_default_limit_is_512_kb(self):
        assert html_output.TEXT_MAX_BYTES == 512 * 1024


class TestCsvFiles:
    def test_a_csv_file_becomes_a_table_with_a_header_row(self, tmp_path):
        result, html = convert(tmp_path, 'name,qty,note\nりんご,10,"甘い, 赤い"\nみかん,3,\n', name="items.csv")
        assert result.ok
        table = html.split('<table class="csv">', 1)[1].split("</table>", 1)[0]
        assert "<thead><tr><th>name</th><th>qty</th><th>note</th></tr></thead>" in table
        assert "<tr><td>りんご</td><td>10</td><td>甘い, 赤い</td></tr>" in table
        assert "<tr><td>みかん</td><td>3</td><td></td></tr>" in table

    def test_cells_are_escaped_and_short_rows_are_padded(self, tmp_path):
        _, html = convert(tmp_path, 'a,b,c\n<i>x</i>,"line1\nline2"\n', name="x.csv")
        assert "<td>&lt;i&gt;x&lt;/i&gt;</td>" in html and "<i>" not in html.split("<tbody>", 1)[1]
        assert "<td>line1\nline2</td><td></td>" in html   # 列が足りない行は、空のセルで、そろえる

    def test_an_empty_csv_says_so(self, tmp_path):
        result, html = convert(tmp_path, "", name="empty.csv")
        assert result.ok and "空のCSVファイルです" in html and "<table" not in html

    def test_a_large_csv_is_cut_at_a_whole_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(html_output, "TEXT_MAX_BYTES", 50)
        body = "h1,h2\n" + "".join(f"row{i:03d},value\n" for i in range(100))
        result, html = convert(tmp_path, body, name="big.csv")
        assert result.ok and any("large" in w.message for w in result.warnings)
        assert "ファイルが大きいため" in html
        cells = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert cells.count("<tr>") >= 1 and "<td>row000</td><td>value</td>" in cells
        assert cells.rstrip().endswith("</tr>")   # 切れた行が、混ざらない

    def test_without_a_header_every_row_is_a_data_row(self, tmp_path):
        md = tmp_path / "raw.csv"
        md.write_text("りんご,10\nみかん,3\n", encoding="utf-8")
        result = render_html(str(md), plugins=PLAIN, csv_header=False)
        html = open(result.html_path, encoding="utf-8").read()
        assert result.ok and "<thead>" not in html and "<th>" not in html
        assert "<tr><td>りんご</td><td>10</td></tr>" in html and "<tr><td>みかん</td><td>3</td></tr>" in html

    def test_the_header_is_the_default(self, tmp_path):
        md = tmp_path / "raw.csv"
        md.write_text("a,b\n1,2\n", encoding="utf-8")
        html = open(render_html(str(md), plugins=PLAIN).html_path, encoding="utf-8").read()
        assert "<thead><tr><th>a</th><th>b</th></tr></thead>" in html
    def test_a_csv_with_a_bom_or_other_encoding_is_an_error(self, tmp_path):
        assert "not UTF-8" in error_of(tmp_path, "b.csv", b"\xef\xbb\xbfa,b\n").message
        assert "not UTF-8" in error_of(tmp_path, "s.csv", "名前,数\n".encode("cp932")).message


class TestSvgFiles:
    SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script>alert(1)</script><rect width="10" height="10"/></svg>'

    def test_an_svg_file_is_shown_as_an_image_and_never_inlined(self, tmp_path):
        result, html = convert(tmp_path, self.SVG, name="pic.svg")
        assert result.ok
        assert '<img src="../pic.svg" alt="pic.svg">' in html
        assert "<script>alert(1)</script>" not in html   # ファイルの中身は、ページに入れない（<img>は、スクリプトを実行しない）

    def test_the_svg_file_is_a_dependency_so_that_saving_it_updates_the_view(self, tmp_path):
        result, _ = convert(tmp_path, self.SVG, name="pic.svg")
        assert result.dependencies == [str(tmp_path / "pic.svg")]


class TestDarkColors:
    """ダークの配色でも、alertの見出し（本文と同じ大きさの文字）が、読めること（#192）。
    WCAG 2.1のAA（コントラスト比4.5:1）を基準にする。"""

    def test_alert_titles_are_readable_on_the_dark_background(self):
        background = re.search(r"prefers-color-scheme: dark\) \{ :root \{[^}]*--code-bg: (#[0-9a-f]{6})", DOCUMENT_CSS).group(1)
        dark_alerts = DOCUMENT_CSS.split("@media (prefers-color-scheme: dark) {\n  .alert-note", 1)[1]
        colors = dict(re.findall(r"\.alert-(\w+) \{ --alert: (#[0-9a-f]{6}); \}", ".alert-note" + dark_alerts))
        assert set(colors) == {"note", "tip", "important", "warning", "caution"}
        for kind, color in colors.items():
            assert _contrast(color, background) >= 4.5, f"{kind}: {color} on {background}"

    def test_diagrams_are_inverted_only_in_the_dark_scheme(self):
        """図のSVGは、ライト用の配色で描画される。ダークでは、明暗を反転して、背景になじませる（#209）。ライトは、変えない。"""
        dark_only = re.search(r"@media \(prefers-color-scheme: dark\) \{ \.diagram img \{([^}]*)\} \}", DOCUMENT_CSS)
        assert dark_only, "the dark scheme has no rule for .diagram img"
        assert "filter: invert(1) hue-rotate(180deg)" in dark_only.group(1)
        assert "mix-blend-mode: lighten" in dark_only.group(1)   # 不透明な白い背景が、黒い四角にならないように
        without_dark_rule = DOCUMENT_CSS.replace(dark_only.group(0), "")
        assert ".diagram img" not in without_dark_rule

    @staticmethod
    def _after_dark_filter(hex_color):
        """`invert(1) hue-rotate(180deg)`が、色をどう変えるか（CSSの仕様の式。sRGBの値に、行列を掛ける）。"""
        inverted = [1 - int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        matrix = [[-0.574, 1.430, 0.144], [0.426, 0.430, 0.144], [0.426, 1.430, -0.856]]
        rgb = [min(1, max(0, sum(m * c for m, c in zip(row, inverted)))) for row in matrix]
        return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)

    def test_the_default_text_colors_of_each_diagram_tool_are_readable_after_the_filter(self):
        """各ツールが、既定で使う文字の色（実際のSVGから測った値）が、反転したあとも、ダークの背景の上で、4.5:1以上になること。"""
        background = re.search(r"prefers-color-scheme: dark\) \{ :root \{[^}]*--bg: (#[0-9a-f]{6})", DOCUMENT_CSS).group(1)
        for tool, color in {"mermaid": "#333333", "plantuml": "#000000", "d2 (label)": "#676c7e"}.items():
            shown = self._after_dark_filter(color)
            assert _contrast(shown, background) >= 4.5, f"{tool}: {color} -> {shown} on {background}"

    def test_the_filter_keeps_black_and_white_as_the_inverse(self):
        assert self._after_dark_filter("#000000") == "#ffffff"
        assert self._after_dark_filter("#ffffff") == "#000000"


class TestDiagramFailures:
    """図の描画に失敗したときの診断（#202）。messageは短い要約、ツールの出力はdetail、位置は原稿の行。
    外部ツールは、差し替えて、失敗を再現する。"""

    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "err: syntax error at line 1\n"

    def test_a_failed_d2_diagram_reports_a_short_message_the_line_and_the_tool_output(self, tmp_path, monkeypatch):
        monkeypatch.setattr(TypstRenderer, "_ensure_d2_bin", lambda self: "d2")
        monkeypatch.setattr(TypstRenderer, "_d2_version", lambda self: "v0")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: self._Failed())
        result, _ = convert(tmp_path, "# T\n\n本文。\n\n```d2\nx -> \n```\n", plugins={"mermaid": False, "plantuml": False, "d2": True})
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "d2 diagram failed to render"
        assert error.line == 5 and error.file.endswith("doc.md")
        assert "syntax error at line 1" in error.detail

    def test_a_failed_mermaid_diagram_drops_the_internal_stack_from_the_detail(self, tmp_path, monkeypatch):
        class Page:
            def evaluate(self, *args):
                raise RuntimeError("Page.evaluate: Error: Parse error on line 3:\n  A --> \n    at Parser.parse (<anonymous>:1:1)\n    at fTe.parse (<anonymous>:2:2)")

        monkeypatch.setattr(TypstRenderer, "_ensure_mermaid_page", lambda self: Page())
        result, _ = convert(tmp_path, "```mermaid\ngraph TD\n  A --> \n```\n", plugins={"mermaid": True, "plantuml": False, "d2": False})
        assert not result.ok
        error = [d for d in result.diagnostics if d.severity == "error"][0]
        assert error.message == "mermaid diagram failed to render" and error.line == 1
        assert "Parse error on line 3" in error.detail and "Parser.parse" not in error.detail

    def test_the_cli_text_keeps_the_previous_wording(self, tmp_path, monkeypatch, capsys):
        renderer = TypstRenderer.__new__(TypstRenderer)
        renderer.current_file = "doc.md"
        renderer._diagram_error("d2", "boom\n", None)
        assert "[Error] d2 rendering failed for doc.md:\nboom" in capsys.readouterr().out


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return find_system_browser() is not None


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
