"""プラグインの有効・無効の表（renderer_options.py、#488）のテスト。"""
import inspect

import pytest

from text_compositor.config import _ALLOWED_PLUGINS_KEYS
from text_compositor.renderer import TypstRenderer
from text_compositor.renderer_options import PLUGIN_FLAGS, plugin_flags_from_config

# `*_enabled`でも、プラグインではない（`document.glossary`で決まる）引数
NOT_PLUGINS = {"glossary_enabled"}


def _init_parameters():
    return inspect.signature(TypstRenderer.__init__).parameters


class TestTableMatchesTheRest:
    def test_every_flag_is_a_constructor_argument_with_the_same_default(self):
        params = _init_parameters()
        for flag in PLUGIN_FLAGS:
            assert flag.kwarg in params, flag.kwarg
            assert params[flag.kwarg].default is flag.default, flag.kwarg

    def test_every_plugin_argument_of_the_constructor_is_in_the_table(self):
        # 表に書き忘れたプラグインが、configから渡されず、黙って既定値のままになることを防ぐ
        plugin_params = {name for name in _init_parameters() if name.endswith(("_enabled", "_auto_download")) and name not in NOT_PLUGINS}
        assert plugin_params == {flag.kwarg for flag in PLUGIN_FLAGS}

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
