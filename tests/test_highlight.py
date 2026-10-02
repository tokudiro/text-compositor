"""HTML出力のシンタックスハイライト（#218）のテスト。

Pygmentsが、あるときと、無いときの両方を確かめる（無いときは、等幅の素の表示に戻る）。
"""
import re

import pytest

from text_compositor import highlight
from text_compositor.api import render_html

pygments = pytest.importorskip("pygments")

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


def convert(tmp_path, name, text):
    path = tmp_path / name
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    result = render_html(str(path), plugins=PLAIN)
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


@pytest.fixture
def without_pygments(monkeypatch):
    """Pygmentsが、入っていない環境を、まねる。"""
    highlight._pygments.cache_clear()
    highlight.css.cache_clear()
    monkeypatch.setattr(highlight, "_pygments", lambda: None)
    yield
    monkeypatch.undo()
    highlight._pygments.cache_clear()
    highlight.css.cache_clear()


def test_the_viewer_and_the_worker_list_the_same_extensions():
    """Viewerのファイルを開くダイアログの拡張子（viewer/src/targets.js）と、ワーカーの対応（SOURCE_FILE_LANGS）が、そろっている。"""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "viewer" / "src" / "targets.js").read_text(encoding="utf-8")
    block = re.search(r"const SOURCE_EXTENSIONS = \[(.*?)\];", js, re.S).group(1)
    assert set(re.findall(r"'(\.[a-z0-9]+)'", block)) == set(highlight.SOURCE_FILE_LANGS)


class TestHighlightHtml:
    def test_code_becomes_spans_and_is_escaped(self):
        html = highlight.highlight_html('x = "<b>"  # c', "python")
        assert '<span class="s2">' in html and "&lt;b&gt;" in html and "<b>" not in html

    @pytest.mark.parametrize("lang", ["", "nosuchlanguage"])
    def test_an_unknown_or_empty_language_is_not_highlighted(self, lang):
        assert highlight.highlight_html("x", lang) is None

    def test_every_listed_extension_has_a_lexer(self):
        for ext, lang in highlight.SOURCE_FILE_LANGS.items():
            assert highlight.highlight_html("x", lang) is not None, (ext, lang)

    def test_the_css_has_light_and_dark_rules_scoped_to_the_code(self):
        css = highlight.css()
        assert "code.highlighted .k {" in css
        assert "@media (prefers-color-scheme: dark)" in css
        assert "/*" not in css.split("*/", 1)[1]   # 注釈は、先頭の1つだけ
        assert not any(line.strip().startswith(("pre", "body", "td.linenos")) for line in css.splitlines())


class TestSourceFiles:
    @pytest.mark.parametrize("name,text,marker", [
        ("a.yaml", "key: value\nlist:\n  - 1\n", '<span class="nt">key</span>'),
        ("a.yml", "k: v\n", '<span class="nt">k</span>'),
        ("a.json", '{"a": [1, true]}\n', '<span class="nt">"a"</span>'),
        ("a.py", "def f():\n    return 1\n", '<span class="k">def</span>'),
        ("a.js", "const x = 1;\n", '<span class="[a-z]+">const</span>'),
        ("a.toml", "[t]\nk = 1\n", '<span class="[a-z]+">k</span>'),
    ])
    def test_a_source_file_is_shown_highlighted_in_a_monospace_block(self, tmp_path, name, text, marker):
        result, html = convert(tmp_path, name, text)
        assert result.ok and not result.warnings, result.diagnostics
        assert '<pre class="plain-text"><code class="language-' in html and " highlighted\">" in html
        assert re.search(marker, html), marker
        assert "code.highlighted .k {" in html   # 色のCSSが、ページに入る

    def test_the_text_is_not_interpreted_as_markdown(self, tmp_path):
        _, html = convert(tmp_path, "a.yaml", "# not a heading\n- not a list\n")
        assert "<h1" not in html and "<ul>" not in html

    def test_html_is_shown_as_source_and_never_run(self, tmp_path):
        result, html = convert(tmp_path, "page.html", "<script>alert(1)</script>\n")
        assert result.ok
        assert "<script>alert(1)</script>" not in html   # 実行できる形では、入らない
        assert "&lt;" in html and "alert" in html

    def test_a_file_over_the_limit_is_shown_without_colors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(highlight, "HIGHLIGHT_MAX_BYTES", 50)
        result, html = convert(tmp_path, "big.yaml", "key: value\n" * 20)
        assert result.ok
        assert 'class="plain-text">key: value' in html and "highlighted" not in html
        assert "色は付けずに表示しています" in html
        assert "code.highlighted" not in html   # 色のCSSも、入らない

    def test_without_pygments_the_file_is_shown_plain_with_an_info(self, tmp_path, without_pygments):
        result, html = convert(tmp_path, "a.json", '{"a": 1}\n')
        assert result.ok and not result.warnings
        assert '<pre class="plain-text">{&quot;a&quot;: 1}' in html or '<pre class="plain-text">{"a": 1}' in html
        assert "highlighted" not in html and "code.highlighted" not in html
        assert any("Pygments is not installed" in d.message for d in result.diagnostics)

    def test_a_non_utf8_file_is_still_an_error(self, tmp_path):
        result, _ = convert(tmp_path, "a.yaml", "日本語".encode("cp932"))
        assert not result.ok and "not UTF-8" in result.errors[0].message


class TestFencedCode:
    def test_a_known_language_fence_is_highlighted(self, tmp_path):
        result, html = convert(tmp_path, "d.md", "# T\n\n```python\nprint(1)  # c\n```\n")
        assert result.ok
        assert '<code class="language-python highlighted">' in html and '<span class="nb">print</span>' in html
        assert "code.highlighted .k {" in html

    def test_aliases_and_upper_case_are_understood(self, tmp_path):
        _, html = convert(tmp_path, "d.md", "```YML\na: 1\n```\n\n```py\nx = 1\n```\n")
        assert html.count(" highlighted\">") == 2

    def test_an_unknown_language_and_a_plain_fence_stay_plain(self, tmp_path):
        _, html = convert(tmp_path, "d.md", "```nosuch\n<b>x</b>\n```\n\n```\nplain\n```\n")
        assert '<code class="language-nosuch">&lt;b&gt;x&lt;/b&gt;' in html and "highlighted" not in html
        assert "<code>plain" in html

    def test_a_page_without_highlighted_code_has_no_highlight_css(self, tmp_path):
        _, html = convert(tmp_path, "d.md", "# T\n\ntext\n")
        assert "code.highlighted" not in html

    def test_without_pygments_a_fence_is_plain_code(self, tmp_path, without_pygments):
        _, html = convert(tmp_path, "d.md", "```python\nprint(1)\n```\n")
        assert '<code class="language-python">print(1)' in html and "highlighted" not in html

    def test_diagram_fences_are_not_highlighted_as_code(self, tmp_path):
        """図のフェンスは、図にする（コードとして色を付けない）。無効にしたときだけ、素のコード表示。"""
        _, html = convert(tmp_path, "d.md", '```bytefield\n(draw-box "A" {:span 8})\n```\n')
        assert "language-bytefield" in html and "highlighted" not in html or "<img" in html
