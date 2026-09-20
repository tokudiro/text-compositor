"""論文形式テンプレート`paper`と`document.abstract`（#64）のリグレッションテスト。"""
import os
import re

import pytest

import text_compositor.build as build
from text_compositor.config import resolve_template_path
from text_compositor.document import _abstract_typst_arg, _build_document_preamble, _resolve_abstract

TOOL_DIR = os.path.dirname(os.path.abspath(build.__file__))


def read_template(name):
    with open(os.path.join(TOOL_DIR, "templates", name), encoding="utf-8") as f:
        return f.read()


class TestResolveAbstract:
    def test_unset_returns_none(self):
        assert _resolve_abstract({}) is None

    def test_blank_returns_none(self):
        assert _resolve_abstract({"abstract": "  \n "}) is None

    def test_string_is_stripped(self):
        assert _resolve_abstract({"abstract": "\n本文。\n"}) == "本文。"

    @pytest.mark.parametrize("value", [["a", "b"], {"k": "v"}, 3, True])
    def test_non_string_is_an_error(self, value, capsys):
        with pytest.raises(SystemExit) as e:
            _resolve_abstract({"abstract": value})
        assert e.value.code == 1
        assert "document.abstract must be a string" in capsys.readouterr().out


class TestAbstractTypstArg:
    def test_none_passes_no_argument(self):
        assert _abstract_typst_arg(None) == ""

    def test_multiline_is_one_line_literal_with_escaped_newline(self):
        arg = _abstract_typst_arg("一行目\n二行目")
        assert arg == '  abstract: "一行目\\n二行目",\n'

    def test_markup_characters_are_data_not_markup(self):
        arg = _abstract_typst_arg('#import "x" *bold*')
        assert '\\"x\\"' in arg and arg.startswith('  abstract: "')

    def test_crlf_is_normalized(self):
        assert "\\r" not in _abstract_typst_arg("a\r\nb") and "\r" not in _abstract_typst_arg("a\r\nb")


class TestPreamble:
    def preamble(self, doc):
        return _build_document_preamble({"document": doc}, "/t.typ", True, ".", ".")[0]

    def test_abstract_is_passed_only_when_set(self):
        assert "abstract:" not in self.preamble({"title": "T"})
        assert 'abstract: "概要",' in self.preamble({"title": "T", "abstract": "概要"})


class TestPaperTemplate:
    def test_bundled_name_resolves(self):
        path = resolve_template_path("paper", TOOL_DIR, ".")
        assert os.path.exists(path)

    def test_conf_accepts_every_required_argument(self):
        """build.pyが常に渡す引数を受け取れないと、そのテンプレートは常にビルドエラーになる。"""
        conf = read_template("paper.typ").split("#let conf(")[1].split(") = {")[0]
        for arg in ["title", "subtitle", "author", "date", "paper_size", "landscape", "graphviz",
                    "header", "footer", "paginate", "background", "logo"]:
            assert re.search(rf"^\s*{arg}:", conf, re.MULTILINE), arg

    @pytest.mark.parametrize("name", ["paper.typ", "template.typ", "slide.typ"])
    def test_every_bundled_template_accepts_abstract(self, name):
        conf = read_template(name).split("#let conf(")[1].split(") = {")[0]
        assert re.search(r"^\s*abstract:", conf, re.MULTILINE)

    def test_paper_exports_all_helpers_via_common(self):
        m = re.search(r'^#import "_common\.typ": (.+)$', read_template("paper.typ"), re.MULTILINE)
        names = {n.strip() for n in m.group(1).split(",")}
        assert {"fit-image", "render-graph", "callout", "render-header", "render-footer",
                "render-background"} <= names

    def test_paper_is_two_columns(self):
        assert "columns: 2" in read_template("paper.typ")
