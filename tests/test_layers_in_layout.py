"""`layout-*`の中に置いた`::: layers`を、1つの図として扱うテスト（#560）。"""
import struct

import pytest

from text_compositor.api import render_html
from text_compositor.renderer import TypstRenderer


def png_bytes(width, height):
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width, height) + b'\x08\x02\x00\x00\x00'


LAYERS = "::: layers 注釈つき\n![|x=0|y=0](a.png)\n\n![|x=10|y=10](b.png)\n:::"
FILES = {"a.png": png_bytes(100, 80), "b.png": png_bytes(20, 20)}


def prepare(tmp_path):
    for name, data in FILES.items():
        (tmp_path / name).write_bytes(data)


def pdf(tmp_path, markdown):
    prepare(tmp_path)
    renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
    return renderer.render(markdown, filepath=str(tmp_path / "doc.md"))


def convert(tmp_path, markdown):
    prepare(tmp_path)
    md = tmp_path / "doc.md"
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), None, plugins={"mermaid": False, "plantuml": False, "d2": False})
    return result, (open(result.html_path, encoding="utf-8").read() if result.ok else "")


def html(tmp_path, markdown):
    return convert(tmp_path, markdown)[1]


@pytest.mark.parametrize("kind", ["layout-right", "layout-left"])
class TestSide:
    def test_pdf_places_the_whole_stack_in_the_image_cell(self, tmp_path, kind):
        out = pdf(tmp_path, f"::: {kind}\n説明文\n\n{LAYERS}\n:::\n")
        assert "#grid(" in out and out.count("place(top + left") == 2
        assert "説明文" in out
        assert "::: layers" not in out

    def test_html_has_one_svg_with_both_images(self, tmp_path, kind):
        out = html(tmp_path, f"::: {kind}\n説明文\n\n{LAYERS}\n:::\n")
        assert out.count('<svg class="layers"') == 1 and out.count("<image ") == 2
        assert f'class="layout {kind}"' in out and "説明文" in out
        assert "::: layers" not in out


class TestCompare:
    def test_layers_and_a_plain_image_are_the_two_cells(self, tmp_path):
        md = f"::: layout-compare\n{LAYERS}\n\n![](a.png)\n:::\n"
        assert html(tmp_path, md).count("<image ") == 2
        assert pdf(tmp_path, md).count("place(top + left") == 2

    def test_two_layers_are_two_cells(self, tmp_path):
        md = f"::: layout-compare\n{LAYERS}\n\n{LAYERS}\n:::\n"
        assert html(tmp_path, md).count('<svg class="layers"') == 2


class TestFeature:
    def test_caption_overlays_the_stack(self, tmp_path):
        md = f"::: layout-feature\n{LAYERS}\n\nキャッチコピー\n:::\n"
        out = html(tmp_path, md)
        assert out.count('<svg class="layers"') == 1 and "キャッチコピー" in out
        assert "キャッチコピー" in pdf(tmp_path, md)


class TestInOtherBlocks:
    """`align`・`layout-columns`・`layout-takahashi`の中の地の文にも、置ける。"""

    @pytest.mark.parametrize("opening", ["::: align {align=center}", "::: layout-columns", "::: layout-takahashi {size=20pt}"])
    def test_html_draws_it_and_keeps_the_text(self, tmp_path, opening):
        out = html(tmp_path, f"{opening}\n前の文\n\n{LAYERS}\n\n後の文\n:::\n")
        assert out.count('<svg class="layers"') == 1 and out.count("<image ") == 2
        assert "前の文" in out and "後の文" in out and "::: layers" not in out

    @pytest.mark.parametrize("opening", ["::: align {align=center}", "::: layout-columns", "::: layout-takahashi {size=20pt}"])
    def test_pdf_draws_it_and_keeps_the_text(self, tmp_path, opening):
        out = pdf(tmp_path, f"{opening}\n前の文\n\n{LAYERS}\n\n後の文\n:::\n")
        assert out.count("place(top + left") == 2
        assert "前の文" in out and "後の文" in out and "::: layers" not in out

    def test_second_layers_in_the_text_cell_of_layout_right(self, tmp_path):
        md = f"::: layout-right\n{LAYERS}\n\n{LAYERS}\n:::\n"
        assert html(tmp_path, md).count('<svg class="layers"') == 2
        assert pdf(tmp_path, md).count("place(top + left") == 4

    def test_layers_inside_a_code_fence_stays_as_text(self, tmp_path):
        out = html(tmp_path, "::: align {align=center}\n````markdown\n::: layers x\n![](a.png)\n:::\n````\n:::\n")
        assert '<svg class="layers"' not in out and "::: layers x" in out


SVG_FENCE = '```svg\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" height="10"/></svg>\n```'


class TestDarkInversion:
    """ダークで反転するのは、部品がすべて図のフェンスの重ねだけ（通常の図は反転し、通常の画像は反転しない規則に揃える）。"""

    def test_only_fences_are_inverted(self, tmp_path):
        out = html(tmp_path, f"::: layers x\n{SVG_FENCE}\n\n{SVG_FENCE}\n:::\n")
        assert '<svg class="layers layers-invert"' in out
        assert "svg.layers-invert { filter: invert(1)" in out

    def test_an_image_file_keeps_the_stack_as_it_is(self, tmp_path):
        out = html(tmp_path, f"::: layers x\n![](a.png)\n\n{SVG_FENCE}\n:::\n")
        assert '<svg class="layers"' in out
        assert '<svg class="layers layers-invert"' not in out

    def test_an_svg_file_counts_as_an_image(self, tmp_path):
        (tmp_path / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
        out = html(tmp_path, "::: layers x\n![](logo.svg)\n:::\n")
        assert '<svg class="layers"' in out


class TestInnerPartsAreNotPickedUp:
    def test_image_inside_layers_is_not_taken_as_the_single_diagram(self, tmp_path):
        # layers 1つだけ。中の画像2枚が個別に拾われると、layout-compareの「ちょうど2つ」を満たしてしまう
        result, _ = convert(tmp_path, f"::: layout-compare\n{LAYERS}\n:::\n")
        assert not result.ok
