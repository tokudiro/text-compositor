"""`::: layers`ブロックのHTML出力（#560）。

重ねる部品を、`<image>`を並べた1つのインラインSVGにする。`viewBox`を「全部品を包む長方形」にすると、
はみ出した部分や負のずれも含めた全体が、ブラウザの同じ比率の縮小で収まる。`<image>`で読むファイルは
画像として扱われ、中のスクリプトは動かない（`<img>`と同じ。外部への通信もしない）。
"""
import os
import re

from markdown_it.common.utils import escapeHtml

from text_compositor.image_size import natural_size
from text_compositor.layers import parse_layers_block

_URL_SCHEME_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)')


def _num(value: float) -> str:
    return f'{value:g}'


class LayersHtmlMixin:
    """`HtmlRenderer`に取り込まれるミックスイン。状態（`self`の属性）は、`HtmlRenderer`と共有する。"""

    def _layers_html(self, header, body: str) -> str:
        block = parse_layers_block(header or '', body)
        for message in block.warnings:
            self._warn_line(message)
        placed = [p for p in (self._place_layer(part) for part in block.parts) if p]
        if not placed:
            self._warn_line(f"The layers block in {self.current_file} has no part that can be drawn; nothing is shown.")
            return ''
        left = min(x for _, x, _, _, _ in placed)
        top = min(y for _, _, y, _, _ in placed)
        right = max(x + w for _, x, _, w, _ in placed)
        bottom = max(y + h for _, _, y, _, h in placed)
        width, height = right - left, bottom - top
        images = ''.join(
            f'<image href="{escapeHtml(href)}" x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}"/>\n'
            for href, x, y, w, h in placed)
        # 見出し行の文字列が、重ね全体の代替テキスト。無ければ、装飾として読み上げから外す（画像のalt=""と同じ）
        label = f' role="img" aria-label="{escapeHtml(block.alt)}"' if block.alt else ' aria-hidden="true"'
        return (f'<div class="diagram diagram-layers"><svg class="layers" xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{_num(left)} {_num(top)} {_num(width)} {_num(height)}" '
                f'width="{_num(width)}" height="{_num(height)}"{label} '
                f'style="max-width:100%;height:auto">\n{images}</svg></div>\n')

    def _place_layer(self, part):
        """部品1つを、(href, x, y, 幅, 高さ)にする。置けないときは、警告を出して、Noneを返す。"""
        if part.kind == 'fence':
            path = self._diagram_svg_path(part.lang, part.code, self._parse_trim_attr(part.attrs or None),
                                          self._block_line)
            if path is None:
                self._warn_line(f"A {part.lang} fence in a layers block is not available (plugin disabled); skipped.")
                return None
            href = self._url_for(path)
        else:
            if _URL_SCHEME_RE.match(part.src):
                # 外部の画像は、読み込まない（2章の方針）。`data:`の画像は、原寸を読めないため、置けない
                if not part.src.startswith('data:'):
                    self._asset_url(part.src)   # 既定の警告（外部の画像は、読み込まない）を出す
                else:
                    self._warn_line("A data: image in a layers block is not supported; skipped.")
                return None
            href = self._asset_url(part.src)
            path = self._local_asset_path(part.src)
            if href is None or not os.path.exists(path):
                return None   # 画像が無い警告は、_asset_urlが出している
        size = natural_size(path)
        if size is None:
            self._warn_line(f"Cannot read the size of {os.path.basename(path)} in a layers block "
                            "(PNG, JPEG, GIF and SVG are supported); skipped.")
            return None
        return href, part.x, part.y, size[0], size[1]
