"""PDFのコードブロックの装飾（背景・等幅フォント。#511）のテスト。"""
import re
import sys
from pathlib import Path

import pytest

import text_compositor.build as build_mod
from text_compositor import log
from text_compositor.code_block_style import BACKGROUND, CODE_FONTS, wrap_code_block
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
    assert "show raw: set text(font: code-font)" in text   # インラインのコードの等幅フォントだけ


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
