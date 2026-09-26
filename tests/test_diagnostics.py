"""診断の受け皿（diagnostics）と、既存のCLI出力が変わらないことのテスト（#167）。"""
import pytest

from text_compositor import diagnostics
from text_compositor.log import _error, _log_info, _log_success, _log_verbose
from text_compositor.renderer import TypstRenderer
import text_compositor.log as log_mod


class TestOutsideCollect:
    """collect()の外（CLI）では、従来どおり`[Error] ...`を標準出力へ出す。"""

    def test_error_prints_with_the_legacy_prefix(self, capsys):
        diagnostics.error("Config file not found: x.yaml")
        assert capsys.readouterr().out == "[Error] Config file not found: x.yaml\n"

    @pytest.mark.parametrize("severity,label", [("warning", "Warning"), ("hint", "Hint"), ("info", "Info")])
    def test_other_severities_use_their_labels(self, capsys, severity, label):
        diagnostics.emit(severity, "msg")
        assert capsys.readouterr().out == f"[{label}] msg\n"

    def test_cli_text_overrides_the_printed_message_only(self, capsys):
        diagnostics.error("short", detail="long", cli_text="Compile failed:\nlong")
        assert capsys.readouterr().out == "[Error] Compile failed:\nlong\n"

    def test_unknown_severity_is_rejected(self):
        with pytest.raises(ValueError):
            diagnostics.emit("fatal", "x")


class TestCollect:
    def test_collects_in_order_and_prints_nothing(self, capsys):
        with diagnostics.collect() as c:
            diagnostics.warning("w", file="a.md", line=3)
            diagnostics.error("e", detail="d")
            diagnostics.hint("h")
        assert capsys.readouterr().out == ""
        assert [(d.severity, d.message) for d in c.items] == [("warning", "w"), ("error", "e"), ("hint", "h")]
        assert c.items[0].file == "a.md" and c.items[0].line == 3
        assert c.items[1].detail == "d"
        assert [d.message for d in c.errors] == ["e"]
        assert [d.message for d in c.warnings] == ["w"]

    def test_active_flag(self):
        assert not diagnostics.active()
        with diagnostics.collect():
            assert diagnostics.active()
        assert not diagnostics.active()

    def test_nested_collect_is_isolated(self):
        with diagnostics.collect() as outer:
            diagnostics.warning("outer1")
            with diagnostics.collect() as inner:
                diagnostics.warning("inner")
            diagnostics.warning("outer2")
        assert [d.message for d in outer.items] == ["outer1", "outer2"]
        assert [d.message for d in inner.items] == ["inner"]

    def test_collector_is_released_after_an_exception(self):
        with pytest.raises(RuntimeError):
            with diagnostics.collect():
                raise RuntimeError("boom")
        assert not diagnostics.active()

    def test_to_dict(self):
        d = diagnostics.Diagnostic("error", "m", file="f.md", line=2)
        assert d.to_dict() == {"severity": "error", "message": "m", "file": "f.md", "line": 2, "detail": None}


class TestBuildHelpers:
    """build.pyの補助関数が、CLIでは従来どおり、collect()の中では構造化して出す。"""

    def test_error_helper_is_cli_compatible(self, capsys):
        _error("Chapter file not found: a.md")
        assert capsys.readouterr().out == "[Error] Chapter file not found: a.md\n"

    def test_success_is_cli_only(self, capsys):
        _log_success("Generated PDF: out.pdf")
        assert capsys.readouterr().out == "[Success] Generated PDF: out.pdf\n"
        with diagnostics.collect() as c:
            _log_success("Generated PDF: out.pdf")
        assert c.items == []

    def test_info_ignores_quiet_when_collecting(self, monkeypatch):
        monkeypatch.setattr(log_mod, "_QUIET", True)
        with diagnostics.collect() as c:
            _log_info("Rendering ...")
        assert [d.severity for d in c.items] == ["info"]

    def test_info_respects_quiet_on_the_cli(self, monkeypatch, capsys):
        monkeypatch.setattr(log_mod, "_QUIET", True)
        _log_info("Rendering ...")
        assert capsys.readouterr().out == ""

    def test_verbose_is_not_collected(self, monkeypatch, capsys):
        monkeypatch.setattr(log_mod, "_VERBOSE", True)
        with diagnostics.collect() as c:
            _log_verbose("detail")
        assert c.items == [] and capsys.readouterr().out == ""


class TestGithubActionsAnnotations:
    """GitHub Actions実行時（GITHUB_ACTIONS=true）に追加で出す`::warning ...::`/`::error ...::`
    ワークフローコマンド（#29）。GITHUB_ACTIONSが無いときは、tests/conftest.pyのautouseフィクスチャ
    により常に未設定として扱われる（このプロジェクト自身のCIもGitHub Actions上で動くため）。"""

    def test_no_annotation_when_not_in_github_actions(self, capsys):
        diagnostics.warning("w", file="doc.md", line=3)
        assert capsys.readouterr().out == "[Warning] w\n"

    def test_warning_annotation_with_workspace_relative_file(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        md_path = tmp_path / "docs" / "a.md"
        diagnostics.warning("w", file=str(md_path), line=3)
        assert capsys.readouterr().out == "[Warning] w\n::warning file=docs/a.md,line=3::w\n"

    def test_error_annotation(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        diagnostics.error("e", file=str(tmp_path / "a.md"), line=1)
        assert capsys.readouterr().out == "[Error] e\n::error file=a.md,line=1::e\n"

    @pytest.mark.parametrize("severity,label", [("hint", "Hint"), ("info", "Info")])
    def test_hint_and_info_have_no_github_equivalent(self, monkeypatch, capsys, tmp_path, severity, label):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        diagnostics.emit(severity, "m", file=str(tmp_path / "a.md"), line=1)
        assert capsys.readouterr().out == f"[{label}] m\n"

    def test_omits_line_property_when_line_is_unknown(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        diagnostics.warning("w", file=str(tmp_path / "a.md"))
        assert capsys.readouterr().out == "[Warning] w\n::warning file=a.md::w\n"

    def test_omits_file_property_when_file_is_unknown(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        diagnostics.error("e")
        assert capsys.readouterr().out == "[Error] e\n::error::e\n"

    def test_file_outside_the_workspace_falls_back_to_no_file_property(self, monkeypatch, capsys, tmp_path):
        """原稿がリポジトリ（GITHUB_WORKSPACE）の外にあってもよい設計（3章）のための後方互換。"""
        workspace = tmp_path / "workspace"
        outside = tmp_path / "outside" / "a.md"
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
        diagnostics.error("e", file=str(outside), line=5)
        assert capsys.readouterr().out == "[Error] e\n::error::e\n"

    def test_escapes_percent_and_newlines_in_the_message(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        diagnostics.warning("100% done\nnext line", file=str(tmp_path / "a.md"), line=1)
        out = capsys.readouterr().out
        assert "::warning file=a.md,line=1::100%25 done%0Anext line\n" in out

    def test_collect_mode_never_emits_an_annotation(self, monkeypatch, capsys, tmp_path):
        """Python API/常駐ワーカー（collect()の中）は、従来どおり標準出力に何も出さない。"""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        with diagnostics.collect():
            diagnostics.warning("w", file=str(tmp_path / "a.md"), line=1)
        assert capsys.readouterr().out == ""


class TestRendererLocations:
    """レンダラーの警告・エラーが、原稿のfile/lineを持つ。"""

    def render(self, text, filepath="doc.md"):
        renderer = TypstRenderer(line_mapping="off")
        with diagnostics.collect() as c:
            renderer.render(text, filepath=filepath)
        return c

    def test_html_warning_has_file_and_the_block_line(self):
        c = self.render("# T\n\ntext\n\nbefore <span>x</span> after\n")
        html = [d for d in c.warnings if "HTML tag" in d.message]
        assert html and all(d.file == "doc.md" and d.line == 5 for d in html)

    def test_invalid_span_size_warning_has_a_location(self):
        c = self.render("a\n\n[x]{size=oops}\n")
        w = [d for d in c.warnings if "invalid size" in d.message]
        assert w and w[0].file == "doc.md" and w[0].line == 3

    def test_unknown_front_matter_key_is_attributed_to_the_file(self):
        c = self.render("---\nbogus: 1\n---\n# T\n")
        w = [d for d in c.warnings if "Unknown front-matter key" in d.message]
        assert w and w[0].file == "doc.md"

    def test_no_file_when_rendering_a_bare_string(self):
        c = self.render("a\n\n[x]{size=oops}\n", filepath="")
        w = [d for d in c.warnings if "invalid size" in d.message]
        assert w and w[0].file is None

    def test_cli_message_is_unchanged_when_the_line_is_known(self, capsys):
        renderer = TypstRenderer(line_mapping="off")
        renderer.render("a\n\n[x]{size=oops}\n", filepath="doc.md")
        assert "[Warning] Ignoring invalid size 'oops' in doc.md:3; expected e.g. '10pt'." in capsys.readouterr().out
