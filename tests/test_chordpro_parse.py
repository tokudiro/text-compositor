"""ChordProの構文解析（chordpro_render.parse、#440）のテスト。ブラウザも外部ツールも使わない。"""
from text_compositor import chordpro_render as cp


def pairs(line):
    return [(s.chord, s.lyric) for s in line.segments]


class TestParseLine:
    def test_chords_split_the_lyric_into_pairs(self):
        assert pairs(cp.parse_line("[C]Hello [G]world")) == [("C", "Hello "), ("G", "world")]

    def test_a_lyric_before_the_first_chord_has_an_empty_chord(self):
        assert pairs(cp.parse_line("Oh [Am]my")) == [("", "Oh "), ("Am", "my")]

    def test_a_line_without_chords_is_one_segment(self):
        line = cp.parse_line("just words")
        assert pairs(line) == [("", "just words")] and not line.has_chords

    def test_consecutive_chords_keep_the_empty_lyric(self):
        assert pairs(cp.parse_line("[C][G]x")) == [("C", ""), ("G", "x")]

    def test_a_trailing_chord_keeps_an_empty_lyric(self):
        assert pairs(cp.parse_line("word[C]")) == [("", "word"), ("C", "")]

    def test_japanese_lyrics(self):
        assert pairs(cp.parse_line("[C]あおい[G]そら")) == [("C", "あおい"), ("G", "そら")]

    def test_an_asterisk_makes_an_annotation_not_a_chord(self):
        seg = cp.parse_line("[*Coda]end").segments[0]
        assert (seg.chord, seg.annotation) == ("Coda", True)


class TestParse:
    def test_metadata_and_aliases(self):
        song = cp.parse("{title: Amazing Grace}\n{st: Traditional}\n{artist: John Newton}\n")
        assert (song.title, song.subtitle, song.artist) == ("Amazing Grace", "Traditional", "John Newton")

    def test_a_directive_may_use_a_space_instead_of_a_colon(self):
        assert cp.parse("{title Song}").title == "Song"

    def test_comments_and_hash_lines(self):
        song = cp.parse("# note to self\n{c: Intro}\n{ci: soft}\n{cb: boxed}\n")
        assert [(c.style, c.text) for c in song.items] == [("comment", "Intro"), ("italic", "soft"), ("box", "boxed")]

    def test_a_section_collects_its_lines(self):
        song = cp.parse("{soc: Chorus}\n[C]la\n\n[G]la\n{eoc}\nafter\n")
        section = song.items[0]
        assert (section.kind, section.label) == ("chorus", "Chorus")
        assert [type(i).__name__ for i in section.items] == ["Line", "Blank", "Line"]
        assert isinstance(song.items[1], cp.Line)   # 区間の外に戻る
        assert not song.warnings

    def test_a_tab_section_keeps_lines_as_text(self):
        song = cp.parse("{sot}\ne|--[0]--|\n{eot}\n")
        assert song.items[0].items[0].text == "e|--[0]--|"

    def test_unsupported_directives_are_reported_not_swallowed(self):
        song = cp.parse("{define: C base-fret 1}\n[C]x\n")
        assert song.warnings == [(1, "Unsupported directive 'define'; ignored.")]
        assert len(song.items) == 1

    def test_an_unclosed_section_warns_and_does_not_raise(self):
        song = cp.parse("{sov}\n[C]x\n")
        assert song.items[0].kind == "verse" and song.warnings[0][0] == 0

    def test_an_end_without_start_warns(self):
        assert cp.parse("{eoc}\n").warnings[0][0] == 1

    def test_crlf_input(self):
        assert cp.parse("{title: A}\r\n[C]x\r\n").title == "A"
