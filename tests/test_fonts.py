"""追加のフォント（fonts.dir）と、フォントに無い文字の警告（#376）のテスト。"""
import struct
import sys

import pytest

import text_compositor.compiler as compiler_mod
from text_compositor import diagnostics, fonts
from text_compositor.config import load_config_file


@pytest.fixture(autouse=True)
def _reset_extra_dirs():
    """追加のフォントのフォルダは、プロセスグローバル。他のテストへ、残さない。"""
    fonts.set_extra_font_dirs(())
    yield
    fonts.set_extra_font_dirs(())


def make_font(codepoints_bmp=(), codepoints_astral=()):
    """`cmap`だけを持つ、最小のOpenTypeフォントのバイト列（形式4と形式12）。cmapの読み取りを確かめるための、作り物。"""
    # 形式4: 連続する範囲ごとに、1つの区分。最後に、終端の区分（0xFFFF）
    ranges = []
    for cp in sorted(codepoints_bmp):
        if ranges and ranges[-1][1] == cp - 1:
            ranges[-1][1] = cp
        else:
            ranges.append([cp, cp])
    ranges.append([0xFFFF, 0xFFFF])
    seg = len(ranges)
    ends = [r[1] for r in ranges]
    starts = [r[0] for r in ranges]
    body4 = struct.pack(">HHH", 0, 0, 0)   # searchRange等は、読み取りに使わない
    fmt4 = (struct.pack(">HHHHHHH", 4, 0, 0, seg * 2, 0, 0, 0)
            + struct.pack(f">{seg}H", *ends) + struct.pack(">H", 0) + struct.pack(f">{seg}H", *starts)
            + struct.pack(f">{seg}h", *([0] * seg)) + struct.pack(f">{seg}H", *([0] * seg)))
    # 形式12
    groups = []
    for cp in sorted(codepoints_astral):
        if groups and groups[-1][1] == cp - 1:
            groups[-1][1] = cp
        else:
            groups.append([cp, cp])
    fmt12 = struct.pack(">HHIII", 12, 0, 16 + 12 * len(groups), 0, len(groups))
    for start, end in groups:
        fmt12 += struct.pack(">III", start, end, 0)
    header_len = 4 + 8 * 2
    off4 = header_len
    off12 = off4 + len(fmt4)
    cmap = (struct.pack(">HH", 0, 2) + struct.pack(">HHI", 3, 1, off4) + struct.pack(">HHI", 3, 10, off12) + fmt4 + fmt12)
    table_offset = 12 + 16
    sfnt = struct.pack(">4sHHHH", b"OTTO", 1, 0, 0, 0) + struct.pack(">4sIII", b"cmap", 0, table_offset, len(cmap)) + cmap
    return sfnt


class TestCmapReading:
    def test_reads_bmp_and_astral_characters(self, tmp_path):
        path = tmp_path / "a.otf"
        path.write_bytes(make_font([0x3042, 0x3043, 0x3044, 0xAC00], [0x1F600, 0x1F601]))
        chars = fonts.font_codepoints(str(path))
        assert {0x3042, 0x3043, 0x3044, 0xAC00, 0x1F600, 0x1F601} <= chars
        assert 0x3045 not in chars and 0x1F602 not in chars

    def test_a_broken_file_gives_an_empty_set_and_does_not_raise(self, tmp_path):
        path = tmp_path / "broken.ttf"
        path.write_bytes(b"not a font")
        assert fonts.font_codepoints(str(path)) == frozenset()
        assert fonts.font_codepoints(str(tmp_path / "missing.ttf")) == frozenset()

    def test_the_bundled_font_has_japanese_but_not_hangul(self):
        from text_compositor.deps import ensure_fonts
        try:
            directory = ensure_fonts()
        except SystemExit:
            pytest.skip("fonts are not available")
        covered = fonts.covered_codepoints(directory)
        assert ord("あ") in covered and ord("漢") in covered
        assert ord("한") not in covered and 0x1F600 not in covered


class TestFontPaths:
    def test_without_extra_dirs_the_bundled_folder_is_used_as_before(self):
        assert fonts.font_paths("/x/noto") == ["/x/noto"]
        assert fonts.fonts_signature() == ""

    def test_extra_dirs_are_added_after_the_bundled_folder(self, tmp_path):
        fonts.set_extra_font_dirs([str(tmp_path)])
        assert fonts.font_paths("/x/noto") == ["/x/noto", str(tmp_path)]

    def test_the_signature_changes_when_a_font_is_added(self, tmp_path):
        fonts.set_extra_font_dirs([str(tmp_path)])
        empty = fonts.fonts_signature()
        (tmp_path / "a.ttf").write_bytes(b"x" * 10)
        one = fonts.fonts_signature()
        (tmp_path / "b.otf").write_bytes(b"y" * 20)
        two = fonts.fonts_signature()
        assert empty and one and two and len({empty, one, two}) == 3   # 図のSVGのキャッシュが、描き直される


class TestResolveExtraFontDirs:
    def test_relative_paths_are_based_on_the_project_folder(self, tmp_path):
        (tmp_path / "fonts").mkdir()
        (tmp_path / "fonts" / "a.ttf").write_bytes(b"x")
        assert fonts.resolve_extra_font_dirs({"fonts": {"dir": "fonts"}}, str(tmp_path)) == [str(tmp_path / "fonts")]

    def test_a_list_of_folders_is_accepted(self, tmp_path):
        for name in ("f1", "f2"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "a.ttf").write_bytes(b"x")
        result = fonts.resolve_extra_font_dirs({"fonts": {"dir": ["f1", "f2"]}}, str(tmp_path))
        assert result == [str(tmp_path / "f1"), str(tmp_path / "f2")]

    def test_no_setting_gives_no_folder(self, tmp_path):
        assert fonts.resolve_extra_font_dirs({}, str(tmp_path)) == []
        assert fonts.resolve_extra_font_dirs({"fonts": None}, str(tmp_path)) == []

    def test_a_missing_folder_warns_and_is_dropped(self, tmp_path):
        with diagnostics.collect() as sink:
            result = fonts.resolve_extra_font_dirs({"fonts": {"dir": "nope"}}, str(tmp_path))
        assert result == []
        assert any("not found" in d.message for d in sink.of("warning"))

    def test_a_folder_without_fonts_warns_but_is_kept(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with diagnostics.collect() as sink:
            result = fonts.resolve_extra_font_dirs({"fonts": {"dir": "empty"}}, str(tmp_path))
        assert result == [str(tmp_path / "empty")]
        assert any("no font file" in d.message for d in sink.of("warning"))


class TestConfigValidation:
    def _write(self, tmp_path, text):
        path = tmp_path / "text-compositor.config.yaml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_fonts_dir_is_a_known_key(self, tmp_path):
        config = load_config_file(self._write(tmp_path, "fonts:\n  dir: fonts\nchapters:\n  - a.md\n"))
        assert config["fonts"]["dir"] == "fonts"
        load_config_file(self._write(tmp_path, "fonts:\n  dir: [a, b]\nchapters:\n  - a.md\n"))

    def test_a_typo_in_fonts_is_fail_fast(self, tmp_path):
        with pytest.raises(SystemExit):
            with diagnostics.collect() as sink:
                load_config_file(self._write(tmp_path, "fonts:\n  dirs: fonts\nchapters:\n  - a.md\n"))
        assert any("fonts.dirs" in d.message and "unknown key" in d.message for d in sink.errors)

    def test_a_wrong_type_is_fail_fast(self, tmp_path):
        with pytest.raises(SystemExit):
            with diagnostics.collect() as sink:
                load_config_file(self._write(tmp_path, "fonts:\n  dir: 5\nchapters:\n  - a.md\n"))
        assert any("fonts.dir" in d.message for d in sink.errors)


class TestFindMissingGlyphs:
    covered = frozenset(ord(c) for c in "あいう漢")

    def test_reports_hangul_cjk_and_emoji_with_the_first_line(self):
        text = "あいう\n한국\n漢字 简\n😀 ✅\n"
        found = fonts.find_missing_glyphs(text, self.covered)
        assert found == [(2, "한", "Hangul"), (2, "국", "Hangul"), (3, "字", "CJK ideograph"), (3, "简", "CJK ideograph"),
                         (4, "😀", "emoji"), (4, "✅", "emoji")]

    def test_a_character_is_reported_once_at_its_first_line(self):
        found = fonts.find_missing_glyphs("한\n한\n한\n", self.covered)
        assert found == [(1, "한", "Hangul")]

    def test_characters_the_builtin_fonts_may_have_are_not_reported(self):
        # 内蔵のフォント（DejaVu Sans Mono等）が持つ記号は、誤警告になるため、対象にしない
        assert fonts.find_missing_glyphs("☐ ☑ → ✓ ★ ① ≠ ±", self.covered) == []

    def test_ascii_and_covered_characters_are_ignored(self):
        assert fonts.find_missing_glyphs("plain text あいう漢", self.covered) == []

    def test_an_extra_font_that_has_the_character_removes_the_report(self, tmp_path):
        path = tmp_path / "ko.otf"
        path.write_bytes(make_font([ord("한")]))
        covered = self.covered | fonts.font_codepoints(str(path))
        assert fonts.find_missing_glyphs("한", covered) == []


class TestWarnMissingGlyphs:
    def test_one_warning_per_category_with_the_first_line_and_examples(self, tmp_path):
        font_dir = tmp_path / "bundled"
        font_dir.mkdir()
        (font_dir / "a.otf").write_bytes(make_font([ord("あ")]))
        text = "あ\n한국어 안녕하세요\n\n😀\n"
        with diagnostics.collect() as sink:
            fonts.warn_missing_glyphs(text, "doc.md", str(font_dir))
        warnings = sink.of("warning")
        assert len(warnings) == 2
        hangul = next(d for d in warnings if "Hangul" in d.message)
        assert hangul.file == "doc.md" and hangul.line == 2
        assert "8 Hangul" in hangul.message and "U+D55C" in hangul.message and "and 3 more" in hangul.message
        assert "fonts.dir" in hangul.message
        emoji = next(d for d in warnings if "emoji" in d.message)
        assert emoji.line == 4

    def test_no_warning_when_every_character_is_covered(self, tmp_path):
        font_dir = tmp_path / "bundled"
        font_dir.mkdir()
        (font_dir / "a.otf").write_bytes(make_font([ord("한"), ord("あ")]))
        with diagnostics.collect() as sink:
            fonts.warn_missing_glyphs("あ 한", "doc.md", str(font_dir))
        assert sink.of("warning") == []


def test_the_compiler_gets_the_extra_font_folders(tmp_path, monkeypatch):
    """PDFのコンパイルに、追加のフォントのフォルダが、渡る（Typstの`font_paths`）。"""
    captured = {}

    def fake_compile(path, output=None, **kwargs):
        captured.update(kwargs)
        with open(output, "wb") as f:
            f.write(b"%PDF-1.7\n")

    monkeypatch.setattr(compiler_mod.typst_lib, "compile", fake_compile, raising=False)
    extra = tmp_path / "extra"
    extra.mkdir()
    fonts.set_extra_font_dirs([str(extra)])
    template_copy = tmp_path / "template.typ"
    template_copy.write_text("", encoding="utf-8")
    (tmp_path / "_common.typ").write_text("", encoding="utf-8")   # 成功後の後片づけが、テンプレートの隣の_common.typも消すため
    compiler_mod._compile_and_cleanup(
        "#set page()\n", str(tmp_path), str(tmp_path), {"output": {"filename": "o.pdf"}}, str(tmp_path), "/x/noto",
        str(template_copy), str(tmp_path))
    assert captured["font_paths"] == ["/x/noto", str(extra)]
    assert captured["ignore_system_fonts"] is True   # システムのフォントは、使わない（#71）
