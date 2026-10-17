"""プラグインの有効・無効の表（renderer_options.py、#488）のテスト。"""
import re

import pytest

import text_compositor.renderer_diagrams as diagrams_module
from text_compositor.config import _ALLOWED_PLUGINS_KEYS
from text_compositor.html_output import HtmlRenderer
from text_compositor.renderer import TypstRenderer
from text_compositor.renderer_options import PLUGIN_FLAGS, _FIGURE_FLAGS, apply_plugin_flags, plugin_flags_from_config


class TestApplyPluginFlags:
    @pytest.mark.parametrize("flag", PLUGIN_FLAGS, ids=lambda f: f.kwarg)
    def test_each_constructor_argument_reaches_its_attribute(self, flag):
        renderer = TypstRenderer(line_mapping="off", **{flag.kwarg: not flag.default})
        if flag.kwarg in _FIGURE_FLAGS:
            assert renderer.figure_enabled[_FIGURE_FLAGS[flag.kwarg]] is (not flag.default)
        else:
            assert getattr(renderer, flag.kwarg) is (not flag.default)

    def test_nothing_given_means_the_defaults(self):
        renderer = TypstRenderer(line_mapping="off")
        for flag in PLUGIN_FLAGS:
            if flag.kwarg in _FIGURE_FLAGS:
                assert renderer.figure_enabled[_FIGURE_FLAGS[flag.kwarg]] is flag.default
            else:
                assert getattr(renderer, flag.kwarg) is flag.default

    def test_the_other_figure_flags_keep_their_defaults(self):
        renderer = TypstRenderer(line_mapping="off", cetz_enabled=False)
        assert renderer.figure_enabled == {"cetz": False, "fletcher": True, "timeliney": True, "finite": True}

    def test_an_unknown_argument_is_a_type_error(self):
        with pytest.raises(TypeError, match="mermaid_enabld"):
            TypstRenderer(line_mapping="off", mermaid_enabld=False)
        with pytest.raises(TypeError):
            apply_plugin_flags(object(), {"nope": True})

    def test_html_renderer_passes_the_flags_through(self):
        renderer = HtmlRenderer(None, structurizr_enabled=True, vega_enabled=False)
        assert renderer.structurizr_enabled is True and renderer.vega_enabled is False

    def test_only_base_dir_and_typst_root_are_positional(self, tmp_path):
        TypstRenderer(str(tmp_path), str(tmp_path), line_mapping="off")
        with pytest.raises(TypeError):
            TypstRenderer(str(tmp_path), str(tmp_path), True)

    def test_every_warn_once_flag_the_diagram_mixin_reads_is_initialized(self):
        # `_<名前>_disabled_warned`を、ミックスインが読むのに、初期化を忘れると、AttributeErrorになる
        source = open(diagrams_module.__file__, encoding="utf-8").read()
        names = set(re.findall(r"self\.(_\w+_disabled_warned)\b", source))
        assert names
        renderer = TypstRenderer(line_mapping="off")
        # bizmodelは、`getattr(self, ..., False)`で読むため、初期化されていなくてよい
        missing = {name for name in names if not hasattr(renderer, name) and "bizmodel" not in name}
        assert missing == set()


class TestTableMatchesTheRest:
    def test_the_config_keys_are_the_ones_config_py_allows_under_plugins(self):
        assert {flag.config_key for flag in PLUGIN_FLAGS} == _ALLOWED_PLUGINS_KEYS

    def test_no_duplicates(self):
        assert len({flag.config_key for flag in PLUGIN_FLAGS}) == len(PLUGIN_FLAGS)
        assert len({flag.kwarg for flag in PLUGIN_FLAGS}) == len(PLUGIN_FLAGS)


class TestPluginFlagsFromConfig:
    @pytest.mark.parametrize("config", [{}, {"plugins": None}, {"plugins": {}}])
    def test_nothing_written_gives_the_defaults(self, config):
        flags = plugin_flags_from_config(config)
        assert flags == {flag.kwarg: flag.default for flag in PLUGIN_FLAGS}
        # 既定でオフ・オンのもの（重い、または新しい依存を使うため）
        assert flags["structurizr_enabled"] is False and flags["diagram_trim_enabled"] is False
        assert flags["mermaid_auto_download"] is False
        assert flags["plantuml_auto_download"] is True and flags["d2_auto_download"] is True
        assert flags["graphviz_enabled"] is True and flags["mermaid_enabled"] is True

    @pytest.mark.parametrize("flag", PLUGIN_FLAGS, ids=lambda f: f.config_key)
    def test_each_config_key_sets_only_its_own_argument(self, flag):
        flags = plugin_flags_from_config({"plugins": {flag.config_key: not flag.default}})
        expected = {f.kwarg: f.default for f in PLUGIN_FLAGS}
        expected[flag.kwarg] = not flag.default
        assert flags == expected

    def test_values_are_converted_to_booleans(self):
        flags = plugin_flags_from_config({"plugins": {"graphviz": 0, "mermaid": "yes", "d2": None}})
        assert flags["graphviz_enabled"] is False
        assert flags["mermaid_enabled"] is True
        assert flags["d2_enabled"] is False

    def test_unknown_plugin_keys_are_ignored_here(self):
        # 未知のキーの検出は、config.pyのキー検証（#309）の仕事
        assert plugin_flags_from_config({"plugins": {"nope": False}}) == plugin_flags_from_config({})

    def test_the_result_builds_a_renderer(self):
        renderer = TypstRenderer(line_mapping="off", **plugin_flags_from_config({"plugins": {"vega": False, "cetz": False}}))
        assert renderer.vega_enabled is False
        assert renderer.figure_enabled["cetz"] is False
