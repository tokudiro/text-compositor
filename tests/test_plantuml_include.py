"""PlantUMLの`!include`を、原稿のフォルダ基準で解決する機能（#622）のテスト。

1. plantuml_include.pyの単体テスト（`!include`の拾い方・取り込める範囲・キャッシュ用の文字列）
2. TypstRendererとの結合（subprocess.runをモックして、渡す環境変数・キャッシュのキー・バッチの分け方を確かめる）
3. 実際のJavaとplantuml.jarでの確認（キャッシュに無いときは、ダウンロードせずにスキップする）
"""
import os

import pytest

import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor import diagnostics, plantuml_include
from text_compositor.deps import PLANTUML_JAR_SHA256
from text_compositor.plantuml_include import IncludeError, cache_suffix, collect_includes, find_includes
from text_compositor.renderer import TypstRenderer


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


class TestFindIncludes:
    def test_finds_the_four_include_directives_in_order(self):
        code = ("@startuml\n"
                "!include a.iuml\n"
                "!include_once b.iuml\n"
                "!include_many c.iuml\n"
                "!includesub d.iuml\n"
                "@enduml\n")
        assert find_includes(code) == ["a.iuml", "b.iuml", "c.iuml", "d.iuml"]

    def test_index_and_sub_suffixes_are_removed(self):
        assert find_includes("!include a.iuml!1\n!includesub b.iuml!PART\n") == ["a.iuml", "b.iuml"]

    def test_quoted_paths_and_indentation(self):
        assert find_includes('  !include "my defs.iuml"\n') == ["my defs.iuml"]

    def test_standard_library_is_not_a_file(self):
        assert find_includes("!include <C4/C4_Container>\n!include <awslib/AWSCommon>\n") == []

    def test_paths_with_variables_or_functions_are_skipped(self):
        assert find_includes("!include %getenv('X')/a.iuml\n!include $dir/a.iuml\n") == []

    def test_comments_and_text_in_the_middle_of_a_line_are_not_includes(self):
        assert find_includes("' !include a.iuml\nA -> B: !include b.iuml\n") == []

    def test_urls_are_kept_so_that_they_can_be_rejected_with_a_reason(self):
        assert find_includes("!include https://example.com/x.puml\n") == ["https://example.com/x.puml"]


class TestCollectIncludes:
    def test_relative_to_the_manuscript_folder(self, tmp_path):
        f = _write(tmp_path / "docs" / "defs.iuml", "!$a = 1\n")
        assert collect_includes("!include defs.iuml\n", str(tmp_path / "docs")) == [os.path.realpath(f)]

    def test_no_includes_gives_an_empty_list(self, tmp_path):
        assert collect_includes("@startuml\nA -> B\n@enduml\n", str(tmp_path)) == []
        assert collect_includes("!include <C4/C4_Container>\n", str(tmp_path)) == []

    def test_nested_includes_are_relative_to_the_including_file(self, tmp_path):
        a = _write(tmp_path / "lib" / "a.iuml", "!include b.iuml\n")
        b = _write(tmp_path / "lib" / "b.iuml", "!$a = 1\n")
        files = collect_includes("!include lib/a.iuml\n", str(tmp_path))
        assert files == [os.path.realpath(a), os.path.realpath(b)]

    def test_nested_includes_fall_back_to_the_manuscript_folder(self, tmp_path):
        _write(tmp_path / "lib" / "a.iuml", "!include common.iuml\n")
        common = _write(tmp_path / "common.iuml", "!$a = 1\n")
        files = collect_includes("!include lib/a.iuml\n", str(tmp_path))
        assert os.path.realpath(common) in files

    def test_a_file_included_twice_is_listed_once(self, tmp_path):
        _write(tmp_path / "a.iuml", "x\n")
        assert len(collect_includes("!include a.iuml\n!include a.iuml\n", str(tmp_path))) == 1

    def test_a_cycle_does_not_loop(self, tmp_path):
        _write(tmp_path / "a.iuml", "!include b.iuml\n")
        _write(tmp_path / "b.iuml", "!include a.iuml\n")
        assert len(collect_includes("!include a.iuml\n", str(tmp_path))) == 2

    def test_going_outside_the_manuscript_folder_is_an_error(self, tmp_path):
        _write(tmp_path / "outside.iuml", "x\n")
        docs = tmp_path / "docs"
        docs.mkdir()
        with pytest.raises(IncludeError, match="outside the manuscript folder"):
            collect_includes("!include ../outside.iuml\n", str(docs))

    def test_a_nested_include_going_outside_is_an_error(self, tmp_path):
        _write(tmp_path / "outside.iuml", "x\n")
        _write(tmp_path / "docs" / "a.iuml", "!include ../outside.iuml\n")
        with pytest.raises(IncludeError, match="outside the manuscript folder"):
            collect_includes("!include a.iuml\n", str(tmp_path / "docs"))

    def test_absolute_paths_are_an_error(self, tmp_path):
        target = _write(tmp_path / "x.iuml", "x\n")
        with pytest.raises(IncludeError, match="Absolute paths"):
            collect_includes("!include %s\n" % str(target).replace("\\", "/"), str(tmp_path))

    def test_urls_are_an_error(self, tmp_path):
        with pytest.raises(IncludeError, match="URLs"):
            collect_includes("!include https://example.com/x.puml\n", str(tmp_path))

    def test_a_missing_file_is_an_error(self, tmp_path):
        with pytest.raises(IncludeError, match="not found"):
            collect_includes("!include nothing.iuml\n", str(tmp_path))

    def test_too_deep_nesting_is_an_error(self, tmp_path):
        for i in range(12):
            _write(tmp_path / ("f%d.iuml" % i), "!include f%d.iuml\n" % (i + 1))
        _write(tmp_path / "f12.iuml", "x\n")
        with pytest.raises(IncludeError, match="nested more than"):
            collect_includes("!include f0.iuml\n", str(tmp_path))

    def test_a_symlink_pointing_outside_is_an_error(self, tmp_path):
        target = _write(tmp_path / "outside.iuml", "x\n")
        docs = tmp_path / "docs"
        docs.mkdir()
        try:
            os.symlink(str(target), str(docs / "link.iuml"))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available")
        with pytest.raises(IncludeError, match="outside the manuscript folder"):
            collect_includes("!include link.iuml\n", str(docs))


class TestCacheSuffix:
    def test_empty_without_includes(self, tmp_path):
        assert cache_suffix([], str(tmp_path)) == ""

    def test_changes_when_the_included_file_changes(self, tmp_path):
        f = _write(tmp_path / "a.iuml", "one\n")
        before = cache_suffix([str(f)], str(tmp_path))
        f.write_text("two\n", encoding="utf-8")
        assert cache_suffix([str(f)], str(tmp_path)) != before

    def test_is_the_same_when_the_folder_is_moved(self, tmp_path):
        a = _write(tmp_path / "one" / "docs" / "a.iuml", "same\n")
        b = _write(tmp_path / "two" / "docs" / "a.iuml", "same\n")
        assert cache_suffix([str(a)], str(tmp_path / "one" / "docs")) == cache_suffix([str(b)], str(tmp_path / "two" / "docs"))

    def test_changes_when_the_file_name_changes(self, tmp_path):
        a = _write(tmp_path / "a.iuml", "same\n")
        b = _write(tmp_path / "b.iuml", "same\n")
        assert cache_suffix([str(a)], str(tmp_path)) != cache_suffix([str(b)], str(tmp_path))


class _Fake:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def stub_tools(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(diagrams_mod, "find_system_java", lambda: sys.executable)
    monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", lambda: str(tmp_path / "plantuml.jar"))


def _renderer(tmp_path, docs=None):
    r = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
    if docs is not None:
        r.current_dir = str(docs)
        r.current_file = str(docs / "doc.md")
    return r


class TestSinglePath:
    def _capture(self, monkeypatch):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(kwargs.get("env"))
            return _Fake(0, "<svg>ok</svg>", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)
        return calls

    def test_include_path_is_the_manuscript_folder(self, monkeypatch, stub_tools, tmp_path):
        docs = tmp_path / "docs"
        _write(docs / "defs.iuml", "!$a = 1\n")
        calls = self._capture(monkeypatch)
        _renderer(tmp_path, docs)._plantuml_svg_path("@startuml\n!include defs.iuml\nA -> B\n@enduml\n")
        assert calls[0]["PLANTUML_INCLUDE_PATH"] == os.path.realpath(docs)
        assert calls[0]["PLANTUML_SECURITY_PROFILE"] == "ALLOWLIST"

    def test_no_include_path_without_file_includes(self, monkeypatch, stub_tools, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        calls = self._capture(monkeypatch)
        _renderer(tmp_path, docs)._plantuml_svg_path("@startuml\n!include <C4/C4_Container>\nA -> B\n@enduml\n")
        assert "PLANTUML_INCLUDE_PATH" not in calls[0]

    def test_editing_the_included_file_redraws_the_diagram(self, monkeypatch, stub_tools, tmp_path):
        docs = tmp_path / "docs"
        defs = _write(docs / "defs.iuml", "!$a = 1\n")
        calls = self._capture(monkeypatch)
        code = "@startuml\n!include defs.iuml\nA -> B\n@enduml\n"
        first = _renderer(tmp_path, docs)._plantuml_svg_path(code)
        again = _renderer(tmp_path, docs)._plantuml_svg_path(code)
        assert again == first and len(calls) == 1        # 変えなければ、キャッシュを使う
        defs.write_text("!$a = 2\n", encoding="utf-8")
        changed = _renderer(tmp_path, docs)._plantuml_svg_path(code)
        assert changed != first and len(calls) == 2      # 取り込んだファイルを直すと、描き直す

    def test_cache_key_without_includes_is_unchanged(self, monkeypatch, stub_tools, tmp_path):
        """ファイルを取り込まない図は、これまでと同じキャッシュのキーになる（既存のキャッシュを無駄にしない）。"""
        docs = tmp_path / "docs"
        docs.mkdir()
        self._capture(monkeypatch)
        r = _renderer(tmp_path, docs)
        code = "@startuml\nA -> B\n@enduml\n"
        expected, _ = r._diagram_cache_path("plantuml", PLANTUML_JAR_SHA256, code)
        assert r._plantuml_svg_path(code) == expected

    def test_includes_become_dependencies(self, monkeypatch, stub_tools, tmp_path):
        docs = tmp_path / "docs"
        defs = _write(docs / "defs.iuml", "!$a = 1\n")
        self._capture(monkeypatch)
        r = _renderer(tmp_path, docs)
        r.dependencies = set()
        r._plantuml_svg_path("@startuml\n!include defs.iuml\nA -> B\n@enduml\n")
        assert os.path.realpath(defs) in r.dependencies

    def test_a_blocked_include_stops_with_a_reason(self, monkeypatch, stub_tools, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        self._capture(monkeypatch)
        with diagnostics.collect() as c:
            with pytest.raises(SystemExit):
                _renderer(tmp_path, docs)._plantuml_svg_path("@startuml\n!include ../x.iuml\n@enduml\n")
        errors = [d for d in c.items if d.severity == "error"]
        assert errors and "outside the manuscript folder" in (errors[0].detail or "")


class TestBatchGroupsByFolder:
    def test_each_folder_that_includes_files_gets_its_own_process(self, monkeypatch, stub_tools, tmp_path):
        _write(tmp_path / "a" / "defs.iuml", '!$m = "A"\n')
        _write(tmp_path / "b" / "defs.iuml", '!$m = "B"\n')
        inc = "@startuml\n!include defs.iuml\nrectangle $m\n@enduml\n"
        plain = "@startuml\nA -> B\n@enduml\n"
        texts = [
            (str(tmp_path / "a" / "a.md"), "```plantuml\n%s```\n\n```plantuml\n%s```\n" % (inc, plain)),
            (str(tmp_path / "b" / "b.md"), "```plantuml\n%s```\n" % inc),
        ]
        calls = []
        delim = "===text-compositor-plantuml-batch-delimiter===\n"

        def fake_run(args, **kwargs):
            env = kwargs["env"]
            n = kwargs["input"].count("@startuml")
            calls.append((env.get("PLANTUML_INCLUDE_PATH"), n))
            return _Fake(0, "".join("<svg>%d</svg>%s" % (i, delim) for i in range(n)), "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        _renderer(tmp_path).prefetch_plantuml_diagrams(texts)
        by_dir = {d: n for d, n in calls}
        assert len(calls) == 3
        assert by_dir[os.path.realpath(tmp_path / "a")] == 1
        assert by_dir[os.path.realpath(tmp_path / "b")] == 1
        assert by_dir[None] == 1                       # ファイルを取り込まない図は、フォルダに分けない

    def test_diagrams_without_file_includes_still_use_a_single_process(self, monkeypatch, stub_tools, tmp_path):
        texts = [(str(tmp_path / "a.md"), "".join("```plantuml\n@startuml\nA -> B: %d\n@enduml\n```\n\n" % i for i in range(3)))]
        calls = []
        delim = "===text-compositor-plantuml-batch-delimiter===\n"

        def fake_run(args, **kwargs):
            calls.append(kwargs["env"].get("PLANTUML_INCLUDE_PATH"))
            return _Fake(0, "".join("<svg>%d</svg>%s" % (i, delim) for i in range(3)), "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)
        _renderer(tmp_path).prefetch_plantuml_diagrams(texts)
        assert calls == [None]


class TestRealPlantuml:
    """実際のplantuml.jarで確かめる。印（MARK_...）が、出力のSVGに出たら、そのファイルが読めた証拠になる。"""

    def _renderer(self, tmp_path, real_tools, docs):
        java, jar = real_tools
        r = _renderer(tmp_path, docs)
        r._plantuml_java_bin, r._plantuml_jar_path = java, jar
        return r

    def test_include_in_the_manuscript_folder_works_from_another_working_directory(self, real_tools, tmp_path, monkeypatch):
        docs = tmp_path / "docs"
        _write(docs / "defs.iuml", '!$mark = "MARK_DEFS"\n')
        monkeypatch.chdir(tmp_path)       # プロジェクトの直下から実行する（#622の再現手順）
        r = self._renderer(tmp_path, real_tools, docs)
        svg = r._plantuml_svg_path("@startuml\n!include defs.iuml\nrectangle $mark\n@enduml\n")
        assert "MARK_DEFS" in open(svg, encoding="utf-8").read()

    def test_nested_include_works(self, real_tools, tmp_path):
        docs = tmp_path / "docs"
        _write(docs / "lib" / "a.iuml", "!include b.iuml\n")
        _write(docs / "lib" / "b.iuml", '!$mark = "MARK_NESTED"\n')
        r = self._renderer(tmp_path, real_tools, docs)
        svg = r._plantuml_svg_path("@startuml\n!include lib/a.iuml\nrectangle $mark\n@enduml\n")
        assert "MARK_NESTED" in open(svg, encoding="utf-8").read()

    def test_editing_the_included_file_changes_the_picture(self, real_tools, tmp_path):
        docs = tmp_path / "docs"
        defs = _write(docs / "defs.iuml", '!$mark = "MARK_ONE"\n')
        code = "@startuml\n!include defs.iuml\nrectangle $mark\n@enduml\n"
        first = self._renderer(tmp_path, real_tools, docs)._plantuml_svg_path(code)
        defs.write_text('!$mark = "MARK_TWO"\n', encoding="utf-8")
        second = self._renderer(tmp_path, real_tools, docs)._plantuml_svg_path(code)
        assert "MARK_ONE" in open(first, encoding="utf-8").read()
        assert "MARK_TWO" in open(second, encoding="utf-8").read()

    def test_files_with_the_same_name_in_different_folders_are_not_mixed_up(self, real_tools, tmp_path):
        """include.pathは、JVMに1つだけ渡せる。同名のファイルを、フォルダごとに取り違えないこと（バッチをフォルダごとに分ける）。"""
        _write(tmp_path / "a" / "defs.iuml", '!$mark = "MARK_A"\n')
        _write(tmp_path / "b" / "defs.iuml", '!$mark = "MARK_B"\n')
        code = "@startuml\n!include defs.iuml\nrectangle $mark\n@enduml\n"
        texts = [(str(tmp_path / "a" / "a.md"), "```plantuml\n%s```\n" % code),
                 (str(tmp_path / "b" / "b.md"), "```plantuml\n%s```\n" % code)]
        r = self._renderer(tmp_path, real_tools, None)
        r.prefetch_plantuml_diagrams(texts)
        a_dir, b_dir = tmp_path / "a", tmp_path / "b"
        out = {}
        for d in (a_dir, b_dir):
            r2 = self._renderer(tmp_path, real_tools, d)
            out[d.name] = open(r2._plantuml_svg_path(code), encoding="utf-8").read()
        assert "MARK_A" in out["a"] and "MARK_B" not in out["a"]
        assert "MARK_B" in out["b"] and "MARK_A" not in out["b"]

    def test_include_outside_the_folder_is_blocked(self, real_tools, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        _write(tmp_path / "outside.iuml", '!$mark = "MARK_OUT"\n')
        java, jar = real_tools
        # 事前の確認（plantuml_include）を通らない書き方でも、PlantUML自身が拒否する（二重の防御）
        result = _renderer(tmp_path, docs)._run_plantuml_jar(
            java, jar, "@startuml\n!include ../outside.iuml\nrectangle $mark\n@enduml\n", include_dir=str(docs))
        assert "MARK_OUT" not in result.stdout
