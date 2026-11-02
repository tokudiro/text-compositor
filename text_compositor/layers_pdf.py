"""`::: layers`ブロックのPDF出力（Typst。#560）。

部品を、`place`で、全部品を包む長方形の中に重ねる。全体は、1つの部品として、幅とページの高さの
上限に収まるよう、同じ比率で縮める（`scale`）。置き場所と全体の大きさは、HTMLと共通（layers_stack.py）。
"""
import os
import re
import sys
from typing import Optional

from text_compositor.layers import LayerPart
from text_compositor.typst_literal import escape_string_literal

# 縦に長い重ねが、ページからはみ出さないための高さの上限。Typstは、箱をページをまたいで割れない。
# templates/_common.typ の MAX_IMG_HEIGHT（通常の画像の上限）と同じ値。独自のテンプレートが、
# その定義を持たなくても動くよう、生成するコードに、値を直接書く。
LAYERS_MAX_HEIGHT = '12cm'
# 部品の大きさは、HTMLと同じ「ピクセル」で読む。Typstの長さ（pt）には、CSSと同じ1px=0.75ptで換算する。
_PT_PER_PX = 0.75

_URL_SCHEME_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)')


def _pt(pixels: float) -> str:
    return f'{pixels * _PT_PER_PX:g}pt'


class LayersPdfMixin:
    """`TypstRenderer`に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する。"""

    def _render_layers_block(self, header, body: str) -> str:
        stack = self._layers_stack(header, body)
        if stack is None:
            return ''
        places = []
        for index, p in enumerate(stack.parts):
            rel = "/" + os.path.relpath(p.path, self.typst_root).replace(os.sep, '/')
            # 代替テキストは、重ね全体で1つ。先頭の部品に付け、残りは、装飾として読み上げから外す
            alt = f'"{escape_string_literal(stack.alt)}"' if index == 0 and stack.alt else 'none'
            places.append(
                f'    place(top + left, dx: {_pt(p.x - stack.left)}, dy: {_pt(p.y - stack.top)}, '
                f'image("{escape_string_literal(rel)}", width: {_pt(p.width)}, height: {_pt(p.height)}, alt: {alt}))')
        width, height = _pt(stack.width), _pt(stack.height)
        return (
            '#align(center)[#layout(size => {\n'
            f'  let k = calc.min(1, size.width / {width}, {LAYERS_MAX_HEIGHT} / {height})\n'
            f'  scale(k * 100%, reflow: true, origin: top + left, box(width: {width}, height: {height}, {{\n'
            + '\n'.join(places) + '\n'
            '  }))\n'
            '})]\n\n'
        )

    def _layer_image_path(self, part: LayerPart) -> Optional[str]:
        src = part.src
        if src.startswith('data:'):
            return self._resolve_data_uri_asset(src)
        if _URL_SCHEME_RE.match(src):
            self._warn_here(f"External image in a layers block is not loaded: {src}; skipped.", line=self._block_line)
            return None
        if src.startswith('/'):
            path = os.path.normpath(os.path.join(self.typst_root, src.lstrip('/')))
        else:
            path = os.path.normpath(os.path.join(self.current_dir, src))
        # 仕様9章: 画像パス欠損はフォールバックせず即エラー (Fail-fast)
        if not os.path.exists(path):
            self._error_here(f"Image not found: {path} (referenced from {self.current_file})")
            sys.exit(1)
        return path
