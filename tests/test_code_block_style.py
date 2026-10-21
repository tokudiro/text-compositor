"""PDFのコードブロックの装飾（背景・等幅フォント。#511）のテスト。"""
import re
import sys
from pathlib import Path

import pytest
import typst

import text_compositor.build as build_mod
from text_compositor import log
from text_compositor.code_block_style import BACKGROUND, CODE_FONTS, CodeBlockStyle, resolve_code_block, wrap_code_block
from text_compositor.renderer import TypstRenderer

ROOT = Path(__file__).resolve().parent.parent
FENCE = "```python\nprint(1)\n```\n"
DOT = "```dot\ndigraph G { a -> b; }\n```\n"


def render(markdown, **flags):
    return TypstRenderer(line_mapping="off", **flags).render(markdown)


def test_wrap_code_block_adds_the_background_and_the_mono_font():
    wrapped = wrap_code_block('#raw("x", block: true)')
    assert f'fill: rgb("{BACKGROUND}")' in wrapped
    assert '#show raw: set text(font: ("Noto Sans Mono CJK JP", "DejaVu Sans Mono"))' in wrapped
    assert '#raw("x", block: true)' in wrapped
    assert "stroke" not in wrapped   # 枠線は、既定では付けない（HTML出力と同じ）


def test_a_code_fence_is_wrapped():
    typst = render(FENCE)
    assert "fill: rgb(" in typst
    assert '#raw("print(1)\\n", lang: "python", block: true)' in typst


def test_plain_text_and_data_files_are_wrapped_too():
    """`.yaml`・`.txt`などのファイル（章として読み込むもの）も、同じ`_render_raw_text`を通る。"""
    assert "fill: rgb(" in TypstRenderer(line_mapping="off")._render_raw_text("a: 1\n", "yaml")


def test_graphviz_is_not_wrapped_when_the_plugin_is_enabled():
    """dot/graphvizは、テンプレートのshowルールが図に置き換える。包むと、図が、枠の中に入ってしまう。"""
    typst = render(DOT, graphviz_enabled=True)
    assert "fill: rgb(" not in typst
    assert '#raw("digraph G { a -> b; }\\n", lang: "dot", block: true)' in typst


def test_graphviz_is_wrapped_as_code_when_the_plugin_is_disabled():
    assert "fill: rgb(" in render(DOT, graphviz_enabled=False)


def test_decorate_false_gives_the_bare_raw():
    """ChordProの譜面（tab）は、歌詞の一部のため、装飾しない。"""
    bare = TypstRenderer(line_mapping="off")._render_raw_text("x", decorate=False)
    assert bare == '#raw("x", block: true)\n\n'


def test_the_mono_fonts_match_the_templates_code_font():
    """`code_block_style.py`の`CODE_FONTS`と、テンプレートの`code-font`（インラインのコード用）は、同じ値。"""
    common = (ROOT / "text_compositor" / "templates" / "_common.typ").read_text(encoding="utf-8")
    declared = re.search(r"#let code-font = \(([^)]*)\)", common).group(1)
    assert tuple(re.findall(r'"([^"]+)"', declared)) == CODE_FONTS


@pytest.mark.parametrize("name", ["template.typ", "slide.typ", "paper.typ"])
def test_the_bundled_templates_no_longer_box_code_blocks_themselves(name):
    """テンプレートのshowルールは、重ねがけされる（外側と内側が、両方効く）。背景を、テンプレートと、Pythonで、二重に付けない。"""
    text = (ROOT / "text_compositor" / "templates" / name).read_text(encoding="utf-8")
    assert "raw.where(block: true)" not in text
    # インラインのコードの等幅フォントだけ。コードブロックは、Python側が付ける（`code_block: false`のとき、対象にしない）
    assert "show raw.where(block: false): set text(font: code-font)" in text


RAW = '#raw("x", block: true)'


class TestWrapWithStyle:
    """章ごとの設定（`code_block`。#511）が、包むTypstのコードに、反映される。"""

    def test_the_default_style_has_no_border_and_the_default_size(self):
        wrapped = wrap_code_block(RAW, CodeBlockStyle())
        assert "stroke" not in wrapped and "size:" not in wrapped

    def test_disabled_gives_the_bare_raw(self):
        assert wrap_code_block(RAW, CodeBlockStyle(enabled=False)) == RAW + "\n\n"

    def test_a_border_adds_a_stroke_with_the_width_and_color(self):
        style = resolve_code_block({"border": {"color": "#112233", "width": "2pt"}})
        assert 'stroke: 2pt + rgb("#112233")' in wrap_code_block(RAW, style)

    def test_border_true_uses_the_default_color_and_width(self):
        assert 'stroke: 0.75pt + rgb("#d1d9e0")' in wrap_code_block(RAW, resolve_code_block({"border": {}}))

    def test_a_typst_color_name_is_passed_as_it_is(self):
        assert "stroke: 1pt + red," in wrap_code_block(RAW, resolve_code_block({"border": {"color": "red", "width": "1pt"}})) + ","

    def test_font_size_is_set_on_the_text(self):
        wrapped = wrap_code_block(RAW, resolve_code_block({"font_size": "8pt"}))
        assert '#show raw: set text(font: ("Noto Sans Mono CJK JP", "DejaVu Sans Mono"), size: 8pt)' in wrapped

    @pytest.mark.parametrize("spec", [
        {}, {"enabled": False}, {"font_size": "7.5pt"}, {"border": {}}, {"border": {"color": "gray", "width": "1pt"}},
        {"border": {"color": "#abc"}, "font_size": "9pt"}, {"border": {"color": "#AABBCCDD", "width": "0.5pt"}}])
    def test_every_combination_is_valid_typst(self, spec):
        source = '#set page(width: 200pt, height: 100pt)\n' + wrap_code_block(RAW, resolve_code_block(spec))
        assert typst.compile(source.encode(), format="pdf").startswith(b"%PDF")

    def test_the_renderer_uses_the_style_of_the_chapter(self):
        renderer = TypstRenderer(line_mapping="off")
        renderer.code_block_style = resolve_code_block({"border": {}, "font_size": "8pt"})
        typst_code = renderer.render(FENCE)
        assert "stroke: 0.75pt" in typst_code and "size: 8pt" in typst_code
        renderer.code_block_style = CodeBlockStyle(enabled=False)
        disabled = renderer.render(FENCE)
        assert "#show raw" not in disabled and '#raw("print(1)\\n", lang: "python", block: true)' in disabled

    def test_graphviz_stays_unwrapped_even_with_a_border(self):
        renderer = TypstRenderer(line_mapping="off", graphviz_enabled=True)
        renderer.code_block_style = resolve_code_block({"border": {}})
        assert "stroke" not in renderer.render(DOT)


class TestPerChapterInTheBuild:
    """`document:`・section・章の指定が、章ごとの出力に反映される（組み立てたTypstのコードで確かめる）。"""

    def test_each_chapter_gets_its_own_style(self, tmp_path, monkeypatch):
        import text_compositor.project as project_mod
        captured = {}
        monkeypatch.setattr(project_mod, "_compile_and_cleanup", lambda typst_code, *a, **k: captured.setdefault("code", typst_code))
        from text_compositor.deps import ensure_fonts
        try:
            ensure_fonts()
        except SystemExit:
            pytest.skip("fonts are not available")
        for name in ("a", "b", "c", "d"):
            (tmp_path / f"{name}.md").write_text(f"# {name.upper()}\n\n```python\nprint('{name}')\n```\n", encoding="utf-8")
        (tmp_path / "text-compositor.config.yaml").write_text(
            'document:\n  title: "t"\n  cover: "none"\n  toc: false\n  code_block: {font_size: 8pt}\n'
            'inputs: {dir: "."}\noutput: {filename: "out.pdf", dir: "."}\n'
            'chapters:\n'
            '  - "a.md"\n'
            '  - {file: "b.md", code_block: {border: true}}\n'
            '  - {file: "c.md", code_block: false}\n'
            '  - section: "S"\n'
            '    code_block: {border: {color: red, width: 2pt}}\n'
            '    chapters: ["d.md"]\n', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["text-compositor", "--config", str(tmp_path / "text-compositor.config.yaml"), "-q"])
        build_mod.build()
        code = captured["code"]

        lines = code.split("\n")

        def wrapper_before(name):
            """その章のコードの`#raw(`の行の、直前にある、包み（`#show raw`で始まる2行）。包まれていなければ、空。"""
            index = next(i for i, line in enumerate(lines) if line.startswith("#raw(") and f"print('{name}')" in line)
            before = lines[index - 2:index]
            return "\n".join(before) if all(line.startswith("#show raw") for line in before) else ""

        a, b, c, d = (wrapper_before(n) for n in "abcd")
        assert "size: 8pt" in a and "stroke" not in a                       # documentだけ
        assert "size: 8pt" in b and "stroke: 0.75pt + rgb(\"#d1d9e0\")" in b   # 章で、枠線を足す
        assert c == ""                                                      # 章で、無効にする（包まない）
        assert "size: 8pt" in d and "stroke: 2pt + red" in d                # sectionの枠線（documentの大きさは、そのまま）


@pytest.fixture(autouse=True)
def _restore_verbosity():
    yield
    log.set_verbosity(False, False)


def test_a_custom_template_also_gets_the_mono_font(tmp_path, monkeypatch):
    """独自テンプレート（テンプレートに、コードの指定がない）でも、コードブロックが、等幅フォントで出る（#511）。"""
    from text_compositor.deps import ensure_fonts
    try:
        ensure_fonts()
    except SystemExit:
        pytest.skip("fonts are not available")
    (tmp_path / "adapter.typ").write_text(
        '#import "_common.typ": fit-image, render-graph, callout, render-header, render-footer, render-background, meta-date\n'
        '#let conf(..args, doc) = doc\n', encoding="utf-8")
    (tmp_path / "a.md").write_text("# Custom\n\n" + FENCE, encoding="utf-8")
    (tmp_path / "text-compositor.config.yaml").write_text(
        'document: {title: "custom", cover: "none", toc: false}\n'
        'template: {path: "adapter.typ"}\n'
        'inputs: {dir: "."}\n'
        'output: {filename: "out.pdf", dir: "."}\n'
        'chapters: ["a.md"]\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["text-compositor", "--config", str(tmp_path / "text-compositor.config.yaml"), "-q"])
    build_mod.build()
    pdf = (tmp_path / "out.pdf").read_bytes()
    assert b"NotoSansMonoCJKjp" in pdf
