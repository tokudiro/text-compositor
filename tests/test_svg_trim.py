"""生成済みSVGの余白トリミング（svg_trim.py、#315）のテスト。

resvg_py・Pillow（どちらもopt-inの依存、plugins.diagram_trim: trueのときだけ要る）が
無い環境では、実際のラスタライズを伴うテストをスキップする（tests/test_mermaid_resident.py の
TestRealBrowser と同じ考え方）。"""
import pytest

from text_compositor import svg_trim


def _has_resvg():
    try:
        import resvg_py  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


# 透明な背景に、(20,20)-(40,60)の範囲だけ赤い矩形がある、200x200のSVG（Mermaidのような
# 透明背景のケースを想定）。
TRANSPARENT_BG_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
    '<rect x="20" y="20" width="20" height="40" fill="red"/>'
    '</svg>'
)

# 全面を白で塗ってから、(20,20)-(40,60)の範囲だけ赤い矩形を重ねる、200x200のSVG
# （D2のように、自身で不透明な背景矩形を描くケースを想定）。
OPAQUE_BG_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
    '<rect x="0" y="0" width="200" height="200" fill="white"/>'
    '<rect x="20" y="20" width="20" height="40" fill="red"/>'
    '</svg>'
)


@pytest.mark.skipif(not _has_resvg(), reason="needs resvg_py and Pillow")
class TestTrimSvg:
    def test_shrinks_to_content_with_transparent_background(self):
        trimmed = svg_trim.trim_svg(TRANSPARENT_BG_SVG, margin=4)
        minx, miny, w, h = (float(x) for x in svg_trim._VIEWBOX_RE.search(trimmed).group(1).split())
        # 内容は x:20-40, y:20-60。安全マージン4を引いた分だけ広く、元の200x200よりは
        # ずっと小さいはず。
        assert minx == pytest.approx(16, abs=1)
        assert miny == pytest.approx(16, abs=1)
        assert w == pytest.approx(28, abs=2)
        assert h == pytest.approx(48, abs=2)

    def test_ignores_an_opaque_full_canvas_background_rect(self):
        """D2のように、自身で不透明な背景矩形を描く場合でも、背景ではなく実際の内容（赤い矩形）を
        基準にトリミングできることを確かめる（#315で判明した、透明度だけでは判定できない挙動への対応）。"""
        trimmed = svg_trim.trim_svg(OPAQUE_BG_SVG, margin=4)
        minx, miny, w, h = (float(x) for x in svg_trim._VIEWBOX_RE.search(trimmed).group(1).split())
        assert minx == pytest.approx(16, abs=1)
        assert miny == pytest.approx(16, abs=1)
        assert w == pytest.approx(28, abs=2)
        assert h == pytest.approx(48, abs=2)

    def test_percent_width_is_left_untouched(self):
        """Mermaidのwidth="100%"のような相対値は、絶対サイズに書き換えると意味が変わってしまうため、
        対象外にする。"""
        svg = TRANSPARENT_BG_SVG.replace('width="200"', 'width="100%"')
        trimmed = svg_trim.trim_svg(svg, margin=4)
        assert 'width="100%"' in trimmed

    def test_style_width_height_are_updated(self):
        """PlantUML・Structurizrが持つ、style属性中のwidth/height（px）も、<img>で埋め込む際に
        優先されるため、更新する必要がある（#315）。"""
        svg = TRANSPARENT_BG_SVG.replace(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">',
            '<svg xmlns="http://www.w3.org/2000/svg" style="width:200px;height:200px;background:#FFFFFF;" '
            'width="200" height="200" viewBox="0 0 200 200">',
        )
        trimmed = svg_trim.trim_svg(svg, margin=4)
        style = svg_trim._ROOT_SVG_RE.search(trimmed).group(0)
        assert 'width:200px' not in style
        assert 'height:200px' not in style

    def test_solid_color_image_raises_trim_error(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50" width="50" height="50"></svg>'
        with pytest.raises(svg_trim.TrimError):
            svg_trim.trim_svg(svg)


class TestTrimSvgWithoutRendering:
    """viewBoxが無い等、ラスタライズ以前に判定できるケースは、resvg_py・Pillo無しでも試せる。"""

    def test_no_root_svg_tag_raises_trim_error(self):
        with pytest.raises(svg_trim.TrimError):
            svg_trim.trim_svg("not an svg at all")

    def test_missing_viewbox_raises_trim_error(self):
        with pytest.raises(svg_trim.TrimError):
            svg_trim.trim_svg('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>')

    def test_empty_viewbox_raises_trim_error(self):
        with pytest.raises(svg_trim.TrimError):
            svg_trim.trim_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 0"></svg>')
