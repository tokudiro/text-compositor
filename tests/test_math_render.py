"""数式描画（LaTeX記法・mitex・PDF・HTML。#183）のテスト。"""
import os
import re
import tempfile
from pathlib import Path

import pytest

from text_compositor import math_render
from text_compositor.api import Session
from text_compositor.math_render import MITEX_VERSION, MathRenderError, cache_version, render_svg
from text_compositor.renderer import TypstRenderer

ROOT = Path(__file__).resolve().parent.parent


def _read(relative):
    with open(ROOT / relative, encoding="utf-8") as f:
        return f.read()


class TestPinnedVersion:
    def test_the_mitex_version_is_the_same_in_every_place_it_is_pinned(self):
        """PDFのテンプレート・ZIPに同梱するパッケージ・HTML出力の3つの版が一致すること。"""
        common = _read("text_compositor/templates/_common.typ")
        m_common = re.search(r"@preview/mitex:([\d.]+)", common)
        assert m_common, "mitex not found in _common.typ"
        template_ver = m_common.group(1)

        build_dist = _read("viewer/scripts/build-dist.js")
        m_dist = re.search(r"name: 'mitex', version: '([\d.]+)'", build_dist)
        assert m_dist, "mitex not found in build-dist.js"
        bundled_ver = m_dist.group(1)

        assert math_render.MITEX_VERSION == template_ver == bundled_ver

    def test_the_cache_version_names_mitex_typst_and_mode(self):
        v_inline = cache_version(display_mode=False)
        v_block = cache_version(display_mode=True)
        assert "mitex" in v_inline and "inline" in v_inline
        assert "mitex" in v_block and "block" in v_block
        assert v_inline != v_block


class TestRenderSvg:
    def test_renders_inline_math_svg(self):
        svg = render_svg(r"x^2 + y^2 = z^2", display_mode=False)
        assert "<svg" in svg and "</svg>" in svg
        # 透明背景（fill=none）のため白背景パスは含まれない
        assert 'fill="#ffffff"' not in svg

    def test_renders_block_math_svg(self):
        svg = render_svg(r"\sum_{i=1}^n i = \frac{n(n+1)}{2}", display_mode=True)
        assert "<svg" in svg and "</svg>" in svg

    def test_renders_japanese_inside_text(self):
        svg = render_svg(r"x_{\text{合計}} = 100", display_mode=False)
        assert "<svg" in svg

    def test_syntax_error_raises_math_render_error(self):
        with pytest.raises(MathRenderError) as exc_info:
            render_svg(r"\unknowncommandxyz{123}", display_mode=False)
        assert "unknown command" in str(exc_info.value) or "error" in str(exc_info.value).lower()


class TestTypstPdfOutput:
    def test_inline_math_becomes_mi(self):
        r = TypstRenderer()
        output = r.render("This is $x^2 + y^2 = z^2$ and $$\\alpha$$.", "test.md")
        assert '#mi("x^2 + y^2 = z^2")' in output
        assert r'#mi("\\alpha")' in output

    def test_block_math_becomes_mimath(self):
        r = TypstRenderer()
        output = r.render("$$\n\\sum_{i=1}^n x_i\n$$", "test.md")
        assert r'#mimath("\\sum_{i=1}^n x_i")' in output

    def test_math_fence_becomes_mimath(self):
        r = TypstRenderer()
        output = r.render("```math\n\\int_0^1 f(x) dx\n```", "test.md")
        assert r'#mimath("\\int_0^1 f(x) dx")' in output

    def test_currency_and_escaped_dollar_are_not_math(self):
        r = TypstRenderer()
        output = r.render("Cost is $100 and $200, or \\$300. Spaced $ a + b $ is plain.", "test.md")
        assert "#mi(" not in output
        assert "\\$100" in output and "\\$200" in output
        assert "\\$300" in output


class TestHtmlOutput:
    def test_inline_and_block_math_in_html(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("""# Math Test

Inline math $a^2 + b^2 = c^2$ in text.
Price is $100 and $200.

$$
\\frac{x}{y} = z
$$

```math
\\sqrt{x}
```
""", encoding="utf-8")
        session = Session()
        res = session.render_html(str(md))
        assert res.ok
        assert not res.errors
        assert not res.warnings

        html = open(res.html_path, encoding="utf-8").read()
        assert 'class="math-inline"' in html
        assert 'class="math-block"' in html
        assert "$100" in html and "$200" in html
        # 生成されたSVGファイルが存在すること
        m = re.findall(r'<img [^>]*src="([^"]+)"', html)
        assert len(m) >= 3
        html_dir = Path(res.html_path).parent
        for src in m:
            svg_file = html_dir / src
            assert svg_file.exists()
            assert svg_file.read_text(encoding="utf-8").startswith("<svg")

    def test_invalid_math_produces_diagnostic_error(self, tmp_path):
        md = tmp_path / "bad.md"
        md.write_text("Line 1\n\n$\\invalidcmd{x}$\n", encoding="utf-8")
        session = Session()
        res = session.render_html(str(md))
        assert not res.ok
        assert len(res.errors) == 1
        assert res.errors[0].line == 3
        assert "Math diagram failed to render" in res.errors[0].message
