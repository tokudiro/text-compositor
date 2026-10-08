"""ChordProのTypst出力（PDF側。#440）のテスト。生成したコードを調べ、Typstで実際にコンパイルできることも確かめる。"""
import pytest

from text_compositor.renderer import TypstRenderer

SONG = "{title: 蛍の光}\n{soc: サビ}\n[C]あおい[G]そら\n{eoc}\nplain\n{c: Intro}\n{cb: Fine}\n{sot}\ne|--0--|\n{eot}\n"


def renderer(tmp_path, **kwargs):
    return TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off", **kwargs)


def test_a_chord_and_its_lyric_are_stacked_in_one_box(tmp_path):
    code = renderer(tmp_path)._render_chordpro_typst("[G]Amazing [C]grace")
    assert code.count("#box(stack(dir: ttb") == 2
    assert '"G"' in code and '"Amazing "' in code and '"C"' in code and '"grace"' in code


def test_text_is_embedded_as_string_literals_so_markup_characters_are_inert(tmp_path):
    code = renderer(tmp_path)._render_chordpro_typst('[C]#set page(width: 1pt) *x* "q" \\ end')
    assert '"#set page(width: 1pt) *x* \\"q\\" \\\\ end"' in code


def test_the_whole_song_compiles(tmp_path):
    typst = pytest.importorskip("typst")
    code = renderer(tmp_path)._render_chordpro_typst(SONG + "[C]#set page(width: 1pt) *x* [G]_y_\n")
    pdf = typst.compile(code.encode("utf-8"))
    assert pdf[:5] == b"%PDF-"


def test_a_chordpro_fence_in_markdown_becomes_boxes(tmp_path):
    code = renderer(tmp_path).render("# T\n\n```chordpro\n[C]x\n```\n")
    assert "#box(stack(dir: ttb" in code and "#raw(" not in code


def test_a_chordpro_file_chapter_becomes_boxes(tmp_path):
    code = renderer(tmp_path).render_chapter("[C]x\n", filepath=str(tmp_path / "s.cho"))
    assert "#box(stack(dir: ttb" in code


def test_the_plugin_off_shows_the_source_as_code(tmp_path):
    r = renderer(tmp_path, chordpro_enabled=False)
    assert "#box(stack" not in r.render("# T\n\n```chordpro\n[C]x\n```\n")
    assert r.render_chapter("[C]x\n", filepath=str(tmp_path / "s.pro")).startswith('#raw("[C]x')


def test_a_warning_points_at_the_line_in_the_document(tmp_path):
    seen = []
    r = renderer(tmp_path)
    r._warn_here = lambda message, line=None: seen.append((line, message))
    r.render("# T\n\n```chordpro\n[C]x\n{define: C base-fret 1}\n```\n")
    assert [(line, "define" in m) for line, m in seen] == [(5, True)]


def test_the_key_header_and_the_transposed_chords_are_in_the_typst_code(tmp_path):
    typst = pytest.importorskip("typst")
    code = renderer(tmp_path)._render_chordpro_typst("{key: B}\n{transpose: 1}\n{capo: 2}\n[B]a[E]b\n")
    assert '"Key: B (play in C) / Capo: 2"' in code
    assert '"C"' in code and '"F"' in code and '"B"' not in code
    assert typst.compile(code.encode("utf-8"))[:5] == b"%PDF-"
