"""CLI: 単一のMarkdownファイルを直接指定してPDFにする（`text-compositor FILE.md`、#179）のテスト。"""
import os
import sys

import pytest

import text_compositor.build as build_mod
from text_compositor import log
import text_compositor.project as project_mod
from text_compositor.build import _single_markdown_output, parse_args


@pytest.fixture(autouse=True)
def _restore_verbosity():
    """`build()`は、-q/-vを、プロセスグローバルへ反映する。他のテストへ、残さない。"""
    yield
    log.set_verbosity(False, False)


def parse(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["text-compositor", *argv])
    return parse_args()


class TestParseArgs:
    def test_a_single_file_with_output_and_template(self, monkeypatch):
        args = parse(monkeypatch, "doc.md", "-o", "out.pdf", "-t", "slide", "-q", "--keep-temp")
        assert (args.markdown, args.output, args.template, args.quiet, args.keep_temp) == ("doc.md", "out.pdf", "slide", True, True)

    def test_existing_usage_without_a_file_is_unchanged(self, monkeypatch):
        args = parse(monkeypatch, "--config", "c.yaml", "--if-changed")
        assert args.markdown is None and args.config == "c.yaml" and args.if_changed

    @pytest.mark.parametrize("flags", [
        ["--config", "c.yaml"], ["--config-list", "l.txt"], ["--check-env"], ["--watch"], ["--if-changed"],
        ["--clean"], ["--clean-cache"],
    ])
    def test_options_that_need_a_config_cannot_be_combined_with_a_file(self, monkeypatch, capsys, flags):
        with pytest.raises(SystemExit) as e:
            parse(monkeypatch, "doc.md", *flags)
        assert e.value.code == 2
        assert "同時に指定できません" in capsys.readouterr().err

    @pytest.mark.parametrize("flags", [["-o", "out.pdf"], ["-t", "slide"]])
    def test_output_and_template_need_a_file(self, monkeypatch, capsys, flags):
        with pytest.raises(SystemExit) as e:
            parse(monkeypatch, *flags)
        assert e.value.code == 2 and "FILE.md" in capsys.readouterr().err

    def test_only_markdown_files_are_accepted(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as e:
            parse(monkeypatch, "notes.txt")
        assert e.value.code == 2
        assert parse(monkeypatch, "A.MD").markdown == "A.MD" and parse(monkeypatch, "a.markdown").markdown == "a.markdown"


class TestOutputPath:
    def test_the_default_is_next_to_the_manuscript(self, tmp_path):
        md = str(tmp_path / "sub" / "note.md")
        assert _single_markdown_output(md, None) == str(tmp_path / "sub" / "note.pdf")

    def test_an_explicit_file_and_a_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        md = str(tmp_path / "note.md")
        assert _single_markdown_output(md, "out.pdf") == str(tmp_path / "out.pdf")
        (tmp_path / "existing").mkdir()
        assert _single_markdown_output(md, "existing") == str(tmp_path / "existing" / "note.pdf")
        assert _single_markdown_output(md, "new" + os.sep) == str(tmp_path / "new" / "note.pdf")


class TestBuildSingleMarkdown:
    @pytest.fixture
    def calls(self, monkeypatch):
        recorded = []
        monkeypatch.setattr(project_mod, "_build_project", lambda *a, **k: recorded.append((a, k)))
        return recorded

    def run(self, tmp_path, *argv, monkeypatch):
        monkeypatch.setattr(build_mod, "check_typst_version", lambda *a: None)
        monkeypatch.setattr(build_mod, "ensure_fonts", lambda: "fonts")
        monkeypatch.setattr(sys, "argv", ["text-compositor", *argv])
        build_mod.build()

    def test_it_builds_the_api_config_and_writes_next_to_the_manuscript(self, tmp_path, calls, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("# T\n", encoding="utf-8")
        self.run(tmp_path, str(md), monkeypatch=monkeypatch)
        (args, kwargs), = calls
        project_dir, config, chapters = args[3], args[4], args[5]
        assert project_dir == str(tmp_path) and chapters == ["note.md"]
        assert config["document"]["cover"] == "markdown" and config["document"]["title"] == "note"   # APIと同じ既定
        assert config["template"]["path"] == "template"
        assert kwargs["out_pdf"] == str(tmp_path / "note.pdf")

    def test_the_template_name_and_a_typ_path_relative_to_the_cwd(self, tmp_path, calls, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("# T\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        self.run(tmp_path, "note.md", "-t", "paper", monkeypatch=monkeypatch)
        self.run(tmp_path, "note.md", "-t", "my/own.typ", "-o", "build/o.pdf", monkeypatch=monkeypatch)
        assert calls[0][0][4]["template"]["path"] == "paper"
        assert calls[1][0][4]["template"]["path"] == str(tmp_path / "my" / "own.typ")
        assert calls[1][1]["out_pdf"] == str(tmp_path / "build" / "o.pdf") and (tmp_path / "build").is_dir()

    def test_a_missing_file_and_an_unknown_template_fail_with_exit_code_1(self, tmp_path, calls, monkeypatch, capsys):
        with pytest.raises(SystemExit) as e:
            self.run(tmp_path, str(tmp_path / "nope.md"), monkeypatch=monkeypatch)
        assert e.value.code == 1 and "Markdown file not found" in capsys.readouterr().out
        md = tmp_path / "note.md"
        md.write_text("# T\n", encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            self.run(tmp_path, str(md), "-t", "nosuch", monkeypatch=monkeypatch)
        assert e.value.code == 1 and "Unknown template" in capsys.readouterr().out
        assert calls == []


def test_a_real_pdf_is_built_without_a_config(tmp_path, monkeypatch):
    """実際に、configなしで、PDFができる（Typstとフォントが、ある環境）。先頭の見出しは、表紙に落とされず、本文に残る。"""
    from text_compositor.deps import ensure_fonts
    try:
        ensure_fonts()
    except SystemExit:
        pytest.skip("fonts are not available")
    md = tmp_path / "note.md"
    md.write_text("# 見出し\n\n本文です。\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["text-compositor", str(md), "-q"])
    build_mod.build()
    pdf = tmp_path / "note.pdf"
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")
