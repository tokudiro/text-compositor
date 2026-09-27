"""複数のPlantUML/Structurizr図を1回のJVM起動でまとめて事前描画する機能（#307）のテスト。
実際のJava/plantuml.jar/structurizr-cliは呼ばず、subprocess.runをモックする
（PlantUML/Structurizrの既存テストと同じ方針）。"""
import os
import sys

import pytest

import text_compositor.build as build
import text_compositor.project as project_mod
from text_compositor import diagnostics
import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor.deps import PLANTUML_JAR_SHA256, STRUCTURIZR_CLI_SHA256
from text_compositor.project import _build_one
from text_compositor.renderer import TypstRenderer


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def stub_tools(monkeypatch, tmp_path):
    """java・plantuml.jar・structurizr-cliの取得を、実際のダウンロードなしで解決させる。"""
    monkeypatch.setattr(diagrams_mod, "find_system_java", lambda: sys.executable)
    monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", lambda: str(tmp_path / "plantuml.jar"))
    monkeypatch.setattr(diagrams_mod, "ensure_structurizr_cli", lambda: str(tmp_path / "structurizr-cli-lib"))


def _fake_batch_run_factory(svgs, returncode=0):
    """-pipe -pipedelimitorでのバッチ呼び出しを模擬する。svgsはコード数と同じ順のSVG文字列のリスト。"""
    delim = "===text-compositor-plantuml-batch-delimiter===\n"

    def fake_run(args, **kwargs):
        assert "-pipedelimitor" in args
        assert "-jar" in args
        stdout = "".join(s + delim for s in svgs)
        return _FakeCompletedProcess(returncode, stdout, "")
    return fake_run


class TestBatchesMultiplePlantumlFences:
    def test_multiple_fences_use_a_single_subprocess_call(self, monkeypatch, stub_tools, tmp_path):
        calls = []

        def counting_fake(args, **kwargs):
            calls.append(args)
            return _fake_batch_run_factory(["<svg>1</svg>", "<svg>2</svg>", "<svg>3</svg>"])(args, **kwargs)
        monkeypatch.setattr(diagrams_mod.subprocess, "run", counting_fake)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        text = (
            "```plantuml\n@startuml\nA -> B: 1\n@enduml\n```\n\n"
            "```plantuml\n@startuml\nB -> C: 2\n@enduml\n```\n\n"
            "```plantuml\n@startuml\nC -> D: 3\n@enduml\n```\n"
        )
        renderer.prefetch_plantuml_diagrams([("doc.md", text)])
        assert len(calls) == 1   # 3個の図でも、JVM起動は1回だけ

        # 事前フェーズが書いたキャッシュが、通常の描画経路でそのまま使われる（呼ばれたら失敗にする）
        def boom(*a, **k):
            raise AssertionError("must not invoke a subprocess again; the batch should have cached all fences")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", boom)
        with diagnostics.collect() as c:
            out = renderer.render(text, filepath="doc.md")
        assert out.count("#fit-image(") + out.count("#image(") == 3
        assert not any(d.severity == "error" for d in c.items)

    def test_already_cached_diagrams_are_not_included_in_the_batch(self, monkeypatch, stub_tools, tmp_path):
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        code = "@startuml\nA -> B: hi\n@enduml\n"
        cache_path, _ = renderer._diagram_cache_path("plantuml", PLANTUML_JAR_SHA256, code)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write("<svg>cached</svg>")

        def boom(*a, **k):
            raise AssertionError("must not invoke a subprocess when the diagram is already cached")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", boom)

        renderer.prefetch_plantuml_diagrams([("doc.md", f"```plantuml\n{code}```\n")])

    def test_disabled_plugins_do_nothing(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise AssertionError("must not invoke a subprocess when both plugins are disabled")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", boom)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off",
                                  plantuml_enabled=False, structurizr_enabled=False)
        renderer.prefetch_plantuml_diagrams([("doc.md", "```plantuml\n@startuml\nA -> B\n@enduml\n```\n")])


class TestBatchFailureFallsBackToIndividualReruns:
    def test_one_bad_diagram_is_fail_fast_with_its_own_error_after_individual_rerun(self, monkeypatch, stub_tools, tmp_path):
        """バッチのstderrは最初のエラーしか含まず、どの図かは特定できない（#307のissueコメント参照）
        ため、バッチ失敗時は1件ずつ個別再実行して、失敗した図だけを既存のFail-fast診断で報告する。"""
        batch_calls = []
        individual_calls = []

        def fake_run(args, **kwargs):
            if "-pipedelimitor" in args:
                batch_calls.append(args)
                return _FakeCompletedProcess(200, "", "ERROR\n1\nSyntax Error?\n")
            individual_calls.append(args)
            # 2番目に個別実行される図だけ失敗させる
            if len(individual_calls) == 2:
                return _FakeCompletedProcess(1, "", "Syntax Error? (Assumed diagram type: sequence)")
            return _FakeCompletedProcess(0, f"<svg>ok{len(individual_calls)}</svg>", "")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", plantuml_enabled=True)
        text = (
            "```plantuml\n@startuml\nA -> B: 1\n@enduml\n```\n\n"
            "```plantuml\n@startuml\nbad syntax ][\n@enduml\n```\n\n"
            "```plantuml\n@startuml\nC -> D: 3\n@enduml\n```\n"
        )
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                renderer.prefetch_plantuml_diagrams([("doc.md", text)])
        assert len(batch_calls) == 1
        assert len(individual_calls) == 2   # 1件目は成功、2件目で失敗して即終了（3件目は試さない）
        errors = [d for d in c.items if d.severity == "error"]
        assert errors and "Syntax Error?" in errors[0].detail


class TestStructurizrIncludedInBatch:
    def test_structurizr_dsl_conversion_runs_individually_but_plantuml_step_is_batched(self, monkeypatch, stub_tools, tmp_path):
        """DSL->PlantUML変換（structurizr-cli）はバッチ化できないため図ごとに1回起動するが、
        後段のPlantUML->SVG変換は他のPlantUML図とまとめて1回のJVM起動になる。"""
        structurizr_calls = []
        batch_calls = []

        def fake_run(args, **kwargs):
            if "com.structurizr.cli.StructurizrCliApplication" in args:
                structurizr_calls.append(args)
                out_dir = args[args.index("-output") + 1]
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "structurizr-SystemContext.puml"), "w", encoding="utf-8") as f:
                    f.write("@startuml\ntitle SystemContext\n@enduml\n")
                return _FakeCompletedProcess(0, "", "")
            if "-pipedelimitor" in args:
                batch_calls.append(args)
                return _fake_batch_run_factory(["<svg>plantuml</svg>", "<svg>structurizr</svg>"])(args, **kwargs)
            raise AssertionError(f"unexpected subprocess call: {args}")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off",
                                  plantuml_enabled=True, structurizr_enabled=True)
        text = (
            "```plantuml\n@startuml\nA -> B: 1\n@enduml\n```\n\n"
            "```structurizr\nworkspace { model {} views {} }\n```\n"
        )
        renderer.prefetch_plantuml_diagrams([("doc.md", text)])
        assert len(structurizr_calls) == 1
        assert len(batch_calls) == 1   # PlantUML本体・Structurizr変換後の両方が同じ1回のJVM起動に入る

    def test_cache_key_matches_the_existing_structurizr_cache_version(self, monkeypatch, stub_tools, tmp_path):
        def fake_run(args, **kwargs):
            if "com.structurizr.cli.StructurizrCliApplication" in args:
                out_dir = args[args.index("-output") + 1]
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "structurizr-SystemContext.puml"), "w", encoding="utf-8") as f:
                    f.write("@startuml\ntitle SystemContext\n@enduml\n")
                return _FakeCompletedProcess(0, "", "")
            return _fake_batch_run_factory(["<svg>structurizr</svg>"])(args, **kwargs)
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        code = "workspace { model {} views {} }\n"
        renderer.prefetch_plantuml_diagrams([("doc.md", f"```structurizr\n{code}```\n")])

        version = f"{STRUCTURIZR_CLI_SHA256}:{PLANTUML_JAR_SHA256}"
        cache_path, _ = renderer._diagram_cache_path("structurizr", version, code)
        assert os.path.exists(cache_path)

        def boom(*a, **k):
            raise AssertionError("must not invoke a subprocess; the normal rendering path should hit the prefetched cache")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", boom)
        with diagnostics.collect() as c:
            out = renderer.render(f"```structurizr\n{code}```\n", filepath="doc.md")
        assert "#fit-image(" in out or "#image(" in out
        assert not any(d.severity == "error" for d in c.items)


class TestBuildProjectCollectsAcrossChapters:
    def test_prefetch_is_called_once_with_every_markdown_chapter_and_skips_aggregate(
            self, monkeypatch, tmp_path):
        """_build_project（project.py）が、複数のMarkdown章をまとめて1回のprefetch呼び出しに
        渡すことを確認する（#307）。aggregate章・Markdown以外の拡張子は対象に含めない。"""
        (tmp_path / "a.md").write_text("```plantuml\n@startuml\nA -> B\n@enduml\n```\n", encoding="utf-8")
        (tmp_path / "b.md").write_text("```plantuml\n@startuml\nB -> C\n@enduml\n```\n", encoding="utf-8")
        (tmp_path / "c.dot").write_text("digraph { a -> b }\n", encoding="utf-8")
        (tmp_path / "agg").mkdir()
        (tmp_path / "agg" / "x.yaml").write_text("title: X\nbody: y\n", encoding="utf-8")

        monkeypatch.setattr(project_mod, "_compile_and_cleanup", lambda typst_code, *a, **k: None)
        captured = []
        monkeypatch.setattr(TypstRenderer, "prefetch_plantuml_diagrams",
                             lambda self, file_texts: captured.append(list(file_texts)))

        cfg = tmp_path / "text-compositor.config.yaml"
        cfg.write_text(
            "inputs:\n  dir: \".\"\n"
            "chapters:\n  - a.md\n  - b.md\n  - c.dot\n  - aggregate: agg\n", encoding="utf-8")
        tool_dir = os.path.dirname(os.path.abspath(build.__file__))
        _build_one(tool_dir, str(tmp_path), "fonts", str(cfg))

        assert len(captured) == 1
        filepaths = sorted(os.path.basename(p) for p, _text in captured[0])
        assert filepaths == ["a.md", "b.md"]   # c.dotとaggregate配下は対象外
