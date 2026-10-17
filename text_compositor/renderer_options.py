"""レンダラー（`TypstRenderer`・`HtmlRenderer`）の、プラグインの有効・無効の設定を、configから読む（#488）。

PDFのビルド（project.py）と、Python API・HTML出力（api.py）の、両方が、同じ表（`PLUGIN_FLAGS`）から読む。
プラグインを足すときは、表に1行足し、`TypstRenderer.__init__`の引数にも同じ名前を足す
（名前が一致していることは、`tests/test_renderer_options.py`が調べる）。
"""
from collections import namedtuple

# config_key: `plugins:`のキー。 kwarg: `TypstRenderer`の引数名。 default: `plugins:`に書かれていないときの値。
#   *_auto_downloadは、システムに必要なツール（ブラウザ/Java/D2）が無い場合の振る舞いを制御する別軸のフラグ（#22）。
#   既定値が非対称なのは、ダウンロードされる実体のサイズが一桁違うため（Playwright自身のChromium: 約700MB
#   対 Eclipse Temurin JRE: 約49.7MB 対 D2 CLI: 約13MB）。
#   structurizr（既定false。#212）は、内部で使うstructurizr-cli一式が約99MBあり、他のプラグインと一桁違うため、
#   mermaidと同じ「重いので既定オフ」の位置づけ。diagram_trim（既定false。#315）は、resvg_py・Pillowという新しい
#   依存に頼るため、opt-in。
PluginFlag = namedtuple("PluginFlag", ["config_key", "kwarg", "default"])

PLUGIN_FLAGS = (
    PluginFlag("graphviz", "graphviz_enabled", True),
    PluginFlag("pikchr", "pikchr_enabled", True),                       # #213
    PluginFlag("cetz", "cetz_enabled", True),                           # #236
    PluginFlag("fletcher", "fletcher_enabled", True),
    PluginFlag("timeliney", "timeliney_enabled", True),                 # #294
    PluginFlag("finite", "finite_enabled", True),                       # #292
    PluginFlag("vega", "vega_enabled", True),                           # #211
    PluginFlag("chordpro", "chordpro_enabled", True),                   # #440
    PluginFlag("bizmodel", "bizmodel_enabled", True),                   # #447
    PluginFlag("wavedrom", "wavedrom_enabled", True),                   # #299
    PluginFlag("bytefield", "bytefield_enabled", True),                 # #300
    PluginFlag("mermaid", "mermaid_enabled", True),
    PluginFlag("mermaid_auto_download", "mermaid_auto_download", False),
    PluginFlag("plantuml", "plantuml_enabled", True),
    PluginFlag("plantuml_auto_download", "plantuml_auto_download", True),
    PluginFlag("d2", "d2_enabled", True),
    PluginFlag("d2_auto_download", "d2_auto_download", True),
    PluginFlag("structurizr", "structurizr_enabled", False),
    PluginFlag("structurizr_auto_download", "structurizr_auto_download", True),
    PluginFlag("diagram_trim", "diagram_trim_enabled", False),
)


def plugin_flags_from_config(config):
    """configの`plugins:`から、`TypstRenderer`の引数（{引数名: 真偽値}）を作る。書かれていないものは、既定値。"""
    plugins = config.get("plugins") or {}
    return {flag.kwarg: bool(plugins.get(flag.config_key, flag.default)) for flag in PLUGIN_FLAGS}
