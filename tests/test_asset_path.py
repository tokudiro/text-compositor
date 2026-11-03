"""画像のパスの`%20`の解決（text_compositor/asset_path.py。#586）のテスト。"""
import os
import struct

import pytest

from text_compositor.api import render_html
from text_compositor.asset_path import resolve_local_asset
from text_compositor.renderer import TypstRenderer


def png_bytes(width, height):
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width, height) + b'\x08\x02\x00\x00\x00'


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "sub dir").mkdir()
    (tmp_path / "sub dir" / "a b.png").write_bytes(png_bytes(40, 20))
    return tmp_path


def pdf(folder, markdown):
    renderer = TypstRenderer(line_mapping="off", base_dir=str(folder), typst_root=str(folder))
    return renderer.render(markdown, filepath=str(folder / "doc.md"))


class TestResolve:
    def test_percent_20_finds_the_file_with_spaces(self, folder):
        assert resolve_local_asset(str(folder), "sub%20dir/a%20b.png") == os.path.normpath(str(folder / "sub dir" / "a b.png"))

    def test_plain_spaces_still_work(self, folder):
        assert resolve_local_asset(str(folder), "sub dir/a b.png") == os.path.normpath(str(folder / "sub dir" / "a b.png"))

    def test_the_name_as_written_wins_when_it_exists(self, folder):
        (folder / "a%20b.png").write_bytes(png_bytes(1, 1))
        (folder / "a b.png").write_bytes(png_bytes(2, 2))
        assert resolve_local_asset(str(folder), "a%20b.png") == os.path.normpath(str(folder / "a%20b.png"))

    def test_query_and_fragment_are_dropped_as_a_last_resort(self, folder):
        assert resolve_local_asset(str(folder), "sub%20dir/a%20b.png?v=1#top") == os.path.normpath(str(folder / "sub dir" / "a b.png"))

    def test_a_name_with_a_hash_that_exists_is_kept(self, folder):
        (folder / "a#1.png").write_bytes(png_bytes(1, 1))
        assert resolve_local_asset(str(folder), "a#1.png") == os.path.normpath(str(folder / "a#1.png"))

    def test_missing_gives_the_path_as_written(self, folder):
        assert resolve_local_asset(str(folder), "none%20x.png") == os.path.normpath(str(folder / "none%20x.png"))


class TestPdfAndHtml:
    def test_plain_image_in_pdf(self, folder):
        assert '"/sub dir/a b.png"' in pdf(folder, "![](sub%20dir/a%20b.png)\n")

    def test_layers_image_in_pdf(self, folder):
        out = pdf(folder, "::: layers x\n![](sub%20dir/a%20b.png)\n:::\n")
        assert out.count("place(top + left") == 1 and "/sub dir/a b.png" in out

    def test_angle_brackets_and_plain_spaces_in_pdf_still_work(self, folder):
        assert '"/sub dir/a b.png"' in pdf(folder, "![](<sub dir/a b.png>)\n")

    def test_missing_image_is_still_an_error_in_pdf(self, folder):
        with pytest.raises(SystemExit):
            pdf(folder, "![](none%20x.png)\n")

    def test_html_and_pdf_agree(self, folder):
        md = "::: layers x\n![](sub%20dir/a%20b.png)\n:::\n"
        (folder / "doc.md").write_text(md, encoding="utf-8")
        result = render_html(str(folder / "doc.md"), None, plugins={"mermaid": False, "plantuml": False, "d2": False})
        html = open(result.html_path, encoding="utf-8").read()
        assert result.ok and html.count("<image ") == 1
        assert pdf(folder, md).count("place(top + left") == 1
