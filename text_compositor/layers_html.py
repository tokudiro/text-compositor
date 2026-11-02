"""`::: layers`ブロックのHTML出力（#560）。

重ねる部品を、`<image>`を並べた1つのインラインSVGにする。`viewBox`を「全部品を包む長方形」にすると、
はみ出した部分や負のずれも含めた全体が、ブラウザの同じ比率の縮小で収まる。`<image>`で読むファイルは
画像として扱われ、中のスクリプトは動かない（`<img>`と同じ。外部への通信もしない）。
置き場所と全体の大きさは、PDFと共通（layers_stack.py）。
"""
import os
import re
from typing import Optional

from markdown_it.common.utils import escapeHtml

from text_compositor.layers import LayerPart

_URL_SCHEME_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)')


def _num(value: float) -> str:
    return f'{value:g}'


class LayersHtmlMixin:
    """`HtmlRenderer`に取り込まれるミックスイン。状態（`self`の属性）は、`HtmlRenderer`と共有する。"""

    def _layers_html(self, header, body: str) -> str:
        stack = self._layers_stack(header, body)
        if stack is None:
            return ''
        images = ''.join(
            f'<image href="{escapeHtml(self._url_for(p.path))}" x="{_num(p.x)}" y="{_num(p.y)}" '
            f'width="{_num(p.width)}" height="{_num(p.height)}"/>\n'
            for p in stack.parts)
        # 見出し行の文字列が、重ね全体の代替テキスト。無ければ、装飾として読み上げから外す（画像のalt=""と同じ）
        label = f' role="img" aria-label="{escapeHtml(stack.alt)}"' if stack.alt else ' aria-hidden="true"'
        return (f'<div class="diagram diagram-layers"><svg class="layers" xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{_num(stack.left)} {_num(stack.top)} {_num(stack.width)} {_num(stack.height)}" '
                f'width="{_num(stack.width)}" height="{_num(stack.height)}"{label} '
                f'style="max-width:100%;height:auto">\n{images}</svg></div>\n')

    def _layer_image_path(self, part: LayerPart) -> Optional[str]:
        if _URL_SCHEME_RE.match(part.src):
            # 外部の画像は、読み込まない（2章の方針）。`data:`の画像は、HTMLでは、まだ置けない
            if not part.src.startswith('data:'):
                self._asset_url(part.src)   # 既定の警告（外部の画像は、読み込まない）を出す
            else:
                self._warn_here("A data: image in a layers block is not supported in HTML output; skipped.",
                                line=self._block_line)
            return None
        url = self._asset_url(part.src)
        path = self._local_asset_path(part.src)
        if url is None or not os.path.exists(path):
            return None   # 画像が無い警告は、_asset_urlが出している
        return path
