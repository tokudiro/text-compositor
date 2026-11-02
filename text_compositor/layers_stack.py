"""`::: layers`ブロックの、部品の置き場所と全体の大きさ（PDF・HTML共通。#560）。

部品を、ファイルの原寸で原点（左上）に置き、`x=`・`y=`でずらす。全体の大きさは、全部品を包む最小の長方形で、
はみ出した部分も、負のずれも含む。出力ごとの違い（画像ファイルの探し方）だけを、`_layer_image_path`に残す。
"""
import os
from dataclasses import dataclass
from typing import List, Optional

from text_compositor.image_size import natural_size
from text_compositor.layers import LayerPart, parse_layers_block


@dataclass
class PlacedLayer:
    """置き場所が決まった部品。`path`は画像ファイル（図は、SVGにしたキャッシュ）。単位はピクセル。"""
    path: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class LayersStack:
    alt: str                       # 重ね全体の代替テキスト（空なら、装飾）
    parts: List[PlacedLayer]       # 先に書いた順（下から上）
    left: float                    # 全部品を包む長方形
    top: float
    width: float
    height: float


class LayersStackMixin:
    """`TypstRenderer`に取り込まれるミックスイン。状態（`self`の属性）は、`TypstRenderer`と共有する。"""

    # 画像の部品のファイルのパス（`_layer_image_path(part)`。置けないときは、警告を出して、Noneを返す）は、
    # 出力ごとに探し方が違うため、PDF（layers_pdf.py）とHTML（layers_html.py）が、それぞれ実装する。
    # 同じ名前のメソッドを、ミックスインの間で重ねない（test_renderer_structure.py）。HtmlRendererだけが、
    # 先頭のLayersHtmlMixinで、PDF側の実装を上書きする。

    def _layers_stack(self, header, body: str) -> Optional[LayersStack]:
        """ブロックを解析し、部品を置く。1つも置けなければ、警告を出して、Noneを返す。"""
        block = parse_layers_block(header or '', body)
        for message in block.warnings:
            self._warn_here(message, line=self._block_line)
        placed = [p for p in (self._place_layer(part) for part in block.parts) if p]
        if not placed:
            self._warn_here(f"The layers block in {self.current_file} has no part that can be drawn; nothing is shown.",
                            line=self._block_line)
            return None
        left = min(p.x for p in placed)
        top = min(p.y for p in placed)
        right = max(p.x + p.width for p in placed)
        bottom = max(p.y + p.height for p in placed)
        return LayersStack(block.alt, placed, left, top, right - left, bottom - top)

    def _place_layer(self, part: LayerPart) -> Optional[PlacedLayer]:
        if part.kind == 'fence':
            path = self._diagram_svg_path(part.lang, part.code, self._parse_trim_attr(part.attrs or None),
                                          self._block_line)
            if path is None:
                self._warn_here(f"A {part.lang} fence in a layers block is not available (plugin disabled); skipped.",
                                line=self._block_line)
                return None
        else:
            path = self._layer_image_path(part)
            if path is None:
                return None
        size = natural_size(path)
        if size is None:
            self._warn_here(f"Cannot read the size of {os.path.basename(path)} in a layers block "
                            "(PNG, JPEG, GIF and SVG are supported); skipped.", line=self._block_line)
            return None
        return PlacedLayer(path, part.x, part.y, size[0], size[1])
