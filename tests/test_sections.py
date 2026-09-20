"""章（section）グルーピングと見出しレベルのオフセット（#68）のリグレッションテスト。"""
import os

import pytest

import text_compositor.build as build
import text_compositor.project as project_mod
from text_compositor.chapters import ChapterDefaults, _expand_chapters, _render_section_heading
from text_compositor.project import _build_one
from text_compositor.renderer import TypstRenderer

ROOT = ChapterDefaults(
    landscape=False, paper="a4", header="Doc", footer=None, paginate=True,
    background=None, logo=None, table_header={"bold": True}, heading_offset=0)


def expand(chapters, root=ROOT):
    return _expand_chapters(chapters, root, "/proj", "/proj")


class TestHeadingOffsetRendering:
    def render(self, md, offset):
        renderer = TypstRenderer(line_mapping="off")
        renderer.heading_offset = offset
        return renderer.render_chapter(md, filepath="a.md")

    def test_default_offset_zero_keeps_levels(self):
        assert self.render("# A\n\n## B\n", 0) == "= A\n\n== B\n\n"

    def test_offset_one_shifts_all_headings(self):
        assert self.render("# A\n\n## B\n", 1) == "== A\n\n=== B\n\n"

    def test_offset_applies_inside_layout_blocks(self):
        out = self.render("::: layout-right\n# T\n\n```dot\ndigraph { a -> b }\n```\n:::\n", 1)
        assert "== T" in out


class TestExpandChapters:
    def test_flat_chapters_keep_root_defaults(self):
        entries = expand(["a.md", {"file": "b.md"}])
        assert [k for k, _, _ in entries] == ["chapter", "chapter"]
        assert all(d is ROOT for _, _, d in entries)

    def test_section_expands_to_heading_then_children_with_offset_one(self):
        entries = expand([{"section": "保守編", "chapters": ["a.md", "b.md"]}])
        assert [(k, e if k == "section" else e) for k, e, _ in entries] == [
            ("section", "保守編"), ("chapter", "a.md"), ("chapter", "b.md")]
        assert all(d.heading_offset == 1 for _, _, d in entries)

    def test_section_overrides_are_inherited_by_children(self):
        entries = expand([{"section": "S", "header": "H", "footer": "F", "paginate": False,
                           "landscape": True, "paper_size": "a3", "table_header": {"color": "red"},
                           "chapters": ["a.md"]}])
        d = entries[1][2]
        assert (d.header, d.footer, d.paginate, d.landscape, d.paper) == ("H", "F", False, True, "a3")
        # table_headerはキー単位のマージ（rootのboldを残し、colorを足す）
        assert d.table_header == {"bold": True, "color": "red"}

    def test_section_inherits_root_when_unspecified(self):
        d = expand([{"section": "S", "chapters": ["a.md"]}])[1][2]
        assert (d.header, d.footer, d.paginate, d.paper, d.landscape) == ("Doc", None, True, "a4", False)

    def test_section_does_not_leak_into_following_flat_chapters(self):
        entries = expand([{"section": "S", "header": "H", "chapters": ["a.md"]}, "after.md"])
        assert entries[-1][2] is ROOT

    def test_explicit_zero_offset(self):
        d = expand([{"section": "S", "heading_offset": 0, "chapters": ["a.md"]}])[1][2]
        assert d.heading_offset == 0

    def test_root_table_header_is_not_mutated(self):
        expand([{"section": "S", "table_header": {"color": "red"}, "chapters": ["a.md"]}])
        assert ROOT.table_header == {"bold": True}


class TestValidation:
    @pytest.mark.parametrize("bad", [
        {"section": "", "chapters": ["a.md"]},
        {"section": 3, "chapters": ["a.md"]},
        {"section": "S"},
        {"section": "S", "chapters": []},
        {"section": "S", "chapters": "a.md"},
        {"section": "S", "file": "x.md", "chapters": ["a.md"]},
        {"section": "S", "aggregate": "tc", "chapters": ["a.md"]},
        {"section": "S", "chapters": [{"section": "Inner", "chapters": ["a.md"]}]},
        {"section": "S", "heading_offset": -1, "chapters": ["a.md"]},
        {"section": "S", "heading_offset": 6, "chapters": ["a.md"]},
        {"section": "S", "heading_offset": "1", "chapters": ["a.md"]},
        {"section": "S", "heading_offset": True, "chapters": ["a.md"]},
        {"file": "a.md", "heading_offset": 9},
    ])
    def test_invalid_config_is_fatal(self, bad):
        with pytest.raises(SystemExit) as e:
            expand([bad])
        assert e.value.code == 1

    def test_chapter_level_offset_is_accepted(self):
        entries = expand([{"file": "a.md", "heading_offset": 2}])
        assert entries[0][1]["heading_offset"] == 2


class TestSectionHeading:
    def test_emits_h1_and_switches_page_settings_when_they_differ(self):
        renderer = TypstRenderer(line_mapping="off")
        d = ROOT._replace(header="Sec header", heading_offset=1)
        out, *state = _render_section_heading(
            "保守編", renderer, d, ROOT.landscape, ROOT.paper, ROOT.header, ROOT.footer, ROOT.paginate,
            ROOT.background, ROOT.logo)
        assert "#set page" in out
        assert out.rstrip().endswith("= 保守編")
        assert state[2] == "Sec header"

    def test_no_page_set_when_settings_are_unchanged(self):
        renderer = TypstRenderer(line_mapping="off")
        out, *_ = _render_section_heading(
            "S", renderer, ROOT, ROOT.landscape, ROOT.paper, ROOT.header, ROOT.footer, ROOT.paginate,
            ROOT.background, ROOT.logo)
        assert out == "= S\n\n"

    def test_title_is_escaped(self):
        renderer = TypstRenderer(line_mapping="off")
        out, *_ = _render_section_heading(
            "A #1 *x*", renderer, ROOT, ROOT.landscape, ROOT.paper, ROOT.header, ROOT.footer, ROOT.paginate,
            ROOT.background, ROOT.logo)
        assert "\\#1" in out and "\\*x\\*" in out


@pytest.fixture
def project(tmp_path, monkeypatch):
    """_build_oneを通して生成されるTypstコードを取得する。コンパイル（フォント・typst）は差し替える。"""
    (tmp_path / "pre.md").write_text("# Preface\n\npre body\n", encoding="utf-8")
    (tmp_path / "m1.md").write_text("# Mainte One\n\n## Detail\n\ntext\n", encoding="utf-8")
    (tmp_path / "m2.md").write_text("# Mainte Two\n", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(project_mod, "_compile_and_cleanup", lambda typst_code, *a, **k: captured.setdefault("code", typst_code))

    def run(config_text):
        cfg = tmp_path / "text-compositor.config.yaml"
        cfg.write_text(config_text, encoding="utf-8")
        captured.clear()
        tool_dir = os.path.dirname(os.path.abspath(build.__file__))
        _build_one(tool_dir, str(tmp_path), "fonts", str(cfg))
        return captured["code"]

    return run


HEAD = "document:\n  cover: none\ninputs:\n  dir: \".\"\n"


class TestBuildOneIntegration:
    def test_section_produces_two_level_headings(self, project):
        code = project(HEAD + "chapters:\n  - pre.md\n  - section: 保守編\n    chapters: [m1.md, m2.md]\n")
        lines = code.splitlines()
        assert "= 保守編" in lines
        assert "== Mainte One" in lines
        assert "=== Detail" in lines
        assert "== Mainte Two" in lines
        # フラットな章は従来どおり（H1のまま）
        assert "= Preface" not in lines  # cover: noneの先頭タイトルは落とされる従来挙動

    def test_leading_section_keeps_first_child_title(self, project):
        code = project(HEAD + "chapters:\n  - section: 保守編\n    chapters: [m1.md]\n")
        assert "== Mainte One" in code.splitlines()

    def test_flat_config_is_unchanged_by_the_feature(self, project):
        code = project(HEAD + "chapters:\n  - pre.md\n  - m1.md\n")
        lines = code.splitlines()
        assert "= Mainte One" in lines and "== Detail" in lines

    def test_section_header_applies_and_is_restored_after_section(self, project):
        code = project("document:\n  cover: none\n  title: T\ninputs:\n  dir: \".\"\n"
                       "chapters:\n  - section: S\n    header: SecHdr\n    chapters: [m1.md]\n  - m2.md\n")
        # sectionのheaderは、章見出し（= S）より前に切り替わる
        assert code.index('render-header("SecHdr"') < code.index("\n= S\n")
        # section終了後の次のフラットな章では、グローバルのheader（既定はtitle=T）へ戻る
        restored = code.index('render-header("T"', code.index("== Mainte One"))
        assert restored < code.index("= Mainte Two")

    def test_chapter_can_override_section_header(self, project):
        code = project(HEAD + "chapters:\n  - section: S\n    header: SecHdr\n"
                       "    chapters:\n      - file: m1.md\n        header: OwnHdr\n")
        assert "OwnHdr" in code

    def test_chapter_heading_offset_override(self, project):
        code = project(HEAD + "chapters:\n  - section: S\n    chapters:\n"
                       "      - file: m1.md\n        heading_offset: 0\n")
        assert "= Mainte One" in code.splitlines()
