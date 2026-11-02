""":::ブロックの切り出し（text_compositor/layout_blocks.py）の、入れ子の対応のテスト（#560）。"""
from text_compositor.layout_blocks import find_layout_blocks

LAYERS = '::: layers 注釈つき\n![|x=1](a.png)\n\n```svg\n<svg/>\n```\n:::'


def blocks(text, protected=()):
    return find_layout_blocks(text, list(protected))


class TestNesting:
    def test_layers_inside_a_layout_block_does_not_close_it_early(self):
        text = f'::: layout-right\n説明\n\n{LAYERS}\n:::\n後ろ\n'
        found = blocks(text)
        assert len(found) == 1
        assert found[0].group(1) == 'layout-right'
        assert found[0].group(3) == f'説明\n\n{LAYERS}'
        assert text[found[0].end():] == '\n後ろ\n'

    def test_two_layers_in_one_block(self):
        text = f'::: layout-compare\n{LAYERS}\n\n{LAYERS}\n:::\n'
        found = blocks(text)
        assert len(found) == 1 and found[0].group(3).count('::: layers') == 2

    def test_top_level_layers_is_a_block_with_its_header_as_attrs(self):
        found = blocks(f'前\n\n{LAYERS}\n\n後\n')
        assert len(found) == 1 and found[0].group(1) == 'layers'
        assert found[0].group(2) == '注釈つき'
        assert found[0].group(3).startswith('![|x=1](a.png)')

    def test_layers_without_header_gives_none(self):
        assert blocks('::: layers\n```svg\n<svg/>\n```\n:::\n')[0].group(2) is None

    def test_blocks_after_a_nested_one_are_found(self):
        text = f'::: layout-right\n{LAYERS}\n:::\n\n::: align {{align=center}}\n中央\n:::\n'
        assert [b.group(1) for b in blocks(text)] == ['layout-right', 'align']


class TestPdfPipeline:
    def test_text_after_a_block_with_a_nested_layers_stays_outside_the_grid(self):
        from text_compositor.renderer import TypstRenderer
        nested = '::: layers 注釈\n```svg\n<svg viewBox="0 0 1 1"/>\n```\n:::'
        text = f'::: layout-right\n説明\n\n{nested}\n:::\n\n後ろの文\n'
        out = TypstRenderer(line_mapping="off").render(text)
        assert out.count('#grid(') == 1
        assert out.rstrip().endswith('後ろの文')
        assert '後ろの文' not in out.split('\n)\n', 1)[0]


class TestCompatibility:
    def test_attrs_and_body(self):
        found = blocks('::: layout-right {left=30 right=70}\nt\n:::\n')[0]
        assert (found.group(1), found.group(2), found.group(3)) == ('layout-right', 'left=30 right=70', 't')

    def test_no_attrs_gives_none(self):
        assert blocks('::: align\nt\n:::\n')[0].group(2) is None

    def test_start_of_body(self):
        text = '::: align\nt\n:::\n'
        found = blocks(text)[0]
        assert text[found.start(3):].startswith('t\n')
        assert found.start() == 0

    def test_crlf(self):
        text = '::: layout-right\r\nt\r\n:::\r\n'
        found = blocks(text)[0]
        assert found.group(3) == 't' and text[found.start():found.end()] == text.rstrip('\n')

    def test_unclosed_block_is_ignored(self):
        assert blocks('::: layout-right\nt\n') == []

    def test_unknown_block_is_not_a_layout_block(self):
        assert blocks('::: note\nt\n:::\n') == []

    def test_opener_inside_a_fence_is_ignored(self):
        text = '```\n::: align\nt\n:::\n```\n'
        assert blocks(text, [(0, len(text))]) == []
