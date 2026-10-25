"""フローチャートのプラグイン（#536。設計は`doc/flowchart-notation.md`）。

JIS X 0121に準じた独自の記法`flowchart`を、自作の変換器でSVGにする。ほかの描き手がないので、バックエンドは`native`の1つだけで、
従来のブラウザ版へ戻す分岐（フォールバック）はない。Mermaidの`flowchart`（`mermaid`フェンス）とは別の図種である。
"""
from text_compositor import flowchart_notation, flowchart_render
from text_compositor.plugins.registry import OUTPUT_SVG, Backend, DiagramPlugin, RenderResult


class NativeBackend(Backend):
    """自作の変換器（解析→`dot`の配置→自作のSVG）で、SVGにする。"""
    name = "native"
    outputs = (OUTPUT_SVG,)

    def version(self):
        # 変換器・diagraph-layout・Typst・フォントのどれかが変われば、別のキャッシュキーになる（設計書4章）
        return flowchart_render.cache_version()

    def render(self, code, ctx, output):
        return RenderResult(output, svg=flowchart_notation.render_svg(code))


PLUGIN = DiagramPlugin(
    name="flowchart",
    langs=("flowchart",),
    file_exts=(".flow",),
    label="Flowchart",
    backends={NativeBackend.name: NativeBackend()},
)
