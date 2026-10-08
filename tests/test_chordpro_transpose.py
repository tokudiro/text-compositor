"""ChordProの転調（chordpro_transpose と、パーサの`{key}`・`{capo}`・`{transpose}`。#442）のテスト。"""
import pytest

from text_compositor import chordpro_render as cp
from text_compositor import chordpro_transpose as tr


class TestSplitChord:
    @pytest.mark.parametrize("name, expected", [
        ("C", ("C", "", None)),
        ("F#m7", ("F#", "m7", None)),
        ("Bb", ("Bb", "", None)),
        ("Bbm7", ("Bb", "m7", None)),
        ("Bdim", ("B", "dim", None)),
        ("Csus4", ("C", "sus4", None)),
        ("C/E", ("C", "", "E")),
        ("Am7/G", ("A", "m7", "G")),
        ("D/F#", ("D", "", "F#")),
        ("C/9", ("C", "/9", None)),
    ])
    def test_the_root_the_quality_and_the_bass_are_separated(self, name, expected):
        assert tr.split_chord(name) == expected

    @pytest.mark.parametrize("name", ["", "H", "x", "Intro", "/E"])
    def test_a_name_that_is_not_a_chord_is_not_split(self, name):
        assert tr.split_chord(name) is None


class TestTransposeChord:
    @pytest.mark.parametrize("name, n, flats, expected", [
        ("B", 1, False, "C"),
        ("E", 1, False, "F"),
        ("F#m", 1, False, "Gm"),
        ("C", 1, False, "C#"),
        ("C", 1, True, "Db"),
        ("C", -1, False, "B"),
        ("A", 12, False, "A"),          # 1オクターブは、元に戻る
        ("A", -13, False, "G#"),
        ("C/E", 1, False, "C#/F"),      # スラッシュの後ろの音も動かす
        ("Am7/G", 2, False, "Bm7/A"),
        ("Bbm7", 2, False, "Cm7"),
        ("Csus4", 7, False, "Gsus4"),   # 種類は、そのまま残す
        ("C/9", 2, False, "D/9"),
    ])
    def test_the_root_and_the_bass_move_and_the_quality_stays(self, name, n, flats, expected):
        assert tr.transpose_chord(name, n, flats) == expected

    def test_no_chord_stays(self):
        assert tr.transpose_chord("N.C.", 3, False) == "N.C."

    def test_an_unreadable_name_is_none(self):
        assert tr.transpose_chord("Intro", 3, False) is None


class TestKey:
    @pytest.mark.parametrize("key, n, expected", [
        ("B", 1, "C"),
        ("F#m", 1, "Gm"),
        ("C", 2, "D"),
        ("C", 5, "F"),
        ("C", 3, "Eb"),     # フラット系の調は、フラットで書く
        ("C", 6, "F#"),
        ("Am", 3, "Cm"),
        ("Am", 8, "Fm"),
        ("Em", 1, "Fm"),
    ])
    def test_the_key_moves_and_is_spelled_by_the_target_key(self, key, n, expected):
        assert tr.transpose_key(key, n) == expected

    def test_an_unreadable_key_is_none(self):
        assert tr.transpose_key("sharp", 1) is None


class TestChoosesFlats:
    def test_the_target_key_decides_when_there_is_a_key(self):
        assert tr.chooses_flats(5, "C", ["C"]) is True      # F
        assert tr.chooses_flats(2, "C", ["C"]) is False     # D
        assert tr.chooses_flats(3, "Am", ["Am"]) is True    # Cm

    def test_without_a_key_the_written_accidentals_decide(self):
        assert tr.chooses_flats(1, None, ["Bb", "Eb"]) is True
        assert tr.chooses_flats(-1, None, ["F#", "C#m"]) is False

    def test_without_a_key_or_accidentals_the_direction_decides(self):
        assert tr.chooses_flats(1, None, ["C", "G"]) is False   # 上げるとき: シャープ
        assert tr.chooses_flats(-1, None, ["C", "G"]) is True   # 下げるとき: フラット


def chords(song):
    return [s.chord for line in cp._lines(song.items) for s in line.segments if s.chord]


class TestParseTranspose:
    def test_the_original_key_and_the_ukulele_key(self):
        song = cp.parse("{key: B}\n{transpose: 1}\n[B]a[E]b[F#m]c\n")
        assert chords(song) == ["C", "F", "Gm"]
        assert (song.key, song.play_key, song.shift) == ("B", "C", 1)
        assert not song.warnings

    def test_without_transpose_the_chords_are_left_as_written(self):
        song = cp.parse("{key: B}\n[B]a[E]b\n")
        assert chords(song) == ["B", "E"] and song.play_key == "" and song.shift == 0

    def test_a_signed_number_and_zero(self):
        assert chords(cp.parse("{transpose: +2}\n[C]x\n")) == ["D"]
        assert chords(cp.parse("{transpose: -2}\n[C]x\n")) == ["Bb"]
        assert chords(cp.parse("{transpose: 0}\n[C]x\n")) == ["C"]

    def test_a_transpose_in_the_middle_applies_to_the_following_lines_only(self):
        song = cp.parse("[C]a\n{transpose: 2}\n[C]b\n")
        assert chords(song) == ["C", "D"]
        assert song.shift == 0   # 見出しは、最初のコードの行の転調

    def test_annotations_and_no_chord_are_not_moved(self):
        song = cp.parse("{transpose: 2}\n[*Coda]a[N.C.]b[C]c\n")
        assert [(s.chord, s.annotation) for s in song.items[0].segments] == [("Coda", True), ("N.C.", False), ("D", False)]

    def test_the_key_decides_the_accidentals(self):
        assert chords(cp.parse("{key: C}\n{transpose: 5}\n[C]a[G]b\n")) == ["F", "C"]
        assert chords(cp.parse("{key: C}\n{transpose: 3}\n[C]a[G]b\n")) == ["Eb", "Bb"]

    def test_an_unreadable_chord_is_kept_with_one_warning(self):
        song = cp.parse("{transpose: 2}\n[Intro]a\n[Intro]b[C]c\n")
        assert chords(song) == ["Intro", "Intro", "D"]
        assert [w for w in song.warnings if "Intro" in w[1]] == [(2, "Cannot transpose the chord 'Intro'; shown as written.")]

    def test_tab_sections_are_not_transposed(self):
        song = cp.parse("{transpose: 2}\n{sot}\ne|--[0]--|\n{eot}\n")
        assert song.items[0].items[0].text == "e|--[0]--|"

    def test_an_invalid_transpose_warns_and_is_ignored(self):
        song = cp.parse("{transpose: up}\n[C]x\n")
        assert chords(song) == ["C"] and song.warnings[0][0] == 1

    def test_a_section_inside_inherits_the_shift(self):
        song = cp.parse("{transpose: 2}\n{soc}\n[C]x\n{eoc}\n")
        assert chords(song) == ["D"]


class TestParseKeyAndCapo:
    def test_capo_is_stored_and_the_chords_are_not_changed(self):
        song = cp.parse("{capo: 2}\n[C]x\n")
        assert song.capo == 2 and chords(song) == ["C"] and not song.warnings

    def test_an_invalid_capo_warns(self):
        song = cp.parse("{capo: two}\n")
        assert song.capo is None and song.warnings[0][0] == 1

    def test_an_unreadable_key_warns_and_is_kept_as_written(self):
        song = cp.parse("{key: sharp}\n{transpose: 1}\n[C]x\n")
        assert song.key == "sharp" and song.play_key == ""
        assert any("Unreadable key" in w[1] for w in song.warnings)

    def test_a_minor_key(self):
        song = cp.parse("{key: F#m}\n{transpose: 1}\n[F#m]x\n")
        assert song.play_key == "Gm" and chords(song) == ["Gm"]
