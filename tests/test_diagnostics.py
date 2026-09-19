"""診断の受け皿（diagnostics）と、既存のCLI出力が変わらないことのテスト（#167）。"""
import pytest

from text_compositor import diagnostics
import text_compositor.build as build


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
        build._error("Chapter file not found: a.md")
        assert capsys.readouterr().out == "[Error] Chapter file not found: a.md\n"

    def test_success_is_cli_only(self, capsys):
        build._log_success("Generated PDF: out.pdf")
        assert capsys.readouterr().out == "[Success] Generated PDF: out.pdf\n"
        with diagnostics.collect() as c:
            build._log_success("Generated PDF: out.pdf")
        assert c.items == []

    def test_info_ignores_quiet_when_collecting(self, monkeypatch):
        monkeypatch.setattr(build, "_QUIET", True)
        with diagnostics.collect() as c:
            build._log_info("Rendering ...")
        assert [d.severity for d in c.items] == ["info"]

    def test_info_respects_quiet_on_the_cli(self, monkeypatch, capsys):
        monkeypatch.setattr(build, "_QUIET", True)
        build._log_info("Rendering ...")
        assert capsys.readouterr().out == ""

    def test_verbose_is_not_collected(self, monkeypatch, capsys):
        monkeypatch.setattr(build, "_VERBOSE", True)
        with diagnostics.collect() as c:
            build._log_verbose("detail")
        assert c.items == [] and capsys.readouterr().out == ""


class TestRendererLocations:
    """レンダラーの警告・エラーが、原稿のfile/lineを持つ。"""

    def render(self, text, filepath="doc.md"):
        renderer = build.TypstRenderer(line_mapping="off")
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
        renderer = build.TypstRenderer(line_mapping="off")
        renderer.render("a\n\n[x]{size=oops}\n", filepath="doc.md")
        assert "[Warning] Ignoring invalid size 'oops' in doc.md:3; expected e.g. '10pt'." in capsys.readouterr().out
