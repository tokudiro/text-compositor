"""図表プラグイン（#474。設計は`doc/plugin-architecture.md`）。

組み込みのプラグインの一覧は、ここに登録する。外部のパッケージが後から登録する仕組みは、設けない（設計書3.4）。
載せ替えが済んだ図種から、順に足していく（いまは、Pikchrと、新しい記法のフローチャート）。
"""
from text_compositor.plugins import flowchart, pikchr
from text_compositor.plugins.registry import Registry

registry = Registry()
registry.register(pikchr.PLUGIN)
registry.register(flowchart.PLUGIN)
