"""`::: layers`ブロックの解析（text_compositor/layers.py。#560）のテスト。"""
from text_compositor.layers import parse_layers_block

SVG = '```svg\n<svg viewBox="0 0 10 10"></svg>\n```'


class TestParts:
    def test_parts_keep_source_order(self):
        body = f'![a](photo.png)\n\n{SVG}\n\n```mermaid\ngraph LR; A-->B\n```\n'
        block = parse_layers_block('', body)
        assert [p.kind for p in block.parts] == ['image', 'fence', 'fence']
        assert [p.lang for p in block.parts[1:]] == ['svg', 'mermaid']
        assert block.warnings == []

    def test_defaults_to_origin(self):
        part = parse_layers_block('', '![a](photo.png)\n').parts[0]
        assert (part.x, part.y) == (0, 0)

    def test_empty_body_has_no_parts(self):
        assert parse_layers_block('', '\n').parts == []


class TestImage:
    def test_offsets_are_read_from_alt(self):
        part = parse_layers_block('', '![説明|x=40|y=20](photo.png)\n').parts[0]
        assert (part.x, part.y, part.alt, part.src) == (40, 20, '説明', 'photo.png')

    def test_alt_can_be_empty(self):
        part = parse_layers_block('', '![|x=40|y=20](photo.png)\n').parts[0]
        assert (part.x, part.y, part.alt) == (40, 20, '')

    def test_negative_offset(self):
        part = parse_layers_block('', '![|x=-30](photo.png)\n').parts[0]
        assert part.x == -30

    def test_size_attributes_are_ignored_with_a_warning(self):
        block = parse_layers_block('', '![a|width=50%](photo.png)\n')
        assert len(block.warnings) == 1 and 'width' in block.warnings[0]


class TestFence:
    def test_offsets_are_read_from_attrs(self):
        part = parse_layers_block('', '```mermaid {x=240 y=140}\ngraph LR; A-->B\n```\n').parts[0]
        assert (part.x, part.y, part.lang) == (240, 140, 'mermaid')
        assert part.code == 'graph LR; A-->B'
        assert part.attrs == ''

    def test_other_attrs_are_kept(self):
        part = parse_layers_block('', '```mermaid {x=10 trim=5}\ngraph LR; A-->B\n```\n').parts[0]
        assert part.x == 10 and part.attrs == '{trim=5}'

    def test_size_attributes_are_ignored_with_a_warning(self):
        block = parse_layers_block('', '```svg {height=8cm}\n<svg/>\n```\n')
        assert len(block.warnings) == 1 and 'height' in block.warnings[0]
        assert block.parts[0].attrs == ''


class TestHeaderAndWarnings:
    def test_header_is_the_alt_of_the_whole_stack(self):
        assert parse_layers_block('  画面の注釈つきスクリーンショット ', SVG).alt == '画面の注釈つきスクリーンショット'

    def test_missing_header_gives_empty_alt(self):
        assert parse_layers_block(None, SVG).alt == ''

    def test_invalid_offset_warns_and_uses_zero(self):
        block = parse_layers_block('', '![|x=10px](photo.png)\n')
        assert block.parts[0].x == 0
        assert len(block.warnings) == 1 and 'x' in block.warnings[0]

    def test_stray_text_warns_once(self):
        block = parse_layers_block('', f'前の文\n\n{SVG}\n\n後ろの文\n')
        assert len(block.parts) == 1
        assert sum('outside' in w for w in block.warnings) == 1
