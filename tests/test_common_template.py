"""共通の補助関数`_common.typ`（#63）のリグレッションテスト。"""
import os
import re

import pytest

import text_compositor.build as build

TOOL_DIR = os.path.dirname(os.path.abspath(build.__file__))
TEMPLATES = os.path.join(TOOL_DIR, "templates")
HELPERS = ["fit-image", "render-graph", "render-header", "render-footer", "render-background", "callout"]


def read(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return f.read()


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestBundledTemplates:
    def test_common_defines_all_helpers(self):
        common = read("_common.typ")
        for name in HELPERS:
            assert re.search(rf"^#let {re.escape(name)}\(", common, re.MULTILINE), name

    def test_template_reexports_all_helpers_from_common(self):
        """build.pyの生成コードはtemplate.typからimportするため、全補助関数が見える必要がある。"""
        tpl = read("template.typ")
        m = re.search(r'^#import "_common\.typ": (.+)$', tpl, re.MULTILINE)
        assert m
        assert set(HELPERS) <= {n.strip() for n in m.group(1).split(",")}

    def test_helpers_are_not_defined_twice_in_template(self):
        for name in ("fit-image", "render-graph", "callout", "render-background"):
            for tpl_name in ("template.typ", "slide.typ"):
                assert not re.search(rf"^#let {re.escape(name)}\(", read(tpl_name), re.MULTILINE), (tpl_name, name)

    def test_slide_keeps_its_own_header_and_footer(self):
        slide = read("slide.typ")
        assert re.search(r"^#let render-header\(", slide, re.MULTILINE)
        assert re.search(r"^#let render-footer\(", slide, re.MULTILINE)
        m = re.search(r'^#import "_common\.typ": (.+)$', slide, re.MULTILINE)
        assert "render-header" not in m.group(1) and "render-footer" not in m.group(1)


class TestPrepareTemplate:
    @pytest.fixture
    def env(self, tmp_path):
        project_dir = tmp_path / "proj"
        work_dir = project_dir / ".text-compositor"
        work_dir.mkdir(parents=True)
        return project_dir, work_dir

    def test_common_is_copied_next_to_template(self, env):
        project_dir, work_dir = env
        config = {"template": {"path": "template"}}
        copy_path, _ = build._prepare_template(config, TOOL_DIR, str(project_dir), str(work_dir), str(project_dir))
        assert os.path.dirname(copy_path) == str(work_dir)
        assert (work_dir / "_common.typ").read_text(encoding="utf-8") == read("_common.typ")

    def test_common_is_copied_for_custom_typ_template(self, env):
        """アダプタ（独自の.typ）も、隣の_common.typを相対パスで読み込める。"""
        project_dir, work_dir = env
        write(str(project_dir / "adapter.typ"), '#import "_common.typ": fit-image\n')
        config = {"template": {"path": "adapter.typ"}}
        build._prepare_template(config, TOOL_DIR, str(project_dir), str(work_dir), str(project_dir))
        assert (work_dir / "_common.typ").exists()


class TestCleanRemovesCommon:
    def test_clean_removes_common_copy(self, tmp_path):
        cfg = str(tmp_path / "c.yaml")
        write(cfg, "chapters: [a.md]\n")
        work = tmp_path / ".text-compositor"
        write(str(work / "_common.typ"))
        write(str(work / "_template.typ"))
        build._clean_one(cfg, include_cache=False)
        assert not work.exists()


class TestIfChangedDependsOnCommon:
    def test_newer_common_makes_output_stale(self, tmp_path, monkeypatch):
        """同梱の補助関数が更新（pip upgrade等）されたら、入力が同じでも再生成する。"""
        tool = tmp_path / "tool"
        for name in ("templates/template.typ", "templates/_common.typ", "build.py"):
            write(str(tool / name))
        monkeypatch.setattr(build, "__file__", str(tool / "build.py"), raising=False)
        cfg = str(tmp_path / "proj" / "c.yaml")
        write(cfg, "chapters: [a.md]\n")
        pdf = str(tmp_path / "proj" / "outputs" / "System_Specification.pdf")
        write(pdf)

        def mtime(path, sec):
            os.utime(path, ns=(int(sec * 1e9), int(sec * 1e9)))

        for p in (str(tool / "templates" / "template.typ"), str(tool / "build.py"), cfg):
            mtime(p, 1000)
        mtime(str(tool / "templates" / "_common.typ"), 1000)
        mtime(pdf, 2000)
        project_dir, config, _ = build._load_project_config(cfg)
        assert build._is_up_to_date(str(tool), cfg, project_dir, config)[0] is True

        mtime(str(tool / "templates" / "_common.typ"), 3000)
        assert build._is_up_to_date(str(tool), cfg, project_dir, config)[0] is False
