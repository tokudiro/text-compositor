"""javaプロセスの文字コード（#306）のテスト。

PlantUML本体（`_run_plantuml_jar`/`_run_plantuml_batch`）とstructurizr-cli（`_structurizr_dsl_to_plantuml`）
のjava起動コマンドに、JVM自体の文字コードをUTF-8へ固定するオプション
（`-Dfile.encoding`/`-Dstdin.encoding`/`-Dstdout.encoding`/`-Dstderr.encoding`）が
明示的に付くことを確認する。

引数の確認は、他のPlantUML/Structurizrのテストと同じ方針でsubprocess.runをモックして行う。
それだけでは「JVM側が実際にUTF-8として解釈するか」までは確認できないため、実際のJavaが
使える環境（システムJava、またはObunzu同梱Java）でのみ、日本語ラベルを含む図を実際に描画し、
SVG出力に文字化けなくラベルが含まれることも確認する（find_system_browser()を条件に実ブラウザで
描画するtest_mermaid_resident.pyのTestRealBrowserと同じ方針。無ければskip、追加のダウンロードは
発生させない）。"""
import os
import sys

import pytest

import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor.deps import bundled_java_bin, find_system_java
from text_compositor.renderer import TypstRenderer
from text_compositor.renderer_diagrams import _JAVA_UTF8_ENCODING_OPTS


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def stub_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(diagrams_mod, "find_system_java", lambda: sys.executable)
    monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", lambda: str(tmp_path / "plantuml.jar"))
    monkeypatch.setattr(diagrams_mod, "ensure_structurizr_cli", lambda: str(tmp_path / "structurizr-cli-lib"))


class TestPlantumlJarInvocationSetsUtf8Encoding:
    def test_single_diagram_invocation_includes_the_encoding_opts(self, monkeypatch, stub_tools, tmp_path):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return _FakeCompletedProcess(0, "<svg>ok</svg>", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        renderer.render("```plantuml\n@startuml\nA -> B: 1\n@enduml\n```\n", filepath="doc.md")

        assert len(calls) == 1
        args = calls[0]
        for opt in _JAVA_UTF8_ENCODING_OPTS:
            assert opt in args
        # -jarより前（javaコマンド自身へのオプション）に置かれている必要がある
        assert args.index(_JAVA_UTF8_ENCODING_OPTS[0]) < args.index("-jar")

    def test_batch_invocation_includes_the_encoding_opts(self, monkeypatch, stub_tools, tmp_path):
        calls = []
        delim = "===text-compositor-plantuml-batch-delimiter===\n"

        def fake_run(args, **kwargs):
            calls.append(args)
            return _FakeCompletedProcess(0, f"<svg>1</svg>{delim}<svg>2</svg>{delim}", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        text = (
            "```plantuml\n@startuml\nA -> B: 1\n@enduml\n```\n\n"
            "```plantuml\n@startuml\nB -> C: 2\n@enduml\n```\n"
        )
        renderer.prefetch_plantuml_diagrams([("doc.md", text)])

        assert len(calls) == 1
        for opt in _JAVA_UTF8_ENCODING_OPTS:
            assert opt in calls[0]


class TestStructurizrCliInvocationSetsUtf8Encoding:
    def test_dsl_to_plantuml_conversion_includes_the_encoding_opts(self, monkeypatch, stub_tools, tmp_path):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            out_dir = args[args.index("-output") + 1]
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "structurizr-SystemContext.puml"), "w", encoding="utf-8") as f:
                f.write("@startuml\ntitle SystemContext\n@enduml\n")
            return _FakeCompletedProcess(0, "", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        renderer._structurizr_dsl_to_plantuml("workspace { model {} views {} }\n")

        assert len(calls) == 1
        args = calls[0]
        for opt in _JAVA_UTF8_ENCODING_OPTS:
            assert opt in args
        assert args.index(_JAVA_UTF8_ENCODING_OPTS[0]) < args.index("-cp")


def _has_real_java():
    return bool(find_system_java() or bundled_java_bin())


@pytest.mark.skipif(not _has_real_java(), reason="needs a real local Java 11+ (system or Obunzu-bundled)")
class TestRealJavaRendersJapaneseLabelsCorrectly:
    """#306の本来の懸念（JVM自体が入出力をUTF-8以外で解釈し、日本語ラベルが文字化けする）を、
    実際のjava+plantuml.jar/structurizr-cliで確認する。plantuml.jar/structurizr-cli自体は、
    既にローカルキャッシュにあるものだけを使い（無ければskip相当でensure_*が取得するが、
    通常はネットワークアクセスは発生しない）、追加のJREダウンロードは行わない。"""

    LABEL = "こんにちは"

    def test_plantuml_diagram_keeps_the_japanese_label_intact(self, tmp_path):
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        code = f"@startuml\nA -> B : {self.LABEL}\n@enduml\n"
        svg_path = renderer._plantuml_svg_path(code)
        with open(svg_path, "r", encoding="utf-8") as f:
            svg = f.read()
        assert self.LABEL in svg

    def test_structurizr_diagram_keeps_the_japanese_label_intact(self, tmp_path):
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        dsl = (
            "workspace {\n"
            "  model {\n"
            f'    u = person "{self.LABEL}"\n'
            '    s = softwareSystem "System"\n'
            "    u -> s\n"
            "  }\n"
            "  views {\n"
            "    systemContext s {\n"
            "      include *\n"
            "      autoLayout\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        svg_path = renderer._structurizr_svg_path(dsl)
        with open(svg_path, "r", encoding="utf-8") as f:
            svg = f.read()
        assert self.LABEL in svg
