"""図表プラグイン（#474。設計は`doc/plugin-architecture.md`）。

組み込みのプラグインの一覧は、ここに登録する。外部のパッケージが後から登録する仕組みは、設けない（設計書3.4）。
載せ替えが済んだ図種から、順に足していく（いまは、Pikchrだけ）。
"""
from text_compositor.plugins import pikchr
from text_compositor.plugins.registry import Registry

registry = Registry()
registry.register(pikchr.PLUGIN)
