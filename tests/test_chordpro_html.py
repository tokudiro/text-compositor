"""ChordProのHTML出力（` ```chordpro `フェンスと、`.cho`・`.chordpro`・`.pro`の単体ファイル。#440）のテスト。外部ツールは使わない。"""
import pytest

from tests.test_html_output import PLAIN, body, convert

SONG = "{title: Amazing Grace}\n{subtitle: Traditional}\n{soc: Chorus}\n[G]Amazing [C]grace\n{eoc}\nplain line\n"


def plugins(**extra):
    return {**PLAIN, **extra}


class TestFence:
    def test_chords_are_stacked_over_their_lyric_segments(self, tmp_path):
        result, html = convert(tmp_path, "# T\n\n```chordpro\n[G]Amazing [C]grace\n```\n")
        assert result.ok and not result.warnings
        assert ('<span class="cp-seg"><span class="cp-chord">G</span><span class="cp-lyric">Amazing </span></span>'
                '<span class="cp-seg"><span class="cp-chord">C</span><span class="cp-lyric">grace</span></span>') in body(html)

    def test_the_title_in_a_fence_is_not_a_page_heading(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n```chordpro\n" + SONG + "```\n")
        assert '<div class="cp-title">Amazing Grace</div>' in body(html) and "<h1 class=\"cp-title\"" not in body(html)
        assert '<div class="cp-subtitle">Traditional</div>' in body(html)

    def test_a_section_is_wrapped_with_its_label(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n```chordpro\n" + SONG + "```\n")
        assert '<div class="cp-section cp-chorus"><div class="cp-label">Chorus</div>' in body(html)

    def test_a_line_without_chords_has_no_chord_row(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n```chordpro\n" + SONG + "```\n")
        assert '<div class="cp-line cp-plain">plain line</div>' in body(html)

    def test_text_is_escaped(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n```chordpro\n[C]<b>x</b> & y\n```\n")
        assert "<b>x</b>" not in body(html) and "&lt;b&gt;x&lt;/b&gt; &amp; y" in body(html)

    def test_japanese_lyrics(self, tmp_path):
        _, html = convert(tmp_path, "# T\n\n```chordpro\n[C]あおい[G]そら\n```\n")
        assert '<span class="cp-lyric">あおい</span>' in body(html)

    def test_an_unsupported_directive_warns_at_the_line_in_the_document(self, tmp_path):
        result, _ = convert(tmp_path, "# T\n\n```chordpro\n[C]x\n{transpose: 2}\n```\n")
        assert result.ok
        assert [(d.line, "transpose" in d.message) for d in result.warnings] == [(5, True)]

    def test_the_plugin_off_shows_the_source_as_code(self, tmp_path):
        result, html = convert(tmp_path, "# T\n\n```chordpro\n[C]x\n```\n", plugins=plugins(chordpro=False))
        assert result.ok and "language-chordpro" in html and 'class="cp-seg"' not in body(html)

    def test_chordpro_is_an_allowed_plugins_key(self):
        from text_compositor.config import _ALLOWED_PLUGINS_KEYS
        assert "chordpro" in _ALLOWED_PLUGINS_KEYS


class TestFile:
    @pytest.mark.parametrize("name", ["song.cho", "song.chordpro", "song.pro", "SONG.CHO"])
    def test_a_chordpro_file_is_a_page(self, tmp_path, name):
        result, html = convert(tmp_path, SONG, name=name)
        assert result.ok and not result.warnings
        assert '<h1 class="cp-title">Amazing Grace</h1>' in body(html)
        assert '<span class="cp-chord">G</span>' in body(html)

    def test_the_title_becomes_the_page_title(self, tmp_path):
        _, html = convert(tmp_path, SONG, name="song.cho")
        assert "<title>Amazing Grace</title>" in html

    def test_without_a_title_the_file_name_is_the_page_title(self, tmp_path):
        _, html = convert(tmp_path, "[C]x\n", name="untitled.cho")
        assert "<title>untitled</title>" in html

    def test_a_warning_points_at_the_line_of_the_file(self, tmp_path):
        result, _ = convert(tmp_path, "[C]x\n{define: C base-fret 1}\n", name="s.cho")
        assert [d.line for d in result.warnings] == [2]

    def test_the_plugin_off_shows_the_file_as_code(self, tmp_path):
        result, html = convert(tmp_path, "[C]x\n", name="s.cho", plugins=plugins(chordpro=False))
        assert result.ok and "language-chordpro" in html
