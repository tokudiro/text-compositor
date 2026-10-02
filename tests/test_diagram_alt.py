"""図の代替テキスト（フェンスの`alt="..."`、#398）のテスト。

ブラウザの要らない`svg`フェンスで、HTML・PDF（Typstのコード）の両方を確かめる。"""
import re

import pytest

from text_compositor.api import render_html
from text_compositor.renderer import TypstRenderer

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


@pytest.fixture
def renderer(tmp_path):
    return TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off")


class TestParse:
    @pytest.mark.parametrize("attrs,expected", [
        ('{alt="ログインの流れ"}', "ログインの流れ"),
        ("{alt='single quoted'}", "single quoted"),
        ("{alt=word}", "word"),
        ('{alt=""}', ""),
        ('{width=50% alt="a b c" trim=true}', "a b c"),
        ('{width=50%}', None),
        ('', None),
        (None, None),
    ])
    def test_the_alt_value_is_read(self, renderer, attrs, expected):
        assert renderer._parse_alt_attr(attrs) == expected

    def test_a_word_alt_inside_the_value_is_not_taken_for_another_attribute(self, renderer):
        attrs = '{alt="width=3 and height=4 trim=true" width=50%}'
        assert renderer._parse_alt_attr(attrs) == "width=3 and height=4 trim=true"
        assert renderer._parse_size_attrs(attrs) == ("50%", None)
        assert renderer._parse_trim_attr(attrs) is None

    def test_sizes_and_trim_still_work_next_to_alt(self, renderer):
        attrs = '{alt="x" width=40% height=8cm trim=false}'
        assert renderer._parse_size_attrs(attrs) == ("40%", "8cm")
        assert renderer._parse_trim_attr(attrs) is False


class TestHtml:
    def convert(self, tmp_path, attrs):
        md = tmp_path / "doc.md"
        md.write_text(f"# T\n\n```svg {attrs}\n{SVG}\n```\n", encoding="utf-8")
        result = render_html(str(md), plugins=PLAIN)
        assert result.ok, result.diagnostics
        return open(result.html_path, encoding="utf-8").read()

    def test_the_alt_becomes_the_img_alt(self, tmp_path):
        html = self.convert(tmp_path, '{alt="ログインの流れ"}')
        assert 'alt="ログインの流れ"' in html and 'alt="svg diagram"' not in html

    def test_without_alt_the_kind_is_kept(self, tmp_path):
        assert 'alt="svg diagram"' in self.convert(tmp_path, "")

    def test_an_empty_alt_marks_the_figure_as_decorative(self, tmp_path):
        assert 'alt=""' in self.convert(tmp_path, '{alt=""}')

    def test_the_alt_is_escaped(self, tmp_path):
        html = self.convert(tmp_path, "{alt='a <b> & \"q\"'}")
        assert 'alt="a &lt;b&gt; &amp; &quot;q&quot;"' in html and "<b>" not in html

    def test_alt_works_in_a_layout_block(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text(f"# T\n\n::: layout-right\n本文。\n\n```svg {{alt=\"横並びの図\"}}\n{SVG}\n```\n\n:::\n", encoding="utf-8")
        result = render_html(str(md), plugins=PLAIN)
        assert result.ok, result.diagnostics
        assert 'alt="横並びの図"' in open(result.html_path, encoding="utf-8").read()


class TestPdfCode:
    def test_the_alt_is_set_on_the_image_with_fit_image(self, renderer):
        code = renderer._render_diagram_fence("svg", SVG, alt="流れ図")
        assert re.search(r'#align\(center\)\[#\{ set image\(alt: "流れ図"\); fit-image\("[^"]+"\) \}\]', code)

    def test_the_alt_is_set_on_the_image_with_an_explicit_size(self, renderer):
        code = renderer._render_diagram_fence("svg", SVG, width="50%", alt="x")
        assert re.search(r'set image\(alt: "x"\); image\("[^"]+", width: 50%\)', code)

    def test_quotes_and_backslashes_are_escaped_for_typst(self, renderer):
        code = renderer._render_diagram_fence("svg", SVG, alt='a "q" \\ b')
        assert 'alt: "a \\"q\\" \\\\ b"' in code

    def test_an_empty_alt_is_passed_as_an_empty_string(self, renderer):
        assert 'set image(alt: "")' in renderer._render_diagram_fence("svg", SVG, alt="")

    def test_without_alt_the_output_is_unchanged(self, renderer):
        code = renderer._render_diagram_fence("svg", SVG)
        assert "alt" not in code and re.search(r'#align\(center\)\[#fit-image\("[^"]+"\)\]', code)

    def test_the_alt_does_not_leak_into_the_next_diagram(self, renderer):
        renderer._render_diagram_fence("svg", SVG, alt="first")
        assert renderer._pending_alt is None
        assert "alt" not in renderer._render_diagram_fence("svg", SVG)

    def test_the_alt_is_cleared_even_when_rendering_fails(self, renderer, monkeypatch):
        monkeypatch.setattr(TypstRenderer, "_render_svg", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            renderer._render_diagram_fence("svg", SVG, alt="x")
        assert renderer._pending_alt is None
