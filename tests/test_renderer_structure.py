"""renderer.pyの分割（#225）が、崩れないための番人。"""
import os
import re

import text_compositor.renderer as renderer
from text_compositor.html_output import HtmlRenderer
from text_compositor.renderer import TypstRenderer

PACKAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "text_compositor")
MIXIN_MODULES = ["renderer_diagrams", "renderer_inline", "renderer_layout", "renderer_tables", "renderer_tokens"]
MAX_RENDERER_LINES = 500   # #225の完了条件（目安）


def read(module):
    with open(os.path.join(PACKAGE_DIR, f"{module}.py"), encoding="utf-8") as f:
        return f.read()


def test_renderer_py_stays_small_enough_to_be_one_responsibility():
    assert len(read("renderer").splitlines()) <= MAX_RENDERER_LINES


def test_the_mixins_do_not_import_renderer_py():
    """状態は、TypstRendererが持つ。ミックスインが、renderer.pyを読むと、循環になる。"""
    for module in MIXIN_MODULES:
        source = read(module)
        assert not re.search(r"^\s*(from text_compositor\.renderer import|import text_compositor\.renderer\b|from text_compositor import renderer\b)",
                             source, re.MULTILINE), module


def test_typst_renderer_is_built_from_the_mixins():
    names = [cls.__name__ for cls in TypstRenderer.__mro__]
    for name in ("DiagramMixin", "InlineMixin", "LayoutMixin", "TableMixin", "TokenMixin"):
        assert name in names
    assert issubclass(HtmlRenderer, TypstRenderer)


def test_the_public_names_are_still_reachable_from_renderer_py():
    assert callable(TypstRenderer.render_chapter) and callable(TypstRenderer.render)
    assert callable(renderer._diagram_cache_key)   # テスト・他のモジュールが、ここから読む


def test_each_method_is_defined_in_exactly_one_module():
    """同じメソッドが、複数のミックスインに重複すると、MROの順で、片方が黙って隠れる。"""
    owners = {}
    for cls in TypstRenderer.__mro__:
        if cls is object:
            continue
        for name, value in vars(cls).items():
            if callable(value) or isinstance(value, (staticmethod, classmethod)):
                owners.setdefault(name, []).append(cls.__name__)
    duplicated = {name: classes for name, classes in owners.items() if len(classes) > 1 and not name.startswith("__")}
    assert duplicated == {}
