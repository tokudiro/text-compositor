"""図のフェンスを、SVGファイルにする振り分け（PDF・HTML共通）。

もとは、HTML出力（`HtmlRenderer`）の中にあった。`layers`（#560）が、PDFでも、図をSVGファイルにして
原寸を読む必要があるため、`TypstRenderer`側のミックスインに移した。各図種のSVGを作るメソッドは、
`DiagramMixin`（renderer_diagrams.py）にある。
"""
from typing import Optional

from text_compositor import bytefield_render
from text_compositor import graphviz_render
from text_compositor import vega_render
from text_compositor import wavedrom_render
from text_compositor.plugins import registry as plugin_registry


class DiagramSvgMixin:
    """`TypstRenderer`に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する。"""

    def _diagram_svg_path(self, lang: str, code: str, trim=None, line=None, code_line=None) -> Optional[str]:
        """図のSVGファイルのパス。無効なプラグインの図は、Noneを返す（呼び出し側が、コード表示にする）。
        line: 描画に失敗したとき、診断に付ける、原稿でのフェンスの行。code_line: コードの1行目の、原稿での行。"""
        if lang == 'mermaid':
            return self._mermaid_svg_path(code, line, trim)
        if lang == 'plantuml':
            return self._plantuml_svg_path(code, line, trim)
        if lang == 'd2':
            return self._d2_svg_path(code, line, trim)
        if lang == 'structurizr':
            return self._structurizr_svg_path(code, line, trim)
        plugin = plugin_registry.by_lang(lang)      # 登録簿（plugins/）に載せ替えた図種（#474）
        if plugin is not None:
            if not getattr(self, f'{plugin.name}_enabled'):
                return None   # 無効なプラグイン: 警告なしで、コード表示（他の図と同じ）
            return self._plugin_svg_path(plugin, code, line, code_line)
        if lang == 'bizmodel':
            if not self.bizmodel_enabled:
                return None   # 無効なプラグイン: 警告なしで、コード表示（他の図と同じ）
            return self._bizmodel_svg_path(code, line, code_line)
        if lang in vega_render.LANGS:
            return self._vega_svg_path(lang, code, line)
        if lang in wavedrom_render.LANGS:
            return self._wavedrom_svg_path(code, line)
        if lang in bytefield_render.LANGS:
            return self._bytefield_svg_path(code, line)
        if lang in ('cetz', 'fletcher', 'timeliney', 'finite'):
            if not self.figure_enabled[lang]:
                return None   # 無効なプラグイン: 警告なしで、コード表示（他の図と同じ）
            return self._figure_svg_path(lang, code, line, code_line)
        if lang in ('dot', 'graphviz'):
            if not self.graphviz_enabled:
                return None   # 無効なプラグイン: 警告なしで、コード表示（他の図と同じ）
            # diagraphで描けない記法は、エラーにならず、黙って見た目が変わるため、警告する（#264）
            self._warn_graphviz_limits(code, code_line, line)
            return self._graphviz_svg_path(code, line, code_line)
        return self._svg_fence_path(code)

    def _warn_graphviz_limits(self, code: str, code_line, line=None) -> None:
        """diagraphで描けない記法（record・図全体のlabel）を、警告にする。エラーにならず、黙って見た目が変わるため（#264）。
        キャッシュの有無にかかわらず、変換のたびに出す。"""
        for kind, dot_line in graphviz_render.find_unsupported(code):
            at = code_line + dot_line - 1 if code_line else line
            at = at if at is not None else self._block_line
            if kind == 'record':
                self._warn_here("Graphviz: shape=record/Mrecord is not supported by diagraph; the record syntax is drawn as plain text "
                                "in a single box. Use an HTML-like label or separate nodes instead.", line=at)
            else:
                self._warn_here("Graphviz: the graph-level label (and labelloc) is not drawn by diagraph. "
                                "Put the title in the Markdown text, or use a cluster label.", line=at)
