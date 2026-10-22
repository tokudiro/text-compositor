"""図表プラグイン（#474。設計は`doc/plugin-architecture.md`）。

組み込みのプラグインの一覧は、ここに登録する。外部のパッケージが後から登録する仕組みは、設けない（設計書3.4）。
いまは、まだ何も登録していない（#533。載せ替えは、次のステップ）。
"""
from text_compositor.plugins.registry import Registry

registry = Registry()
