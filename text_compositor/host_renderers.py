"""図の描画を、呼び出し元（ViewerのElectron）に任せるためのフック（#207）。

レンダラー（renderer.py）は、値ではなくこのモジュールの属性を毎回参照する（設定後の変更を反映するため）。"""

# Mermaidの描画を、呼び出し元（Viewerの、Electron）に任せる口（#207）。設定されていれば、Playwrightと
# システムのブラウザを使わず、`renderer(diagram_id, code, js_path)`が、SVGの文字列を返す（失敗は、例外）。
# 常駐ワーカーが、環境変数`TEXT_COMPOSITOR_MERMAID_HOST=1`のときに、標準入出力で、依頼する形で設定する（worker.py）。
# Graphvizは、この仕組みを使わない。Typstのdiagraphで描く（#264）。
_mermaid_host_renderer = None


def set_mermaid_host_renderer(renderer):
    """Mermaidの描画を任せる関数を設定する（`None`で解除）。"""
    global _mermaid_host_renderer
    _mermaid_host_renderer = renderer


# Vega・Vega-Liteの描画を、呼び出し元に任せる口（#351）。設定されていれば、`renderer(diagram_id, lang, spec, script, js)`が、
# SVGの文字列を返す（失敗は、例外）。langは`vega-lite`か`vega`、specは検査済みの仕様（dict）、scriptは、ブラウザで実行する
# 描画スクリプト（vega_render.RENDER_SCRIPT。呼び出し元と、二重に持たないため、こちらから渡す）、jsは、
# `{"vega": vega.min.jsのパス, "vega_lite": vega-lite.min.jsのパス}`。設定の仕方は、Mermaidと同じ（worker.py）。
_vega_host_renderer = None


def set_vega_host_renderer(renderer):
    """Vega・Vega-Liteの描画を任せる関数を設定する（`None`で解除）。"""
    global _vega_host_renderer
    _vega_host_renderer = renderer
