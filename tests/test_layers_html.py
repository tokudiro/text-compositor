"""`::: layers`のHTML出力（text_compositor/layers_html.py・image_size.py。#560）のテスト。"""
import re
import struct

from text_compositor.api import render_html
from text_compositor.image_size import natural_size

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


def png_bytes(width, height):
    """IHDRだけを持つ、最小のPNG（原寸を読むテスト用）。"""
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width, height) + b'\x08\x02\x00\x00\x00'


def svg(width, height):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}"/></svg>'


def convert(tmp_path, markdown, files=None):
    for name, data in (files or {}).items():
        (tmp_path / name).write_bytes(data)
    md = tmp_path / "doc.md"
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), None, plugins=PLAIN)
    html = open(result.html_path, encoding="utf-8").read() if result.ok else ""
    return result, html


def warnings(result):
    return [d.message for d in result.diagnostics if d.severity == "warning"]


def layers_svg(html):
    return re.search(r'<svg class="layers".*?</svg>', html, re.S).group(0)


def images(html):
    return re.findall(r'<image href="([^"]*)" x="([^"]*)" y="([^"]*)" width="([^"]*)" height="([^"]*)"/>', layers_svg(html))


class TestImageSize:
    def test_png(self, tmp_path):
        (tmp_path / "a.png").write_bytes(png_bytes(360, 220))
        assert natural_size(str(tmp_path / "a.png")) == (360, 220)

    def test_gif(self, tmp_path):
        (tmp_path / "a.gif").write_bytes(b'GIF89a' + struct.pack('<HH', 30, 20) + b'\x00' * 8)
        assert natural_size(str(tmp_path / "a.gif")) == (30, 20)

    def test_jpeg_reads_the_frame_header_after_other_segments(self, tmp_path):
        app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9
        sof0 = b'\xff\xc0' + struct.pack('>HBHH', 11, 8, 120, 200) + b'\x00' * 6
        (tmp_path / "a.jpg").write_bytes(b'\xff\xd8' + app0 + sof0)
        assert natural_size(str(tmp_path / "a.jpg")) == (200, 120)

    def test_svg_prefers_absolute_width_and_height(self, tmp_path):
        (tmp_path / "a.svg").write_text('<svg width="96px" height="48" viewBox="0 0 10 5"/>')
        assert natural_size(str(tmp_path / "a.svg")) == (96, 48)

    def test_svg_falls_back_to_the_viewbox(self, tmp_path):
        (tmp_path / "a.svg").write_text('<svg width="100%" viewBox="0 0 244 124"/>')
        assert natural_size(str(tmp_path / "a.svg")) == (244, 124)

    def test_svg_converts_absolute_units(self, tmp_path):
        (tmp_path / "a.svg").write_text('<svg width="72pt" height="1in"/>')
        assert natural_size(str(tmp_path / "a.svg")) == (96, 96)

    def test_unknown_or_missing_gives_none(self, tmp_path):
        (tmp_path / "a.bin").write_bytes(b'not an image')
        assert natural_size(str(tmp_path / "a.bin")) is None
        assert natural_size(str(tmp_path / "none.png")) is None


class TestLayersHtml:
    SVG_FENCE = f"```svg\n{svg(100, 60)}\n```"

    def test_parts_are_drawn_in_source_order_at_natural_size(self, tmp_path):
        md = f"::: layers 注釈つき\n![|x=0|y=0](photo.png)\n\n```svg {{x=240 y=140}}\n{svg(244, 124)}\n```\n:::\n"
        result, html = convert(tmp_path, md, {"photo.png": png_bytes(360, 220)})
        placed = images(html)
        assert [p[1:] for p in placed] == [("0", "0", "360", "220"), ("240", "140", "244", "124")]
        assert placed[0][0].endswith("photo.png") and placed[1][0].endswith(".svg")
        assert warnings(result) == []

    def test_viewbox_is_the_bounding_box_including_overflow(self, tmp_path):
        md = f"::: layers\n![|x=0|y=0](photo.png)\n\n```svg {{x=240 y=140}}\n{svg(244, 124)}\n```\n:::\n"
        _, html = convert(tmp_path, md, {"photo.png": png_bytes(360, 220)})
        tag = layers_svg(html)
        assert 'viewBox="0 0 484 264"' in tag     # 右へ240+244、下へ140+124 まで広がる
        assert 'width="484" height="264"' in tag

    def test_negative_offset_extends_the_box_to_the_upper_left(self, tmp_path):
        md = f"::: layers\n![|x=0|y=0](photo.png)\n\n![|x=-30|y=-10](mark.png)\n:::\n"
        _, html = convert(tmp_path, md, {"photo.png": png_bytes(100, 100), "mark.png": png_bytes(20, 20)})
        assert 'viewBox="-30 -10 130 110"' in layers_svg(html)

    def test_header_becomes_the_alt_of_the_whole_stack(self, tmp_path):
        _, html = convert(tmp_path, f"::: layers 画面の注釈\n{self.SVG_FENCE}\n:::\n")
        tag = layers_svg(html)
        assert 'role="img" aria-label="画面の注釈"' in tag and "aria-hidden" not in tag

    def test_without_a_header_the_stack_is_hidden_from_screen_readers(self, tmp_path):
        _, html = convert(tmp_path, f"::: layers\n{self.SVG_FENCE}\n:::\n")
        tag = layers_svg(html)
        assert 'aria-hidden="true"' in tag and "aria-label" not in tag

    def test_scales_down_as_one_unit(self, tmp_path):
        _, html = convert(tmp_path, f"::: layers\n{self.SVG_FENCE}\n:::\n")
        assert 'style="max-width:100%;height:auto"' in layers_svg(html)

    def test_text_around_the_block_is_kept(self, tmp_path):
        _, html = convert(tmp_path, f"前の文\n\n::: layers\n{self.SVG_FENCE}\n:::\n\n後ろの文\n")
        assert html.index("前の文") < html.index('<svg class="layers"') < html.index("後ろの文")


class TestLayersHtmlWarnings:
    SVG_FENCE = f"```svg\n{svg(10, 10)}\n```"

    def test_missing_image_is_skipped_with_one_warning(self, tmp_path):
        result, html = convert(tmp_path, f"::: layers\n![](none.png)\n\n{self.SVG_FENCE}\n:::\n")
        assert len(images(html)) == 1
        assert sum("Image not found" in w for w in warnings(result)) == 1

    def test_external_image_is_not_loaded(self, tmp_path):
        result, html = convert(tmp_path, f"::: layers\n![](https://example.com/a.png)\n\n{self.SVG_FENCE}\n:::\n")
        assert len(images(html)) == 1 and "example.com" not in html.split("<main>", 1)[1]
        assert any("External image blocked" in w for w in warnings(result))

    def test_unreadable_size_is_skipped(self, tmp_path):
        result, html = convert(tmp_path, f"::: layers\n![](a.bmp)\n\n{self.SVG_FENCE}\n:::\n", {"a.bmp": b"BM" + b"\x00" * 30})
        assert len(images(html)) == 1
        assert any("Cannot read the size" in w for w in warnings(result))

    def test_no_drawable_part_shows_nothing_and_warns(self, tmp_path):
        result, html = convert(tmp_path, "::: layers\n![](none.png)\n:::\n")
        assert '<svg class="layers"' not in html
        assert any("no part that can be drawn" in w for w in warnings(result))

    def test_size_attributes_warn_and_are_ignored(self, tmp_path):
        result, html = convert(tmp_path, f"::: layers\n![|width=50%](a.png)\n:::\n", {"a.png": png_bytes(40, 30)})
        assert images(html)[0][3:] == ("40", "30")
        assert any("width" in w for w in warnings(result))

