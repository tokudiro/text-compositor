"""```structurizrフェンスの`!include`を、原稿のフォルダ基準で解決する処理のテスト。"""
import os

import pytest

from text_compositor import structurizr_include as si


def write(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestFindIncludes:
    def test_finds_plain_and_quoted_paths_in_order(self):
        code = 'workspace {\n  model {\n    !include a.dsl\n    !include "dir/b c.dsl"\n  }\n}\n'
        assert si.find_includes(code) == ["a.dsl", "dir/b c.dsl"]

    def test_ignores_include_inside_a_word_or_comment_text(self):
        assert si.find_includes("// !include no.dsl\nname \"!include x.dsl\"\n") == []


class TestCollectIncludes:
    def test_resolves_relative_to_the_manuscript_folder(self, tmp_path):
        write(str(tmp_path / "docs" / "model.dsl"))
        files = si.collect_includes("!include model.dsl\n", str(tmp_path / "docs"), str(tmp_path))
        assert files == [os.path.realpath(str(tmp_path / "docs" / "model.dsl"))]

    def test_follows_nested_includes_relative_to_the_including_file(self, tmp_path):
        write(str(tmp_path / "m" / "model.dsl"), "!include parts/people.dsl\n")
        write(str(tmp_path / "m" / "parts" / "people.dsl"))
        files = si.collect_includes("!include m/model.dsl\n", str(tmp_path), str(tmp_path))
        assert [os.path.basename(f) for f in files] == ["model.dsl", "people.dsl"]

    def test_a_file_included_twice_is_listed_once(self, tmp_path):
        write(str(tmp_path / "a.dsl"))
        assert len(si.collect_includes("!include a.dsl\n!include a.dsl\n", str(tmp_path), str(tmp_path))) == 1

    def test_a_cycle_does_not_loop_forever(self, tmp_path):
        write(str(tmp_path / "a.dsl"), "!include b.dsl\n")
        write(str(tmp_path / "b.dsl"), "!include a.dsl\n")
        assert len(si.collect_includes("!include a.dsl\n", str(tmp_path), str(tmp_path))) == 2

    @pytest.mark.parametrize("path,message", [
        ("../outside.dsl", "outside the project"),
        ("/etc/passwd", "Absolute paths"),
        ("C:\\x.dsl", "Absolute paths"),
        ("https://example.com/a.dsl", "External URLs"),
        ("model.txt", "Only .dsl files"),
        ("missing.dsl", "was not found"),
    ])
    def test_rejects_what_it_cannot_safely_include(self, tmp_path, path, message):
        root = tmp_path / "proj"
        root.mkdir()
        write(str(tmp_path / "outside.dsl"))
        with pytest.raises(si.IncludeError, match=message):
            si.collect_includes(f"!include {path}\n", str(root), str(root))

    def test_rejects_a_symlink_that_leaves_the_project(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        write(str(tmp_path / "secret.dsl"))
        try:
            os.symlink(str(tmp_path / "secret.dsl"), str(root / "link.dsl"))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available")
        with pytest.raises(si.IncludeError, match="outside the project"):
            si.collect_includes("!include link.dsl\n", str(root), str(root))


class TestCacheSuffix:
    def test_empty_when_nothing_is_included(self, tmp_path):
        assert si.cache_suffix([], str(tmp_path)) == ""

    def test_changes_when_an_included_file_changes(self, tmp_path):
        path = str(tmp_path / "a.dsl")
        write(path, "one\n")
        before = si.cache_suffix([path], str(tmp_path))
        write(path, "two\n")
        assert si.cache_suffix([path], str(tmp_path)) != before


class TestStage:
    def test_copies_files_keeping_the_project_layout_and_returns_the_workspace_folder(self, tmp_path):
        root = tmp_path / "proj"
        write(str(root / "shared" / "model.dsl"), "model\n")
        write(str(root / "docs" / "a.md"))
        tmp = tmp_path / "tmp"
        tmp.mkdir()
        ws = si.stage([os.path.realpath(str(root / "shared" / "model.dsl"))], str(root / "docs"), str(root), str(tmp))
        assert os.path.realpath(ws) == os.path.realpath(str(tmp / "docs"))
        # ワークスペースから見て`../shared/model.dsl`が、原稿から見た位置と同じになる
        assert open(os.path.join(ws, "..", "shared", "model.dsl"), encoding="utf-8").read() == "model\n"


class TestIncludeRoot:
    def test_is_the_project_root_when_the_manuscript_is_inside(self, tmp_path):
        (tmp_path / "docs").mkdir()
        assert si.include_root(str(tmp_path / "docs"), str(tmp_path)) == os.path.realpath(str(tmp_path))

    def test_is_the_manuscript_folder_when_it_is_outside_the_project(self, tmp_path):
        (tmp_path / "proj").mkdir()
        (tmp_path / "other").mkdir()
        assert si.include_root(str(tmp_path / "other"), str(tmp_path / "proj")) == os.path.realpath(str(tmp_path / "other"))

    def test_stage_never_writes_outside_the_temp_folder(self, tmp_path):
        (tmp_path / "proj").mkdir()
        (tmp_path / "other").mkdir()
        (tmp_path / "tmp").mkdir()
        with pytest.raises(si.IncludeError):
            si.stage([], str(tmp_path / "other"), str(tmp_path / "proj"), str(tmp_path / "tmp"))


class TestRendererIntegration:
    def test_included_files_become_dependencies_for_html_change_detection(self, tmp_path):
        """HTML（Obunzu）が、取り込んだファイルを保存し直したときに、表示を更新できるようにする。"""
        from text_compositor.renderer import TypstRenderer
        write(str(tmp_path / "model.dsl"))
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path))
        renderer.dependencies = set()
        files = renderer._structurizr_includes("!include model.dsl\n", str(tmp_path))
        assert renderer.dependencies == set(files) == {os.path.realpath(str(tmp_path / "model.dsl"))}

    def test_cache_key_follows_the_included_file(self, tmp_path):
        from text_compositor.renderer import TypstRenderer
        write(str(tmp_path / "model.dsl"), "one\n")
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path))
        before = renderer._structurizr_cache_code("!include model.dsl\n", str(tmp_path))
        write(str(tmp_path / "model.dsl"), "two\n")
        assert renderer._structurizr_cache_code("!include model.dsl\n", str(tmp_path)) != before
