"""Pikchrのプラグイン（#474・#533の次。最初に載せ替える、最も小さい図種）。

描画の実体は、これまでどおり`pikchr_render`（Typstのパッケージ`kip`＝PikchrのWASMで、SVGにする）。
このファイルは、図種の登録情報と、バックエンド（`kip`）の窓口だけを持つ。
"""
from text_compositor import pikchr_render
from text_compositor.plugins.registry import OUTPUT_SVG, Backend, DiagramPlugin, RenderResult


class KipBackend(Backend):
    """Typstのパッケージ`kip`で、SVGにする。"""
    name = "kip"
    outputs = (OUTPUT_SVG,)

    def version(self):
        # 既存のキャッシュを無効にしないため、これまでの文字列を、そのまま使う（設計書3.6）。
        return pikchr_render.cache_version()

    def render(self, code, ctx, output):
        return RenderResult(output, svg=pikchr_render.render_svg(code))


PLUGIN = DiagramPlugin(
    name="pikchr",
    langs=("pikchr",),
    file_exts=(".pikchr",),
    label="Pikchr",
    backends={KipBackend.name: KipBackend()},
)
