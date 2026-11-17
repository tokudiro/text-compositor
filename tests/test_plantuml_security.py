"""plantuml.jarの、ファイルとURLへのアクセスを、ALLOWLISTで遮断する設定（#622）のテスト。

単体テストは、subprocess.runをモックして、渡す環境変数を確かめる。統合テストは、実際のJavaと
plantuml.jarで、プロジェクトの外のファイルが読めないことと、標準ライブラリが使えることを確かめる
（Javaかjarがキャッシュに無いときは、ダウンロードせずにスキップする）。"""
import os

import pytest

import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor import diagnostics
from text_compositor.renderer import TypstRenderer


class _Fake:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _renderer(tmp_path):
    return TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)


class TestEnvironmentPassedToPlantuml:
    def _capture(self, monkeypatch):
        seen = {}

        def fake_run(args, **kwargs):
            seen["env"] = kwargs.get("env")
            return _Fake(0, "<svg></svg>", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)
        return seen

    def test_single_run_uses_allowlist(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PLANTUML_SECURITY_PROFILE", raising=False)
        seen = self._capture(monkeypatch)
        _renderer(tmp_path)._run_plantuml_jar("java", "plantuml.jar", "@startuml\n@enduml\n")
        assert seen["env"]["PLANTUML_SECURITY_PROFILE"] == "ALLOWLIST"

    def test_batch_run_uses_allowlist(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PLANTUML_SECURITY_PROFILE", raising=False)
        seen = self._capture(monkeypatch)
        _renderer(tmp_path)._run_plantuml_batch("java", "plantuml.jar", ["@startuml\n@enduml\n"])
        assert seen["env"]["PLANTUML_SECURITY_PROFILE"] == "ALLOWLIST"

    @pytest.mark.parametrize("profile", ["UNSECURE", "LEGACY", "INTERNET", "SANDBOX", ""])
    def test_a_profile_from_the_caller_environment_is_overridden(self, monkeypatch, tmp_path, profile):
        monkeypatch.setenv("PLANTUML_SECURITY_PROFILE", profile)
        seen = self._capture(monkeypatch)
        _renderer(tmp_path)._run_plantuml_jar("java", "plantuml.jar", "@startuml\n@enduml\n")
        assert seen["env"]["PLANTUML_SECURITY_PROFILE"] == "ALLOWLIST"

    def test_variables_that_widen_the_allowed_paths_are_removed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PLANTUML_ALLOWLIST_PATH", str(tmp_path))
        monkeypatch.setenv("PLANTUML_INCLUDE_PATH", str(tmp_path))
        seen = self._capture(monkeypatch)
        _renderer(tmp_path)._run_plantuml_batch("java", "plantuml.jar", ["@startuml\n@enduml\n"])
        assert "PLANTUML_ALLOWLIST_PATH" not in seen["env"]
        assert "PLANTUML_INCLUDE_PATH" not in seen["env"]

    def test_other_variables_are_kept(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEXT_COMPOSITOR_TEST_MARKER", "kept")
        seen = self._capture(monkeypatch)
        _renderer(tmp_path)._run_plantuml_jar("java", "plantuml.jar", "@startuml\n@enduml\n")
        assert seen["env"]["TEXT_COMPOSITOR_TEST_MARKER"] == "kept"


def _error_detail(renderer, tool, output):
    with diagnostics.collect() as c:
        renderer._diagram_error(tool, output)
    errors = [d for d in c.items if d.severity == "error"]
    assert len(errors) == 1
    return errors[0].detail or ""


class TestHintForBlockedInclude:
    @pytest.mark.parametrize("tool", ["PlantUML", "Structurizr"])
    @pytest.mark.parametrize("output", ["ERROR\n1\ncannot include defs.iuml", "ERROR 1 Cannot open URL"])
    def test_blocked_include_adds_a_hint(self, tmp_path, tool, output):
        detail = _error_detail(_renderer(tmp_path), tool, output)
        assert "ALLOWLIST" in detail
        assert "#622" in detail
        assert output.strip() in detail   # 元の出力は、そのまま残す

    def test_other_errors_get_no_hint(self, tmp_path):
        assert "ALLOWLIST" not in _error_detail(_renderer(tmp_path), "PlantUML", "Syntax Error?")

    def test_other_tools_get_no_hint(self, tmp_path):
        assert "ALLOWLIST" not in _error_detail(_renderer(tmp_path), "D2", "cannot include x")


class TestRealPlantumlBlocksFilesAndUrls:
    """実際のplantuml.jarで確かめる。印（MARK_...）が、出力のSVGに出たら、そのファイルが読めた証拠になる。"""

    def test_file_outside_the_project_is_not_read(self, real_tools, tmp_path, monkeypatch):
        java, jar = real_tools
        monkeypatch.setenv("PLANTUML_SECURITY_PROFILE", "UNSECURE")  # 呼び出し元が緩めても、効かない
        outside = tmp_path / "outside" / "secret.iuml"
        outside.parent.mkdir()
        outside.write_text('!$mark = "MARK_SECRET"\n', encoding="utf-8")
        code = "@startuml\n!include %s\nrectangle $mark\n@enduml\n" % str(outside).replace("\\", "/")
        result = _renderer(tmp_path)._run_plantuml_jar(java, jar, code)
        assert "MARK_SECRET" not in result.stdout
        assert result.returncode != 0

    def test_relative_file_in_the_working_directory_is_not_read(self, real_tools, tmp_path, monkeypatch):
        java, jar = real_tools
        (tmp_path / "defs.iuml").write_text('!$mark = "MARK_LOCAL"\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        code = "@startuml\n!include defs.iuml\nrectangle $mark\n@enduml\n"
        result = _renderer(tmp_path)._run_plantuml_jar(java, jar, code)
        assert "MARK_LOCAL" not in result.stdout
        assert result.returncode != 0

    def test_url_include_is_blocked(self, real_tools, tmp_path):
        java, jar = real_tools
        code = "@startuml\n!include https://example.invalid/x.puml\nrectangle MARK_URL\n@enduml\n"
        result = _renderer(tmp_path)._run_plantuml_jar(java, jar, code)
        assert result.returncode != 0

    def test_standard_library_still_works(self, real_tools, tmp_path):
        java, jar = real_tools
        code = '@startuml\n!include <C4/C4_Container>\nPerson(a, "MARK_STD")\n@enduml\n'
        result = _renderer(tmp_path)._run_plantuml_jar(java, jar, code)
        assert result.returncode == 0
        assert "MARK_STD" in result.stdout

    def test_batch_also_blocks_files(self, real_tools, tmp_path):
        java, jar = real_tools
        outside = tmp_path / "secret.iuml"
        outside.write_text('!$mark = "MARK_SECRET"\n', encoding="utf-8")
        code = "@startuml\n!include %s\nrectangle $mark\n@enduml\n" % str(outside).replace("\\", "/")
        returncode, parts, _ = _renderer(tmp_path)._run_plantuml_batch(java, jar, [code])
        assert returncode != 0
        assert "MARK_SECRET" not in "".join(parts)
