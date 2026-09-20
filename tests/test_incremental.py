"""--if-changed（更新日時による生成スキップ）と--clean/--clean-cacheのリグレッションテスト（#151）。"""
import os
import sys

import pytest

import text_compositor.build as build
import text_compositor.project as project_mod
from text_compositor.changes import _is_up_to_date
from text_compositor.config import _load_project_config
from text_compositor.project import _build_one


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def set_mtime(path, seconds):
    ns = int(seconds * 1e9)
    os.utime(path, ns=(ns, ns))


@pytest.fixture
def project(tmp_path):
    """全入力の更新日時を1000秒、出力PDFを2000秒に固定した、ビルド済みのプロジェクト。"""
    cfg = str(tmp_path / "text-compositor.config.yaml")
    write(cfg, "chapters:\n  - a.md\n")
    write(str(tmp_path / "inputs" / "a.md"), "# A\n")
    pdf = str(tmp_path / "outputs" / "System_Specification.pdf")
    write(pdf)
    for p in (cfg, str(tmp_path / "inputs" / "a.md")):
        set_mtime(p, 1000)
    set_mtime(pdf, 2000)
    return tmp_path, cfg, pdf


@pytest.fixture
def tool_dir(tmp_path_factory):
    """同梱テンプレートとbuild.py自身の更新日時を、実行時点に左右されない古い値に固定した仮のtool_dir。"""
    d = tmp_path_factory.mktemp("tool")
    tpl = str(d / "templates" / "template.typ")
    write(tpl)
    set_mtime(tpl, 500)
    for name in ("build.py", "renderer.py"):
        write(str(d / name))
        set_mtime(str(d / name), 500)
    return str(d)


def check(tmp_path, cfg, tool_dir):
    project_dir, config, _ = _load_project_config(cfg)
    return _is_up_to_date(tool_dir, cfg, project_dir, config)


class TestIsUpToDate:
    def test_up_to_date_when_output_is_newest(self, project, tool_dir):
        tmp_path, cfg, pdf = project
        up_to_date, out = check(tmp_path, cfg, tool_dir)
        assert up_to_date
        assert out == os.path.normpath(pdf)

    def test_stale_when_output_missing(self, project, tool_dir):
        tmp_path, cfg, pdf = project
        os.remove(pdf)
        assert check(tmp_path, cfg, tool_dir)[0] is False

    @pytest.mark.parametrize("rel", ["text-compositor.config.yaml", os.path.join("inputs", "a.md")])
    def test_stale_when_input_or_config_is_newer(self, project, tool_dir, rel):
        tmp_path, cfg, pdf = project
        set_mtime(str(tmp_path / rel), 3000)
        assert check(tmp_path, cfg, tool_dir)[0] is False

    def test_stale_when_new_input_file_is_added(self, project, tool_dir):
        tmp_path, cfg, pdf = project
        b = str(tmp_path / "inputs" / "b.csv")
        write(b)
        set_mtime(b, 3000)
        assert check(tmp_path, cfg, tool_dir)[0] is False

    def test_stale_when_custom_typ_template_is_newer(self, tmp_path, tool_dir):
        cfg = str(tmp_path / "c.yaml")
        write(cfg, "template:\n  path: my/tpl.typ\nchapters: [a.md]\n")
        tpl = str(tmp_path / "my" / "tpl.typ")
        write(tpl)
        pdf = str(tmp_path / "outputs" / "System_Specification.pdf")
        write(pdf)
        set_mtime(cfg, 1000)
        set_mtime(tpl, 3000)
        set_mtime(pdf, 2000)
        assert check(tmp_path, cfg, tool_dir)[0] is False

    @pytest.mark.parametrize("module", ["build.py", "renderer.py"])
    def test_stale_when_any_tool_module_is_newer(self, project, tool_dir, module):
        """ツールは複数のモジュールに分かれている（#157）。build.py以外の更新でも、再生成する。"""
        tmp_path, cfg, pdf = project
        set_mtime(os.path.join(tool_dir, module), 3000)
        assert check(tmp_path, cfg, tool_dir)[0] is False

    def test_intermediate_files_do_not_make_it_stale(self, project, tool_dir):
        tmp_path, cfg, pdf = project
        tmp_file = str(tmp_path / ".text-compositor" / "temp_build.typ")
        write(tmp_file)
        set_mtime(tmp_file, 3000)
        assert check(tmp_path, cfg, tool_dir)[0] is True

    def test_other_pdf_in_project_dir_is_ignored(self, project, tool_dir):
        """--config-listで同じproject_dirを共有する別configのPDFで、互いに常に再生成にならないこと。"""
        tmp_path, cfg, pdf = project
        other = str(tmp_path / "other_outputs" / "other.pdf")
        write(other)
        set_mtime(other, 9000)
        assert check(tmp_path, cfg, tool_dir)[0] is True


class TestBuildOneSkips:
    def test_skip_logs_and_does_not_touch_work_dir(self, project, tool_dir, capsys, monkeypatch):
        tmp_path, cfg, pdf = project
        monkeypatch.setattr(project_mod, "_is_up_to_date", lambda *a: (True, pdf))
        # スキップ時はrepo_root/font_dirを使わない。触ればNoneで即座に失敗する。
        _build_one(tool_dir, None, None, cfg, if_changed=True)
        assert "Skipped (up to date)" in capsys.readouterr().out
        assert not (tmp_path / ".text-compositor").exists()

    def test_without_flag_never_checks_freshness(self, project, tool_dir, monkeypatch):
        tmp_path, cfg, pdf = project

        def boom(*a):
            raise AssertionError("checked")
        monkeypatch.setattr(project_mod, "_is_up_to_date", boom)
        # 既定は従来どおり常に再生成する。判定関数は呼ばれず、後続の処理（ここでは_resolve_variables以降）へ進む。
        monkeypatch.setattr(project_mod, "_resolve_variables", lambda c: (_ for _ in ()).throw(RuntimeError("proceeded")))
        with pytest.raises(RuntimeError, match="proceeded"):
            _build_one(tool_dir, None, None, cfg)


class TestClean:
    @pytest.fixture
    def built(self, project):
        tmp_path, cfg, pdf = project
        work = tmp_path / ".text-compositor"
        write(str(work / "temp_build.typ"))
        write(str(work / "_template.typ"))
        write(str(work / "cache" / "svg_abc.svg"))
        return tmp_path, cfg, pdf, work

    def test_clean_removes_pdf_and_intermediates_but_keeps_cache(self, built):
        tmp_path, cfg, pdf, work = built
        build._clean_one(cfg, include_cache=False)
        assert not os.path.exists(pdf)
        assert not (work / "temp_build.typ").exists()
        assert not (work / "_template.typ").exists()
        assert (work / "cache" / "svg_abc.svg").exists()

    def test_clean_cache_also_removes_cache_and_empty_work_dir(self, built):
        tmp_path, cfg, pdf, work = built
        build._clean_one(cfg, include_cache=True)
        assert not os.path.exists(pdf)
        assert not work.exists()

    def test_inputs_and_config_are_never_removed(self, built):
        tmp_path, cfg, pdf, work = built
        build._clean_one(cfg, include_cache=True)
        assert os.path.exists(cfg)
        assert (tmp_path / "inputs" / "a.md").exists()

    def test_clean_is_noop_when_nothing_to_remove(self, project, capsys):
        tmp_path, cfg, pdf = project
        os.remove(pdf)
        build._clean_one(cfg, include_cache=True)
        assert "Cleaned 0 item(s)" in capsys.readouterr().out


class TestArgs:
    def parse(self, monkeypatch, *argv):
        monkeypatch.setattr(sys, "argv", ["text-compositor", *argv])
        return build.parse_args()

    def test_clean_cache_implies_clean(self, monkeypatch):
        args = self.parse(monkeypatch, "--clean-cache")
        assert args.clean and args.clean_cache

    def test_defaults_keep_existing_behavior(self, monkeypatch):
        args = self.parse(monkeypatch)
        assert not args.if_changed and not args.clean

    @pytest.mark.parametrize("extra", [["--watch"], ["--if-changed"], ["--check-env"]])
    def test_clean_conflicts(self, monkeypatch, extra):
        with pytest.raises(SystemExit) as e:
            self.parse(monkeypatch, "--clean", *extra)
        assert e.value.code == 2

    def test_if_changed_conflicts_with_watch(self, monkeypatch):
        with pytest.raises(SystemExit) as e:
            self.parse(monkeypatch, "--if-changed", "--watch")
        assert e.value.code == 2
