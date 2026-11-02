"""`::: layers`のPDF出力（text_compositor/layers_pdf.py。#560）のテスト。"""
import re
import struct

import pytest

from text_compositor.renderer import TypstRenderer


def png_bytes(width, height):
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width, height) + b'\x08\x02\x00\x00\x00'


def svg(width, height):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}"/></svg>'


def render(tmp_path, markdown, files=None):
    for name, data in (files or {}).items():
        (tmp_path / name).write_bytes(data)
    renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
    return renderer.render(markdown, filepath=str(tmp_path / "doc.md"))


def places(out):
    """place(...)の(dx, dy, 幅, 高さ)をptの数値で取り出す。"""
    found = re.findall(r'place\(top \+ left, dx: ([-\d.]+)pt, dy: ([-\d.]+)pt, image\("([^"]*)", width: ([\d.]+)pt, height: ([\d.]+)pt, alt: ([^)]*)\)\)', out)
    return [(float(dx), float(dy), path, float(w), float(h), alt) for dx, dy, path, w, h, alt in found]


class TestLayersPdf:
    def test_parts_are_placed_in_source_order_at_natural_size(self, tmp_path):
        md = f"::: layers 注釈つき\n![|x=0|y=0](photo.png)\n\n```svg {{x=240 y=140}}\n{svg(244, 124)}\n```\n:::\n"
        out = render(tmp_path, md, {"photo.png": png_bytes(360, 220)})
        placed = places(out)
        # 1px = 0.75pt
        assert [(p[0], p[1], p[3], p[4]) for p in placed] == [(0, 0, 270, 165), (180, 105, 183, 93)]
        assert placed[0][2] == "/photo.png" and placed[1][2].endswith(".svg")

    def test_box_is_the_bounding_box_including_overflow(self, tmp_path):
        md = f"::: layers\n![|x=0|y=0](photo.png)\n\n```svg {{x=240 y=140}}\n{svg(244, 124)}\n```\n:::\n"
        out = render(tmp_path, md, {"photo.png": png_bytes(360, 220)})
        assert "box(width: 363pt, height: 198pt" in out     # 484px x 264px

    def test_negative_offset_moves_everything_into_the_box(self, tmp_path):
        out = render(tmp_path, "::: layers\n![](a.png)\n\n![|x=-30|y=-10](b.png)\n:::\n",
                     {"a.png": png_bytes(100, 100), "b.png": png_bytes(20, 20)})
        assert [(p[0], p[1]) for p in places(out)] == [(22.5, 7.5), (0, 0)]
        assert "box(width: 97.5pt, height: 82.5pt" in out

    def test_whole_stack_shrinks_to_the_width_and_to_the_height_limit(self, tmp_path):
        out = render(tmp_path, f"::: layers\n```svg\n{svg(400, 300)}\n```\n:::\n")
        assert "calc.min(1, size.width / 300pt, 12cm / 225pt)" in out
        assert "scale(k * 100%, reflow: true, origin: top + left" in out

    def test_header_is_the_alt_of_the_first_part_only(self, tmp_path):
        out = render(tmp_path, "::: layers 画面の注釈\n![](a.png)\n\n![](b.png)\n:::\n",
                     {"a.png": png_bytes(10, 10), "b.png": png_bytes(10, 10)})
        assert [p[5] for p in places(out)] == ['"画面の注釈"', 'none']

    def test_without_a_header_every_part_is_decorative(self, tmp_path):
        out = render(tmp_path, "::: layers\n![](a.png)\n:::\n", {"a.png": png_bytes(10, 10)})
        assert [p[5] for p in places(out)] == ['none']

    def test_missing_image_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit):
            render(tmp_path, "::: layers\n![](none.png)\n:::\n")

    def test_block_without_a_drawable_part_gives_nothing(self, tmp_path):
        out = render(tmp_path, "前\n\n::: layers\n```svg\n<svg/>\n```\n:::\n\n後\n")
        assert "place(" not in out and "前" in out and "後" in out
