"""layout-right/left/compare/feature/columns/takahashi/align（#78, #81, #95, #87等）の
リグレッションテスト（#96）。

TestFenceProtectionRegressionは、レイアウトブロック内に実際の図表フェンスを置くと常に
検出失敗していた不具合（#127）の再現・修正確認を兼ねる。
"""
from text_compositor.renderer import TypstRenderer


def render(md_text):
    return TypstRenderer(line_mapping="off").render(md_text)


class TestLayoutRight:
    def test_real_diagram_fence_is_detected(self):
        """#127: 実際の図表フェンスを置いた場合に検出できること（修正前は常に失敗していた）。"""
        out = render("::: layout-right\nテキストです。\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert '#raw("digraph{a->b}", lang: "dot", block: true)' in out
        assert "テキストです。" in out
        assert out.startswith("#grid(\n")
        assert "columns: (35fr, 65fr)" in out

    def test_default_ratio_is_35_65(self):
        out = render("::: layout-right\nt\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert "columns: (35fr, 65fr)" in out

    def test_explicit_ratio(self):
        out = render("::: layout-right {left=30 right=70}\nt\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert "columns: (30fr, 70fr)" in out

    def test_text_is_left_image_is_right(self):
        out = render("::: layout-right\nt\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        text_idx = out.index("[t]")
        image_idx = out.index('#raw("digraph{a->b}"')
        assert text_idx < image_idx

    def test_missing_diagram_or_image_exits(self):
        import pytest
        with pytest.raises(SystemExit):
            render("::: layout-right\nテキストだけ\n:::\n")

    def test_standalone_image_is_accepted(self, tmp_path):
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG\r\n")
        md_path = tmp_path / "doc.md"
        md = f"::: layout-right\nテキスト\n\n![alt]({img.name})\n:::\n"
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        out = renderer.render(md, filepath=str(md_path))
        # width/height未指定なのでfit-image()になる（#69）
        assert "#fit-image(" in out


class TestLayoutLeft:
    def test_image_is_left_text_is_right(self):
        out = render("::: layout-left\nt\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        image_idx = out.index('#raw("digraph{a->b}"')
        text_idx = out.index("[t]")
        assert image_idx < text_idx

    def test_default_ratio_is_65_35(self):
        out = render("::: layout-left\nt\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert "columns: (65fr, 35fr)" in out


class TestLayoutCompare:
    def test_two_diagrams_side_by_side(self):
        out = render(
            "::: layout-compare\n```dot\ndigraph{a->b}\n```\n```dot\ndigraph{c->d}\n```\n:::\n"
        )
        assert '#raw("digraph{a->b}"' in out
        assert '#raw("digraph{c->d}"' in out
        assert "columns: (1fr, 1fr)" in out

    def test_wrong_count_exits(self):
        import pytest
        with pytest.raises(SystemExit):
            render("::: layout-compare\n```dot\ndigraph{a->b}\n```\n:::\n")


class TestLayoutFeature:
    def test_catchcopy_and_cover_image(self):
        out = render("::: layout-feature\nキャッチコピー\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert "キャッチコピー" in out
        assert '#raw("digraph{a->b}"' in out
        assert 'height: 70%' in out


class TestLayoutColumns:
    def test_default_is_two_columns(self):
        out = render("::: layout-columns\n本文\n:::\n")
        assert "#columns(2, gutter: 1.5em" in out

    def test_explicit_column_count(self):
        out = render("::: layout-columns {n=3}\n本文\n:::\n")
        assert "#columns(3, gutter: 1.5em" in out


class TestLayoutTakahashi:
    def test_default_size(self):
        out = render("::: layout-takahashi\n大文字\n:::\n")
        assert out == '#align(center + horizon)[#text(size: 96pt)[大文字]]\n\n'

    def test_explicit_size(self):
        out = render("::: layout-takahashi {size=50pt}\n大文字\n:::\n")
        assert out == '#align(center + horizon)[#text(size: 50pt)[大文字]]\n\n'


class TestAlignBlock:
    def test_default_is_left(self):
        out = render("::: align\n寄せなし\n:::\n")
        assert out == '#align(left)[寄せなし]\n\n'

    def test_explicit_align(self):
        out = render("::: align {align=right}\n右寄せ\n:::\n")
        assert out == '#align(right)[右寄せ]\n\n'


class TestFenceProtectionRegression:
    """#85（説明用サンプルの誤認識防止）と#127（本物の図表フェンスの検出失敗）を両立できているか。"""

    def test_wrapped_example_is_not_treated_as_a_real_layout_block(self):
        """外側フェンスで囲んだ使い方説明サンプルは、本物のlayout-rightとして解釈されない（#85）。"""
        wrapped = (
            "````markdown\n"
            "::: layout-right\n"
            "左にこのテキスト、右に図が並びます。\n"
            "\n"
            "```dot\n"
            "digraph{a->b}\n"
            "```\n"
            ":::\n"
            "````\n"
        )
        out = render(wrapped)
        assert "#grid(" not in out
        assert out.startswith('#raw("')

    def test_real_fence_inside_layout_block_is_detected(self):
        """layout-rightの中に実際の図表フェンスを置いた場合は検出できる（#127）。"""
        out = render("::: layout-right\nテキストです。\n\n```dot\ndigraph{a->b}\n```\n:::\n")
        assert "#grid(" in out
        assert '#raw("digraph{a->b}"' in out
