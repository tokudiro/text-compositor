"""Structurizr（C4モデルのDSL。structurizr-cli経由でPlantUMLへ書き出し、既存のPlantUML+Smetana
パイプラインで描画する、#212）のテスト。実際のJava/structurizr-cli/plantuml.jarは呼ばず、
subprocess.runと取得系の関数をモックする（PlantUML/D2の既存テストと同じ方針）。"""
import os
import sys

import pytest

from text_compositor import diagnostics
import text_compositor.renderer_diagrams as diagrams_mod
from text_compositor.deps import PLANTUML_JAR_SHA256, STRUCTURIZR_CLI_SHA256
from text_compositor.renderer import TypstRenderer, _diagram_cache_key


def render(text, **kw):
    renderer = TypstRenderer(line_mapping="off", **kw)
    with diagnostics.collect() as c:
        out = renderer.render(text, filepath="doc.md")
    return out, c


class TestDisabledByDefault:
    def test_defaults_to_disabled_and_leaves_a_plain_code_block(self, monkeypatch):
        """既定はfalse（#212、内部で使うstructurizr-cli一式が約99MBあるため）。
        subprocessを一切呼ばないことも確認する（無効時は取得すら行わないはず）。"""
        def boom(*a, **k):
            raise AssertionError("must not invoke a subprocess when disabled")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", boom)

        out, c = render('```structurizr\nworkspace {}\n```\n')
        assert out == "```structurizr\nworkspace {}\n```\n\n"
        assert not any(d.severity == "error" for d in c.items)

    def test_disabled_warns_once(self, capsys):
        renderer = TypstRenderer(line_mapping="off", structurizr_enabled=False)
        renderer.render('```structurizr\na\n```\n\n```structurizr\nb\n```\n', filepath="doc.md")
        out = capsys.readouterr().out
        assert out.count("plugins.structurizr is disabled") == 1


class TestCacheKey:
    def test_version_combines_structurizr_and_plantuml_hashes(self):
        """structurizr-cliを更新してもplantuml.jarを更新しても、別キーになる必要がある
        （どちらの更新でも、同じ入力の古いSVGが使い回されると事故になるため）。"""
        v1 = f"{STRUCTURIZR_CLI_SHA256}:{PLANTUML_JAR_SHA256}"
        v2 = f"{STRUCTURIZR_CLI_SHA256}:deadbeef"
        assert _diagram_cache_key("structurizr", v1, "x") != _diagram_cache_key("structurizr", v2, "x")


class TestExtensionMapping:
    def test_dsl_extension_is_routed_to_structurizr(self):
        assert TypstRenderer.DIAGRAM_FILE_EXTS[".dsl"] == "structurizr"


def _fake_run_factory(view_names, plantuml_returncode=0, plantuml_stdout="<svg>ok</svg>", export_returncode=0):
    """structurizr-cliのexport呼び出し（-output配下にview_names個の.pumlを作る）と、
    plantuml.jarの呼び出し（標準入力のPlantUMLをそのままSVG風の文字列にして返す）を、
    引数列で見分けて模擬する。"""
    def fake_run(args, **kwargs):
        if "com.structurizr.cli.StructurizrCliApplication" in args:
            out_dir = args[args.index("-output") + 1]
            os.makedirs(out_dir, exist_ok=True)
            for name in view_names:
                with open(os.path.join(out_dir, f"structurizr-{name}.puml"), "w", encoding="utf-8") as f:
                    f.write(f"@startuml\ntitle {name}\n@enduml\n")
                with open(os.path.join(out_dir, f"structurizr-{name}-key.puml"), "w", encoding="utf-8") as f:
                    f.write("@startuml\n@enduml\n")   # 凡例ファイル（無視される想定）
            return _FakeCompletedProcess(export_returncode, "", "")
        assert "-jar" in args   # plantuml.jarの呼び出し
        return _FakeCompletedProcess(plantuml_returncode, plantuml_stdout, "")
    return fake_run


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def stub_tools(monkeypatch, tmp_path):
    """java・structurizr-cli・plantuml.jarの取得を、実際のダウンロードなしで解決させる。"""
    monkeypatch.setattr(diagrams_mod, "find_system_java", lambda: sys.executable)
    monkeypatch.setattr(diagrams_mod, "ensure_structurizr_cli", lambda: str(tmp_path / "structurizr-cli-lib"))
    monkeypatch.setattr(diagrams_mod, "ensure_plantuml_jar", lambda: str(tmp_path / "plantuml.jar"))


class TestSingleViewSucceeds:
    def test_exactly_one_view_renders_via_the_existing_plantuml_pipeline(self, monkeypatch, stub_tools, tmp_path):
        monkeypatch.setattr(diagrams_mod.subprocess, "run", _fake_run_factory(["SystemContext"]))
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        with diagnostics.collect() as c:
            out = renderer.render('```structurizr\nworkspace { model {} views {} }\n```\n', filepath="doc.md")
        assert "#fit-image(" in out or "#image(" in out
        assert not any(d.severity == "error" for d in c.items)

    def test_the_svg_is_cached_and_not_re_rendered(self, monkeypatch, stub_tools, tmp_path):
        calls = []
        real_fake = _fake_run_factory(["SystemContext"])

        def counting_fake(args, **kwargs):
            calls.append(args)
            return real_fake(args, **kwargs)
        monkeypatch.setattr(diagrams_mod.subprocess, "run", counting_fake)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        code = '```structurizr\nworkspace { model {} views {} }\n```\n'
        with diagnostics.collect():
            renderer.render(code, filepath="doc.md")
        first_call_count = len(calls)
        with diagnostics.collect():
            renderer.render(code, filepath="doc.md")
        assert len(calls) == first_call_count   # 2回目は、subprocessを呼ばない（キャッシュ済み）


class TestMultipleViewsFailFast:
    def test_two_views_is_a_fail_fast_error_not_a_silent_choice(self, monkeypatch, stub_tools, tmp_path):
        """#212の本題: structurizr-cliはCLI引数で1つだけ選べないため、複数ビューは
        エラーにする（どれかを黙って選ぶ、両方を握りつぶす、はいずれも避ける）。"""
        monkeypatch.setattr(diagrams_mod.subprocess, "run", _fake_run_factory(["SystemContext", "Containers"]))
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                renderer.render('```structurizr\nworkspace {}\n```\n', filepath="doc.md")
        errors = [d for d in c.items if d.severity == "error"]
        assert errors and "2 views" in errors[0].detail

    def test_zero_views_is_also_a_fail_fast_error(self, monkeypatch, stub_tools, tmp_path):
        monkeypatch.setattr(diagrams_mod.subprocess, "run", _fake_run_factory([]))
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                renderer.render('```structurizr\nworkspace {}\n```\n', filepath="doc.md")
        errors = [d for d in c.items if d.severity == "error"]
        assert errors and "0 views" in errors[0].detail


class TestStructurizrCliFailure:
    def test_invalid_dsl_fails_fast_with_the_tools_own_message(self, monkeypatch, stub_tools, tmp_path):
        def fake_run(args, **kwargs):
            if "com.structurizr.cli.StructurizrCliApplication" in args:
                return _FakeCompletedProcess(1, "", "StructurizrDslParserException: bad token at line 1")
            raise AssertionError("plantuml.jar must not be invoked when structurizr-cli itself failed")
        monkeypatch.setattr(diagrams_mod.subprocess, "run", fake_run)

        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off", structurizr_enabled=True)
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                renderer.render('```structurizr\nnot valid dsl\n```\n', filepath="doc.md")
        errors = [d for d in c.items if d.severity == "error"]
        assert errors and "StructurizrDslParserException" in errors[0].detail
