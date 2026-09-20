"""CeTZ・Fletcher（Typstのパッケージ。cetz_render.py・図のフェンスの変換、#236）のテスト。"""
import os
import re

import pytest

from text_compositor import cetz_render, diagnostics
from text_compositor.api import build_markdown, render_html
from text_compositor.cetz_render import FigureCodeError, FigureRenderError, check_code, render_svg
from text_compositor.renderer import TypstRenderer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}

CETZ = 'circle((0, 0), radius: 1)\nline((0, 0), (2, 1))\ncontent((1, 0.5), [日本語])'
FLETCHER = 'node((0, 0), [開始]), edge("->"), node((1, 0), [終了])'


def _read(relative):
    with open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as f:
        return f.read()


def test_the_versions_are_the_same_in_the_source_and_the_bundle():
    """生成コードが読み込む版と、ZIPに同梱するパッケージの版が、ずれると、配布物で、取得（ネットワーク）が起きる。"""
    script = _read("viewer/scripts/build-dist.js")
    bundled = set(re.findall(r"name: '([a-z0-9-]+)', version: '([\d.]+)'", script))
    assert ("cetz", cetz_render.CETZ_VERSION) in bundled
    assert ("fletcher", cetz_render.FLETCHER_VERSION) in bundled


class TestCheckCode:
    @pytest.mark.parametrize("code", [
        'import "x.typ"',
        '#import "x.typ"',
        'circle((0, 0))\ninclude "a.typ"',
        'content((0, 0), [#f({ import "/s.typ" })])',
        'let x = {\n  import "a"\n}',
        'content((0, 0), [#let x = { import "a" }])',
        'f(a, (import "a"))',
        '/* c */ import "x"',
        '// c\nimport "x"',
        'content((0, 0), [a #include "x"])',
    ])
    def test_import_and_include_are_rejected(self, code):
        with pytest.raises(FigureCodeError):
            check_code(code)

    @pytest.mark.parametrize("code", [
        'content((0, 0), [import])',
        'content((0, 0), "import and include")',
        '// import x\ncircle((0, 0))',
        'content((0, 0), [Data (import) and include])',
        'my-import(1)',
        'line((0, 0), (1, 1)) /* import */',
        'content((0, 0), `import`)',
        'content((0, 0), [#strong[import]])',
        'content((0, 0), "a\\"import")',
    ])
    def test_the_same_words_in_a_string_a_comment_or_text_are_fine(self, code):
        check_code(code)

    def test_the_error_carries_the_line_in_the_code(self):
        with pytest.raises(FigureCodeError) as e:
            check_code('circle((0, 0))\n\nline((0, 0), (1, 1))\nimport "x"')
        assert e.value.code_line == 4


class TestRender:
    def test_cetz_becomes_an_svg_without_a_page_background(self):
        svg = render_svg("cetz", CETZ)
        assert svg.startswith("<svg") and 'fill="#ffffff"' not in svg

    def test_fletcher_becomes_an_svg(self):
        assert render_svg("fletcher", FLETCHER).startswith("<svg")

    def test_the_compiler_is_reused_and_a_later_figure_is_not_a_leftover(self):
        first = render_svg("cetz", "circle((0, 0))")
        assert render_svg("cetz", "circle((0, 0))\nline((0, 0), (3, 3))") != first
        assert render_svg("cetz", "circle((0, 0))") == first

    def test_the_cetz_scope_has_the_drawing_functions_and_the_cetz_module(self):
        assert render_svg("cetz", "let f = cetz.vector.add((1, 0, 0), (0, 1, 0))\nline((0, 0), f)").startswith("<svg")

    def test_a_typst_error_is_reported_with_its_message(self):
        with pytest.raises(FigureRenderError) as e:
            render_svg("fletcher", 'node((0, 0), [A]), nope(1)')
        assert "unknown variable: nope" in str(e.value)
        assert render_svg("cetz", "circle((0, 0))").startswith("<svg")   # エラーの後でも、同じCompilerで、次の図が描ける

    @pytest.mark.parametrize("kind, code", [
        ("cetz", 'content((0, 0), read("/etc/passwd"))'),
        ("cetz", 'content((0, 0), std.read("x"))'),
        ("cetz", 'content((0, 0), eval("1"))'),
        ("cetz", 'content((0, 0), str(json("x.json")))'),
        ("cetz", 'let f = read\ncontent((0, 0), f("x"))'),
        ("cetz", 'pdf.embed("x")'),
        ("fletcher", 'node((0, 0), read("x"))'),
        ("fletcher", 'node((0, 0), std.plugin("x"))'),
    ])
    def test_functions_that_read_files_are_denied_with_a_clear_message(self, kind, code):
        with pytest.raises(FigureRenderError) as e:
            render_svg(kind, code)
        assert "is not available" in str(e.value) or "no key" in str(e.value) or "dictionary" in str(e.value), str(e.value)

    def test_import_is_rejected_before_typst_runs(self):
        with pytest.raises(FigureCodeError):
            render_svg("cetz", 'import "/secret.typ"')

    def test_the_code_is_passed_as_data_so_quotes_and_typst_syntax_are_harmless(self):
        assert render_svg("cetz", 'content((0, 0), "#panic(\\"x\\") $ \\\\ ")').startswith("<svg")


def _html(tmp_path, text, name="doc.md", plugins=PLAIN):
    md = tmp_path / name
    md.write_text(text, encoding="utf-8")
    result = render_html(str(md), plugins=plugins)
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


class TestHtmlOutput:
    @pytest.mark.parametrize("lang, code", [("cetz", CETZ), ("fletcher", FLETCHER)])
    def test_a_fence_becomes_a_cached_svg_img(self, tmp_path, lang, code):
        result, html = _html(tmp_path, f'a\n\n```{lang} {{width=300pt}}\n{code}\n```\n')
        assert result.ok and not result.warnings
        m = re.search(rf'<img src="([^"]+)" alt="{lang} diagram" style="width:300pt">', html)
        assert m, html
        assert (tmp_path / ".text-compositor" / m.group(1)).read_text(encoding="utf-8").startswith("<svg")

    def test_a_typst_error_is_reported_at_the_line_of_the_fence(self, tmp_path):
        result, _ = _html(tmp_path, 'a\n\n```fletcher\nnode((0, 0), [A]\n```\n')
        assert not result.ok
        error = result.errors[0]
        assert error.message == "Fletcher diagram failed to render"
        assert error.line == 3 and "unclosed delimiter" in error.detail

    def test_import_is_reported_at_the_line_in_the_manuscript(self, tmp_path):
        # フェンスは3行目。`import`は、コードの3行目で、原稿の6行目
        result, _ = _html(tmp_path, 'a\n\n```cetz\ncircle((0, 0))\nline((0, 0), (1, 1))\nimport "/secret.typ"\n```\n')
        assert not result.ok
        assert result.errors[0].line == 6 and "'import' cannot be used" in result.errors[0].detail

    def test_a_denied_function_is_an_error_not_a_file_read(self, tmp_path):
        (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
        result, html = _html(tmp_path, '```cetz\ncontent((0, 0), read("/secret.txt"))\n```\n')
        assert not result.ok and "is not available" in result.errors[0].detail
        assert "TOP-SECRET" not in html

    @pytest.mark.parametrize("lang", ["cetz", "fletcher"])
    def test_the_plugin_setting_falls_back_to_a_code_block_without_a_warning(self, tmp_path, lang):
        result, html = _html(tmp_path, f'```{lang}\nnode((0, 0), [x])\n```\n', plugins={**PLAIN, lang: False})
        assert result.ok and f'class="language-{lang}"' in html and not result.warnings

    def test_one_plugin_setting_does_not_disable_the_other(self, tmp_path):
        result, html = _html(tmp_path, f'```cetz\n{CETZ}\n```\n\n```fletcher\n{FLETCHER}\n```\n', plugins={**PLAIN, "cetz": False})
        assert result.ok and 'class="language-cetz"' in html and 'alt="fletcher diagram"' in html


class TestPdfCode:
    def _render(self, text, **kwargs):
        renderer = TypstRenderer(line_mapping="off", **kwargs)
        with diagnostics.collect():
            return renderer.render(text, filepath="doc.md")

    def test_the_fence_becomes_code_that_imports_the_pinned_package_and_evals_the_code_as_a_string(self):
        code = self._render(f'```cetz\n{CETZ}\n```\n')
        assert f'import "@preview/cetz:{cetz_render.CETZ_VERSION}"' in code
        assert 'eval("circle((0, 0), radius: 1)\\nline' in code and 'mode: "code"' in code
        assert "measure(fig)" in code   # 自動縮小

    def test_fletcher_wraps_the_code_in_diagram(self):
        code = self._render(f'```fletcher\n{FLETCHER}\n```\n')
        assert f'import "@preview/fletcher:{cetz_render.FLETCHER_VERSION}"' in code
        assert 'eval("diagram(\\n" + "node((0, 0)' in code

    def test_the_file_reading_functions_are_denied_in_the_generated_code(self):
        code = self._render('```cetz\ncircle((0, 0))\n```\n')
        assert '"read", "json"' in code and "std: denied" in code

    def test_a_size_attribute_scales_to_that_size(self):
        code = self._render('```cetz {width=5cm}\ncircle((0, 0))\n```\n')
        assert "(5cm)" in code and "scale(s * 100%" in code and "calc.min" in code   # 縦横比を保つ（引き伸ばさない）
        code = self._render('```fletcher {width=50%}\nnode((0, 0), [A])\n```\n')
        assert "50 * 1% * size.width" in code

    def test_it_is_generated_without_touching_the_templates_public_names(self):
        """カスタムテンプレートが、新しい公開名を、持たなくても、動く（生成コードが、パッケージを直接importする）。"""
        code = self._render('```cetz\ncircle((0, 0))\n```\n')
        assert "render-cetz" not in code and "render-fletcher" not in code

    def test_the_plugin_setting_leaves_a_plain_code_block(self):
        code = self._render('```cetz\ncircle((0, 0))\n```\n', cetz_enabled=False)
        assert "@preview/cetz" not in code and "circle" in code

    def test_import_stops_the_build_at_the_line_in_the_manuscript(self):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as sink:
            with pytest.raises(SystemExit):
                renderer.render('a\n\n```cetz\ncircle((0, 0))\nimport "x"\n```\n', filepath="doc.md")
        errors = sink.errors
        assert errors and errors[0].line == 5 and "'import' cannot be used" in errors[0].detail


def test_a_pdf_with_both_figures_is_built(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(f'# 図\n\n```cetz\n{CETZ}\n```\n\n```fletcher\n{FLETCHER}\n```\n\n'
                  '```cetz {width=5cm}\ncircle((0, 0))\n```\n\n```fletcher {width=50% height=3cm}\n'
                  'node((0, 0), [A]), edge("->"), node((1, 0), [B])\n```\n', encoding="utf-8")
    result = build_markdown(str(md), str(tmp_path / "doc.pdf"))
    assert result.ok, [(e.message, e.detail) for e in result.errors]
    assert (tmp_path / "doc.pdf").read_bytes().startswith(b"%PDF")


def test_a_denied_function_in_the_pdf_is_a_compile_error(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text('```cetz\ncontent((0, 0), read("/secret.txt"))\n```\n', encoding="utf-8")
    result = build_markdown(str(md), str(tmp_path / "doc.pdf"))
    assert not result.ok and "is not available" in result.errors[0].message
