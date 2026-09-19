"""Python API（api.py、#167）のテスト。実際にTypstでコンパイルするため、フォント（初回のみ取得）と、
Typstのパッケージ（テンプレートが使う@preview/…。初回のみ取得）を使う。"""
import os
import struct
import sys
import zlib

import pytest

import text_compositor.build as build
from text_compositor import diagnostics
from text_compositor.api import BuildResult, Session, build_markdown


@pytest.fixture(scope="module")
def font_dir():
    return build.ensure_fonts()


@pytest.fixture
def session(font_dir):
    with Session(font_dir=font_dir) as s:
        yield s


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def png_bytes(rgb):
    """8x8の単色PNG（標準ライブラリだけで作る）。"""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * 8 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


class TestBuild:
    def test_builds_a_pdf_to_the_requested_path(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# 見出し\n\n本文。\n\n- a\n- b\n")
        out = tmp_path / "out" / "doc.pdf"
        result = session.build(str(md), str(out), plugins=PLAIN)
        assert isinstance(result, BuildResult)
        assert result.ok and not result.errors
        assert result.pdf_path == str(out)
        assert read_bytes(str(out)).startswith(b"%PDF")

    def test_does_not_create_an_outputs_directory_next_to_the_markdown(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        session.build(str(md), str(tmp_path / "x" / "o.pdf"), plugins=PLAIN)
        assert not (tmp_path / "outputs").exists()

    def test_default_output_is_under_the_work_directory(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        result = session.build(str(md), plugins=PLAIN)
        assert result.ok
        assert result.pdf_path == str(tmp_path / ".text-compositor" / "preview.pdf")
        assert os.path.exists(result.pdf_path)

    def test_leaves_no_intermediate_files_and_no_temporary_pdf(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        out = tmp_path / "out" / "doc.pdf"
        session.build(str(md), str(out), plugins=PLAIN)
        assert sorted(os.listdir(str(tmp_path / ".text-compositor"))) == []
        assert sorted(os.listdir(str(out.parent))) == ["doc.pdf"]

    def test_keep_temp_keeps_the_generated_typst(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN, keep_temp=True)
        assert (tmp_path / ".text-compositor" / "temp_build.typ").exists()

    def test_writes_nothing_to_stdout(self, session, tmp_path, capsys):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbefore <span>x</span> after\n")
        session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        write(str(md), "# T\n\n```dot {width=bogus}\ndigraph { a -> b }\n```\n")
        session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert capsys.readouterr().out == ""

    def test_timings_are_reported(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert set(result.timings_ms) >= {"render", "compile", "total"}
        assert result.timings_ms["total"] >= result.timings_ms["compile"] > 0

    def test_first_markdown_heading_is_kept_as_is(self, session, tmp_path):
        """プレビューでは、先頭のH1を落とさない（CLIの既定のcover: noneは、先頭のタイトルを落とす）。"""
        md = tmp_path / "doc.md"
        write(str(md), "# 先頭の見出し\n\n本文。\n")
        session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN, keep_temp=True)
        typst = (tmp_path / ".text-compositor" / "temp_build.typ").read_text(encoding="utf-8")
        assert "= 先頭の見出し" in typst
        assert "cover: false" in typst


class TestOptions:
    @pytest.mark.parametrize("template", ["template", "slide", "paper"])
    def test_bundled_templates(self, session, tmp_path, template):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\n## 節\n\n本文。\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), template=template, plugins=PLAIN)
        assert result.ok, result.diagnostics

    def test_document_and_variables_overrides(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nバージョンは{{VERSION}}。\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN,
                               document={"title": "仕様書", "toc": True}, variables={"VERSION": "1.2"},
                               keep_temp=True)
        assert result.ok
        typst = (tmp_path / ".text-compositor" / "temp_build.typ").read_text(encoding="utf-8")
        assert 'title: "仕様書"' in typst and "toc: true" in typst and "バージョンは1.2。" in typst

    def test_config_override_applies_last(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN, document={"title": "A"},
                               config={"document": {"title": "B"}}, keep_temp=True)
        assert result.ok
        assert 'title: "B"' in (tmp_path / ".text-compositor" / "temp_build.typ").read_text(encoding="utf-8")

    def test_custom_typ_template_by_path(self, session, tmp_path):
        """独自テンプレートは、Markdownの隣からの相対パスで指定できる。"""
        with open(os.path.join(build.__file__ and os.path.dirname(build.__file__), "templates", "template.typ"),
                  encoding="utf-8") as f:
            write(str(tmp_path / "my.typ"), f.read())
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), template="my.typ", plugins=PLAIN)
        assert result.ok, result.diagnostics


class TestFailures:
    def test_missing_markdown_is_reported_not_raised(self, session, tmp_path):
        result = session.build(str(tmp_path / "none.md"), str(tmp_path / "o.pdf"))
        assert not result.ok and result.pdf_path is None
        assert result.errors and "not found" in result.errors[0].message

    def test_unknown_template_is_reported(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), template="no_such_template", plugins=PLAIN)
        assert not result.ok
        assert any("Template not found" in d.message for d in result.errors)

    def test_compile_error_points_at_the_markdown_line(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# 見出し\n\n```dot {width=bogus}\ndigraph { a -> b }\n```\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert not result.ok and result.pdf_path is None
        error = result.errors[0]
        assert "unknown variable: bogus" in error.message
        assert error.file == str(md) and error.line == 3
        assert error.detail and "temp_build.typ" in error.detail

    def test_a_failed_build_keeps_the_previous_pdf(self, session, tmp_path):
        md = tmp_path / "doc.md"
        out = tmp_path / "o.pdf"
        write(str(md), "# T\n\nok\n")
        assert session.build(str(md), str(out), plugins=PLAIN).ok
        before = read_bytes(str(out))
        write(str(md), "# T\n\n```dot {width=bogus}\ndigraph { a -> b }\n```\n")
        assert not session.build(str(md), str(out), plugins=PLAIN).ok
        assert read_bytes(str(out)) == before

    def test_the_session_recovers_after_a_failure(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\n```dot {width=bogus}\ndigraph { a -> b }\n```\n")
        assert not session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN).ok
        write(str(md), "# T\n\nfine\n")
        assert session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN).ok

    def test_security_violation_is_a_structured_error(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\n```typst-exec\n#panic(\"x\")\n```\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert not result.ok
        assert any("typst-exec" in d.message and d.file == str(md) for d in result.errors)

    def test_unexpected_exceptions_do_not_escape(self, session, tmp_path, monkeypatch):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n")

        def boom(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(build, "_build_project", boom)
        result = session.build(str(md), str(tmp_path / "o.pdf"))
        assert not result.ok
        assert "kaboom" in result.errors[0].message and "Traceback" in result.errors[0].detail

    def test_closed_session_reports_an_error(self, font_dir, tmp_path):
        s = Session(font_dir=font_dir)
        s.close()
        md = tmp_path / "doc.md"
        write(str(md), "# T\n")
        assert not s.build(str(md), str(tmp_path / "o.pdf")).ok

    def test_output_open_elsewhere_is_reported(self, session, tmp_path, monkeypatch):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")

        def denied(src, dst):
            raise PermissionError("in use")
        monkeypatch.setattr(os, "replace", denied)
        monkeypatch.setattr(build.time, "sleep", lambda s: None)
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert not result.ok
        assert any("Cannot write the PDF" in d.message for d in result.errors)
        assert [n for n in os.listdir(str(tmp_path)) if n.startswith(".tmp-")] == []


class TestWarnings:
    def test_html_warning_carries_file_and_line(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\ntext\n\nbefore <span>x</span> after\n")
        result = session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert result.ok
        assert result.warnings
        assert all(d.file == str(md) and d.line == 5 for d in result.warnings if "HTML" in d.message)

    def test_warnings_do_not_leak_between_builds(self, session, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbefore <span>x</span>\n")
        assert session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN).warnings
        write(str(md), "# T\n\nclean\n")
        assert not session.build(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN).warnings


class TestResidentReuse:
    def test_compiler_is_reused_and_changes_are_reflected(self, session, tmp_path):
        md = tmp_path / "doc.md"
        out = tmp_path / "o.pdf"
        write(str(md), "# T\n\nfirst\n")
        assert session.build(str(md), str(out), plugins=PLAIN).ok
        first = read_bytes(str(out))
        write(str(md), "# T\n\nsecond, and a bit longer text\n")
        assert session.build(str(md), str(out), plugins=PLAIN).ok
        assert read_bytes(str(out)) != first
        assert len(session._compilers) == 1

    def test_a_replaced_image_is_picked_up(self, session, tmp_path):
        """同じパスの画像を差し替えても、使い回したコンパイラが古い画像を返さない。"""
        md = tmp_path / "doc.md"
        img = tmp_path / "img.png"
        out = tmp_path / "o.pdf"
        write(str(md), "# T\n\n![pic](img.png)\n")
        img.write_bytes(png_bytes((255, 0, 0)))
        assert session.build(str(md), str(out), plugins=PLAIN).ok
        red = read_bytes(str(out))
        img.write_bytes(png_bytes((0, 0, 255)))
        assert session.build(str(md), str(out), plugins=PLAIN).ok
        assert read_bytes(str(out)) != red

    def test_different_documents_in_one_session(self, session, tmp_path):
        a, b = tmp_path / "a" / "a.md", tmp_path / "b" / "b.md"
        write(str(a), "# A\n\nalpha\n")
        write(str(b), "# B\n\nbeta\n")
        assert session.build(str(a), str(tmp_path / "a.pdf"), plugins=PLAIN).ok
        assert session.build(str(b), str(tmp_path / "b.pdf"), plugins=PLAIN).ok
        assert session.build(str(a), str(tmp_path / "a.pdf"), plugins=PLAIN).ok
        assert read_bytes(str(tmp_path / "a.pdf")) != read_bytes(str(tmp_path / "b.pdf"))

    def test_close_releases_everything_and_is_idempotent(self, font_dir):
        closed = []

        class FakeBrowser:
            page = None

            def close(self):
                closed.append(1)
        s = Session(font_dir=font_dir)
        s._mermaid = FakeBrowser()
        s._compilers["k"] = object()
        s.close()
        s.close()
        assert closed == [1, 1] and s._compilers == {}


class TestModuleFunction:
    def test_build_markdown_is_a_one_shot(self, font_dir, tmp_path):
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbody\n")
        result = build_markdown(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        assert result.ok and os.path.exists(result.pdf_path)

    def test_public_names_are_importable_from_the_package(self):
        import text_compositor
        assert text_compositor.Session is Session
        assert text_compositor.build_markdown is build_markdown
        assert text_compositor.BuildResult is BuildResult
        assert text_compositor.Diagnostic is diagnostics.Diagnostic
        with pytest.raises(AttributeError):
            text_compositor.nope

    def test_plain_import_stays_light(self):
        import subprocess
        code = "import sys, text_compositor; sys.exit(1 if 'text_compositor.build' in sys.modules else 0)"
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, PYTHONPATH=repo_root + os.pathsep + os.environ.get("PYTHONPATH", ""))
        assert subprocess.run([sys.executable, "-c", code], env=env, cwd=repo_root).returncode == 0

    def test_result_to_dict_is_json_serializable(self, font_dir, tmp_path):
        import json
        md = tmp_path / "doc.md"
        write(str(md), "# T\n\nbefore <span>x</span>\n")
        result = build_markdown(str(md), str(tmp_path / "o.pdf"), plugins=PLAIN)
        data = json.loads(json.dumps(result.to_dict()))
        assert data["ok"] is True and data["pdf"] == str(tmp_path / "o.pdf")
        assert data["diagnostics"][0]["severity"] == "warning"
        assert set(data["timings_ms"]) >= {"render", "compile", "total"}
