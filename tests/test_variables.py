"""{{KEY}}プレースホルダの置換機構（#72）のリグレッションテスト。"""
import pytest

from text_compositor.config import _resolve_variables
from text_compositor.renderer import TypstRenderer


def render(md, variables, filepath="ch.md"):
    renderer = TypstRenderer(line_mapping="off", variables=variables)
    return renderer.render_chapter(md, filepath=filepath)


class TestSubstitution:
    def test_replaces_in_body(self):
        out = render("Version {{VERSION}} released.\n", {"VERSION": "1.2.0"})
        assert "Version 1.2.0 released." in out
        assert "{{" not in out

    def test_replaces_multiple_and_repeated(self):
        out = render("{{A}}-{{B}}-{{A}}\n", {"A": "x", "B": "y"})
        assert "x-y-x" in out

    def test_replaces_in_heading_and_table_and_code_fence(self):
        md = "# Rev {{V}}\n\n| a |\n|---|\n| {{V}} |\n\n```\npip install pkg=={{V}}\n```\n"
        out = render(md, {"V": "9.9"})
        assert "{{" not in out
        assert out.count("9.9") == 3

    def test_disabled_when_variables_is_none(self):
        # variablesを持たない既存プロジェクトでは、{{...}}に一切触れない（未定義エラーにもならない）
        assert render("keep {{VERSION}}\n", None) == "keep {{VERSION}}\n\n"

    def test_value_is_not_reinterpreted_as_placeholder(self):
        # 置換は1回だけ。値の中の{{B}}を再帰的に展開しない
        assert render("{{A}}\n", {"A": "{{B}}", "B": "boom"}) == "{{B}}\n\n"

    def test_only_markdown_chapters_are_substituted(self):
        out = render("a,b\n{{X}},2\n", {"X": "1"}, filepath="data.csv")
        assert "[{{X}}]" in out


class TestNonPlaceholders:
    def test_spaced_braces_are_left_alone(self):
        # Vue/Jinja風の {{ message }} は識別子の形ではないため対象外（未定義エラーにもならない）
        assert render("Use {{ message }} here\n", {"VERSION": "1"}) == "Use {{ message }} here\n\n"

    def test_escaped_placeholder_is_output_literally(self):
        # 先頭の\は取り除かれ、{{VERSION}}が置換されずにそのまま出力される
        assert render("Write \\{{VERSION}} now\n", {"VERSION": "1.2.0"}) == "Write {{VERSION}} now\n\n"


class TestUndefined:
    def test_undefined_key_is_fatal_and_reports_location(self, capsys):
        with pytest.raises(SystemExit) as e:
            render("line1\nline2 {{VERSON}}\n", {"VERSION": "1"}, filepath="doc/a.md")
        assert e.value.code == 1
        out = capsys.readouterr().out
        assert "doc/a.md:2" in out
        assert "VERSON" in out

    def test_all_undefined_keys_in_a_file_are_reported(self, capsys):
        with pytest.raises(SystemExit):
            render("{{X}}\n\n{{Y}}\n", {}, filepath="a.md")
        out = capsys.readouterr().out
        assert "a.md:1" in out and "a.md:3" in out

    def test_empty_variables_still_rejects_undefined(self):
        with pytest.raises(SystemExit):
            render("{{X}}\n", {})


class TestResolveVariables:
    def test_absent_key_disables_feature(self):
        assert _resolve_variables({}) is None

    def test_scalars_are_stringified(self):
        assert _resolve_variables({"variables": {"A": "1.2.0", "B": 3, "C": True}}) == {
            "A": "1.2.0", "B": "3", "C": "True"}

    def test_empty_mapping_is_enabled_but_empty(self):
        assert _resolve_variables({"variables": {}}) == {}

    def test_env_value(self, monkeypatch):
        monkeypatch.setenv("TC_TEST_BUILD", "123")
        assert _resolve_variables({"variables": {"BUILD": {"env": "TC_TEST_BUILD"}}}) == {"BUILD": "123"}

    def test_env_missing_uses_default(self, monkeypatch):
        monkeypatch.delenv("TC_TEST_MISSING", raising=False)
        cfg = {"variables": {"CH": {"env": "TC_TEST_MISSING", "default": "stable"}}}
        assert _resolve_variables(cfg) == {"CH": "stable"}

    def test_env_missing_without_default_is_fatal(self, monkeypatch, capsys):
        monkeypatch.delenv("TC_TEST_MISSING", raising=False)
        with pytest.raises(SystemExit):
            _resolve_variables({"variables": {"CH": {"env": "TC_TEST_MISSING"}}})
        assert "TC_TEST_MISSING" in capsys.readouterr().out

    def test_env_set_but_empty_is_used_not_default(self, monkeypatch):
        monkeypatch.setenv("TC_TEST_EMPTY", "")
        cfg = {"variables": {"X": {"env": "TC_TEST_EMPTY", "default": "d"}}}
        assert _resolve_variables(cfg) == {"X": ""}

    @pytest.mark.parametrize("bad", [
        {"variables": ["a"]},
        {"variables": {"1BAD": "x"}},
        {"variables": {"has space": "x"}},
        {"variables": {"A": {"cmd": "git describe"}}},
        {"variables": {"A": {"env": "X", "default": "d", "extra": 1}}},
        {"variables": {"A": ["x"]}},
        {"variables": {"A": "line1\nline2"}},
    ])
    def test_invalid_definitions_are_fatal(self, bad):
        with pytest.raises(SystemExit) as e:
            _resolve_variables(bad)
        assert e.value.code == 1
