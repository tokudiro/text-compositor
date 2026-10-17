"""lint（原稿の警告）のON/OFF（lints.py、#271）のテスト。"""
import pytest

from text_compositor import diagnostics, worker
from text_compositor.api import _single_markdown_config, render_html
from text_compositor.config import _validate_config_keys
from text_compositor.lints import LINTS, check_lint_overrides, lint_defaults, resolve_lints
from text_compositor.renderer import TypstRenderer
from tests.test_worker import FakeSession

PLAIN = {"mermaid": False, "plantuml": False, "d2": False, "graphviz": False}
BAD_BOLD = "これは**「重要」**です。\n"


def _bold_warnings(collected):
    return [w for w in collected.warnings if "Bold markup" in w.message]


class TestRegistry:
    def test_bold_is_registered_and_on_by_default(self):
        assert LINTS["bold"].default is True
        assert lint_defaults() == {"bold": True}

    def test_every_lint_has_a_label_and_a_description(self):
        # 設定画面（Obunzu）が、この一覧から項目を作る
        for lint in LINTS.values():
            assert lint.label and lint.description, lint.name


class TestCheckAndResolve:
    def test_valid_overrides_have_no_problem(self):
        assert check_lint_overrides({"bold": False}) is None
        assert check_lint_overrides({}) is None

    @pytest.mark.parametrize("value, message", [
        ("bold", "must be a mapping"),
        ([True], "must be a mapping"),
        ({"bld": False}, "unknown lint 'bld'"),
        ({"bold": "no"}, "must be true or false"),
        ({"bold": 0}, "must be true or false"),
        ({"bold": None}, "must be true or false"),
    ])
    def test_invalid_overrides_are_described(self, value, message):
        assert message in check_lint_overrides(value)

    def test_none_means_every_lint_on(self):
        assert resolve_lints(None) == {"bold": True}

    def test_override_is_merged_over_the_defaults(self):
        assert resolve_lints({"bold": False}) == {"bold": False}

    def test_invalid_value_stops_with_a_config_error(self, capsys):
        with pytest.raises(SystemExit):
            resolve_lints({"bold": "no"}, "lint")
        assert "lint: bold: must be true or false" in capsys.readouterr().out


class TestRenderer:
    def test_the_default_is_on(self, tmp_path):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as collected:
            renderer.render(BAD_BOLD, filepath=str(tmp_path / "doc.md"))
        assert len(_bold_warnings(collected)) == 1

    def test_off_gives_no_warning_and_the_text_is_unchanged(self, tmp_path):
        on, off = TypstRenderer(line_mapping="off"), TypstRenderer(line_mapping="off")
        off.lints = {"bold": False}
        with diagnostics.collect() as collected:
            text_off = off.render(BAD_BOLD, filepath=str(tmp_path / "doc.md"))
        text_on = on.render(BAD_BOLD, filepath=str(tmp_path / "doc.md"))
        assert _bold_warnings(collected) == []
        assert text_off == text_on

    def test_off_skips_the_detection_itself(self, tmp_path, monkeypatch):
        import text_compositor.renderer_tokens as tokens
        calls = []
        monkeypatch.setattr(tokens, "find_unapplied_bold", lambda *a, **k: calls.append(1) or [])
        renderer = TypstRenderer(line_mapping="off")
        renderer.lints = {"bold": False}
        renderer.render(BAD_BOLD, filepath=str(tmp_path / "doc.md"))
        assert calls == []


class TestHtmlApi:
    def _render(self, tmp_path, **kwargs):
        md = tmp_path / "doc.md"
        md.write_text(BAD_BOLD, encoding="utf-8")
        return render_html(str(md), plugins=PLAIN, **kwargs)

    def test_default_warns(self, tmp_path):
        assert len(_bold_warnings(self._render(tmp_path))) == 1

    def test_lint_off_gives_no_warning(self, tmp_path):
        result = self._render(tmp_path, lint={"bold": False})
        assert result.ok and _bold_warnings(result) == []

    def test_lint_on_explicitly_warns(self, tmp_path):
        assert len(_bold_warnings(self._render(tmp_path, lint={"bold": True}))) == 1

    def test_the_config_override_can_set_it_too(self, tmp_path):
        assert _bold_warnings(self._render(tmp_path, config={"lint": {"bold": False}})) == []

    def test_an_unknown_lint_is_an_error_diagnostic(self, tmp_path):
        result = self._render(tmp_path, lint={"nope": False})
        assert not result.ok
        assert any("unknown lint" in d.message for d in result.errors)


class TestConfig:
    def test_lint_is_an_allowed_top_level_key(self):
        _validate_config_keys({"lint": {"bold": False}})   # 例外が出ない

    def test_an_unknown_lint_name_is_suggested(self, capsys):
        with pytest.raises(SystemExit):
            _validate_config_keys({"lint": {"bld": False}})
        out = capsys.readouterr().out
        assert "lint.bld" in out and "bold" in out

    def test_session_arguments_land_in_the_config(self, tmp_path):
        config = _single_markdown_config(str(tmp_path / "a.md"), "template", None, None, None, None, {"bold": False})
        assert config["lint"] == {"bold": False}
        assert "lint" not in _single_markdown_config(str(tmp_path / "a.md"), "template", None, None, None, None)


class TestWorkerParam:
    @pytest.mark.parametrize("method", ["build", "render_html"])
    def test_a_valid_lint_is_passed_to_the_session(self, method):
        session = FakeSession()
        response = worker.handle_request(session, {
            "id": 1, "method": method, "params": {"path": "a.md", "lint": {"bold": False}}})
        assert response["ok"] is True
        calls = session.calls if method == "build" else session.html_calls
        assert calls[-1][2]["lint"] == {"bold": False}

    @pytest.mark.parametrize("method", ["build", "render_html"])
    @pytest.mark.parametrize("value", [{"nope": True}, {"bold": "no"}, "bold", [True]])
    def test_an_invalid_lint_is_a_protocol_error(self, method, value):
        session = FakeSession()
        response = worker.handle_request(session, {
            "id": 1, "method": method, "params": {"path": "a.md", "lint": value}})
        assert response["ok"] is False and response["error"]["code"] == "bad_request"
        assert "params.lint" in response["error"]["message"]
        assert not session.calls and not getattr(session, "html_calls", [])
