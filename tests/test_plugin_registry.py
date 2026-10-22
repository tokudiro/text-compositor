"""図表プラグインの契約とレジストリ（#533）の、単体テスト。まだ、既存のコードは、これを使わない。"""
import pytest

from text_compositor.plugins.registry import (
    AUTO, OUTPUT_SVG, OUTPUT_TYPST, Backend, BackendSelectionError, DiagramPlugin, Option, PluginRegistrationError,
    RenderResult, Registry, Support)


class Fake(Backend):
    """テスト用のバックエンド。`unsupported`に含まれる語がコードにあれば、対応しない。"""

    def __init__(self, name, outputs=(OUTPUT_SVG,), unsupported=()):
        self.name = name
        self.outputs = outputs
        self._unsupported = unsupported

    def version(self):
        return f"{self.name}-1"

    def supports(self, code, output):
        for word in self._unsupported:
            if word in code:
                return Support.UNSUPPORTED(f"uses {word}")
        return super().supports(code, output)

    def render(self, code, ctx, output):
        return RenderResult(output, svg=f"<svg>{self.name}</svg>")


def plugin(name="demo", backends=None, **kwargs):
    if backends is None:
        backends = [Fake("native"), Fake("java")]
    if isinstance(backends, dict):      # 空の辞書など、そのまま渡したいとき
        backends = list(backends.values())
    defaults = dict(name=name, langs=(name,), file_exts=(f".{name}",), label=name.title(), backends={b.name: b for b in backends})
    defaults.update(kwargs)
    return DiagramPlugin(**defaults)


class TestSupportAndResult:
    def test_support_ok_and_unsupported(self):
        assert Support.OK.ok and Support.OK.reason == ""
        unsupported = Support.UNSUPPORTED("needs skinparam")
        assert not unsupported.ok and unsupported.reason == "needs skinparam"

    def test_a_result_must_carry_the_requested_output(self):
        assert RenderResult(OUTPUT_SVG, svg="<svg/>").svg == "<svg/>"
        assert RenderResult(OUTPUT_TYPST, typst="#box[]").typst == "#box[]"
        with pytest.raises(ValueError):
            RenderResult(OUTPUT_SVG)
        with pytest.raises(ValueError):
            RenderResult(OUTPUT_TYPST, svg="<svg/>")
        with pytest.raises(ValueError):
            RenderResult("png", svg="x")


class TestBackendDefaults:
    def test_supports_follows_the_declared_outputs(self):
        backend = Fake("native")
        assert backend.supports("a", OUTPUT_SVG).ok
        result = backend.supports("a", OUTPUT_TYPST)
        assert not result.ok and "typst" in result.reason

    def test_check_env_and_prefetch_default_to_nothing(self):
        backend = Backend()
        assert backend.check_env() == []
        assert backend.prefetch(["a"], None) is None

    def test_version_and_render_must_be_written_by_the_subclass(self):
        with pytest.raises(NotImplementedError):
            Backend().version()
        with pytest.raises(NotImplementedError):
            Backend().render("a", None, OUTPUT_SVG)


class TestPluginValidation:
    def test_a_valid_plugin(self):
        p = plugin()
        assert p.default_backend == AUTO and p.default_output == OUTPUT_SVG and p.default_enabled

    @pytest.mark.parametrize("kwargs, message", [
        ({"name": ""}, "needs a name"),
        ({"file_exts": ("puml",)}, "start with '.'"),
        ({"file_exts": (".PUML",)}, "lowercase"),
        ({"langs": ("PlantUML",)}, "lowercase"),
        ({"backends": {}}, "at least one backend"),
        ({"default_output": "png"}, "default_output"),
        ({"default_backend": "missing"}, "default_backend"),
    ])
    def test_invalid_definitions_are_refused(self, kwargs, message):
        with pytest.raises(PluginRegistrationError, match=message):
            plugin(**kwargs)

    def test_every_backend_must_be_able_to_produce_svg(self):
        """HTML・Viewer・単体の図は、常にSVGを使うため（設計書3.2.1）。"""
        with pytest.raises(PluginRegistrationError, match="'svg'"):
            plugin(backends=[Fake("typst_only", outputs=(OUTPUT_TYPST,))])

    def test_a_backend_registered_under_another_name_is_refused(self):
        with pytest.raises(PluginRegistrationError, match="is named"):
            DiagramPlugin(name="d", langs=("d",), file_exts=(".d",), label="D", backends={"x": Fake("y")})

    def test_auto_cannot_be_a_backend_name(self):
        with pytest.raises(PluginRegistrationError, match="reserved"):
            plugin(backends=[Fake(AUTO)])

    def test_unknown_output_declared_by_a_backend(self):
        with pytest.raises(PluginRegistrationError, match="unknown output"):
            plugin(backends=[Fake("x", outputs=(OUTPUT_SVG, "png"))])


class TestRegistry:
    def make(self):
        registry = Registry()
        registry.register(plugin("alpha", options=(Option("alpha_auto_download", False),), default_enabled=False))
        registry.register(plugin("beta", langs=("beta", "b"), file_exts=(".beta", ".bta")))
        return registry

    def test_lookup_by_name_language_and_extension(self):
        registry = self.make()
        assert registry.get("alpha").name == "alpha" and registry.get("zzz") is None
        assert registry.by_lang("b").name == "beta"
        assert registry.by_lang("BETA").name == "beta"      # フェンスの言語は、大文字・小文字を区別しない
        assert registry.by_lang("unknown") is None
        assert registry.by_ext(".BTA").name == "beta"
        assert [p.name for p in registry.plugins()] == ["alpha", "beta"]

    def test_file_exts_map_to_plugin_names(self):
        assert self.make().file_exts() == {".alpha": "alpha", ".beta": "beta", ".bta": "beta"}

    def test_duplicates_are_refused(self):
        registry = self.make()
        with pytest.raises(PluginRegistrationError, match="already registered"):
            registry.register(plugin("alpha", langs=("x",), file_exts=(".x",)))
        with pytest.raises(PluginRegistrationError, match="Fence language"):
            registry.register(plugin("gamma", langs=("b",), file_exts=(".gamma",)))
        with pytest.raises(PluginRegistrationError, match="File extension"):
            registry.register(plugin("delta", langs=("delta",), file_exts=(".bta",)))
        assert [p.name for p in registry.plugins()] == ["alpha", "beta"]     # 失敗した登録は、何も残さない

    def test_allowed_plugin_keys(self):
        registry = self.make()
        assert registry.allowed_plugin_keys() == {"alpha", "alpha_auto_download", "beta"}
        assert registry.allowed_plugin_keys(with_selection=True) == {
            "alpha", "alpha_auto_download", "alpha_backend", "alpha_output", "beta", "beta_backend", "beta_output"}

    def test_resolve_enabled_uses_the_default_when_unset(self):
        registry = self.make()
        assert registry.resolve_enabled({}) == {"alpha": False, "beta": True}
        assert registry.resolve_enabled(None) == {"alpha": False, "beta": True}
        assert registry.resolve_enabled({"alpha": True, "beta": False}) == {"alpha": True, "beta": False}


class TestOutputSelection:
    def test_auto_resolves_to_the_default_output(self):
        p = plugin(default_output=OUTPUT_TYPST)
        assert Registry().resolve_output(p, {}) == OUTPUT_TYPST
        assert Registry().resolve_output(p, {"demo_output": "svg"}) == OUTPUT_SVG

    def test_html_and_other_targets_always_use_svg(self):
        """`typst`が効くのは、PDF出力だけ（設計書3.2.1）。"""
        p = plugin(default_output=OUTPUT_TYPST)
        assert Registry().resolve_output(p, {"demo_output": "typst"}, target="html") == OUTPUT_SVG

    def test_an_invalid_value_is_an_error(self):
        with pytest.raises(BackendSelectionError, match="demo_output"):
            Registry().resolve_output(plugin(), {"demo_output": "png"})


class TestBackendSelection:
    def test_auto_picks_the_first_backend_that_supports_the_code(self):
        p = plugin(backends=[Fake("native", unsupported=("skinparam",)), Fake("java")])
        registry = Registry()
        assert registry.resolve_backend(p, "a -> b", OUTPUT_SVG, {}).name == "native"
        assert registry.resolve_backend(p, "skinparam x", OUTPUT_SVG, {}).name == "java"

    def test_choice_depends_only_on_the_input_not_on_a_failed_render(self):
        """同じ入力なら、同じバックエンド（決定論。設計書3.3）。"""
        p = plugin(backends=[Fake("native", unsupported=("skinparam",)), Fake("java")])
        first = Registry().resolve_backend(p, "skinparam x", OUTPUT_SVG, {})
        second = Registry().resolve_backend(p, "skinparam x", OUTPUT_SVG, {})
        assert first is second

    def test_auto_fails_with_every_reason_when_nothing_supports_the_code(self):
        p = plugin(backends=[Fake("native", unsupported=("x",)), Fake("java", unsupported=("x",))])
        with pytest.raises(BackendSelectionError, match="native: uses x; java: uses x"):
            Registry().resolve_backend(p, "x", OUTPUT_SVG, {})

    def test_an_explicit_backend_is_used_alone(self):
        p = plugin(backends=[Fake("native"), Fake("java")])
        assert Registry().resolve_backend(p, "a", OUTPUT_SVG, {"demo_backend": "java"}).name == "java"

    def test_an_explicit_backend_that_cannot_render_is_an_error_not_a_fallback(self):
        """明示したのに、別のバックエンドへ戻すと、設定が、黙って無視される（Fail-fast）。"""
        p = plugin(backends=[Fake("native", unsupported=("skinparam",)), Fake("java")])
        with pytest.raises(BackendSelectionError, match="'native' backend cannot render"):
            Registry().resolve_backend(p, "skinparam x", OUTPUT_SVG, {"demo_backend": "native"})

    def test_an_unknown_backend_name_lists_the_choices(self):
        with pytest.raises(BackendSelectionError, match="unknown backend 'nope'.*native, java"):
            Registry().resolve_backend(plugin(), "a", OUTPUT_SVG, {"demo_backend": "nope"})

    def test_the_output_is_part_of_the_decision(self):
        p = plugin(backends=[Fake("native"), Fake("typst", outputs=(OUTPUT_SVG, OUTPUT_TYPST))])
        assert Registry().resolve_backend(p, "a", OUTPUT_TYPST, {}).name == "typst"

    def test_the_default_backend_of_the_plugin_is_used_when_unset(self):
        p = plugin(default_backend="java")
        assert Registry().resolve_backend(p, "a", OUTPUT_SVG, {}).name == "java"


def test_the_package_registry_holds_the_plugins_moved_over_so_far():
    """載せ替えが済んだ図種だけが、登録簿にある。足すたびに、この一覧を更新する（#474）。"""
    from text_compositor.plugins import registry
    assert [p.name for p in registry.plugins()] == ["pikchr"]
