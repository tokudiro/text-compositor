"""--watch（保存即再生成、#30）のリグレッションテスト。"""
import os

import pytest

import text_compositor.build as build
from text_compositor.changes import _watch_snapshot, _watch_targets
import time


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.fixture
def project(tmp_path):
    cfg = str(tmp_path / "text-compositor.config.yaml")
    write(cfg, "chapters:\n  - a.md\n")
    write(str(tmp_path / "inputs" / "a.md"), "# A\n")
    return tmp_path, cfg


class TestWatchTargets:
    def test_roots_include_project_and_inputs_and_config(self, project):
        tmp_path, cfg = project
        roots, ignore, files = _watch_targets(str(tmp_path), cfg)
        assert str(tmp_path) in roots
        assert os.path.join(str(tmp_path), "inputs") in roots
        assert cfg in files

    def test_outputs_dir_is_ignored(self, project):
        tmp_path, cfg = project
        _, ignore, _ = _watch_targets(str(tmp_path), cfg)
        assert os.path.join(str(tmp_path), "outputs") in ignore

    def test_custom_typ_template_is_watched(self, tmp_path):
        cfg = str(tmp_path / "c.yaml")
        write(cfg, "template:\n  path: my/tpl.typ\nchapters: [a.md]\n")
        _, _, files = _watch_targets(str(tmp_path), cfg)
        assert os.path.join(str(tmp_path), "my", "tpl.typ") in files

    def test_bundled_template_name_is_not_watched(self, project):
        tmp_path, cfg = project
        _, _, files = _watch_targets(str(tmp_path), cfg)
        assert files == [cfg]

    def test_output_dir_equal_to_project_dir_does_not_ignore_everything(self, tmp_path, capsys):
        cfg = str(tmp_path / "c.yaml")
        write(cfg, "output:\n  dir: .\n  filename: out.pdf\nchapters: [a.md]\n")
        _, ignore, _ = _watch_targets(str(tmp_path), cfg)
        assert str(tmp_path) not in ignore
        assert os.path.join(str(tmp_path), "out.pdf") in ignore

    def test_broken_config_falls_back_without_output(self, tmp_path, capsys):
        cfg = str(tmp_path / "c.yaml")
        write(cfg, "chapters: [unclosed\n")
        roots, ignore, files = _watch_targets(str(tmp_path), cfg)
        assert roots == [str(tmp_path)]
        assert files == [cfg]
        assert capsys.readouterr().out == ""


class TestWatchSnapshot:
    def snap(self, tmp_path, cfg):
        return _watch_snapshot(*_watch_targets(str(tmp_path), cfg))

    def test_detects_edit_add_and_delete(self, project):
        tmp_path, cfg = project
        a = str(tmp_path / "inputs" / "a.md")
        before = self.snap(tmp_path, cfg)
        assert a in before

        write(a, "# A changed and longer\n")
        assert self.snap(tmp_path, cfg) != before

        before = self.snap(tmp_path, cfg)
        b = str(tmp_path / "inputs" / "b.md")
        write(b)
        assert b in self.snap(tmp_path, cfg)

        os.remove(b)
        assert b not in self.snap(tmp_path, cfg)

    def test_ignores_outputs_work_dir_dotfiles_and_backups(self, project):
        tmp_path, cfg = project
        before = self.snap(tmp_path, cfg)
        write(str(tmp_path / "outputs" / "doc.pdf"))
        write(str(tmp_path / ".text-compositor" / "temp_build.typ"))
        write(str(tmp_path / ".git" / "HEAD"))
        write(str(tmp_path / "inputs" / ".a.md.swp"))
        write(str(tmp_path / "inputs" / "a.md~"))
        assert self.snap(tmp_path, cfg) == before


class TestBuildGuarded:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(build, "_build_one", lambda *a, **k: None)
        assert build._build_guarded("t", "r", "f", "c", False) is True

    def test_sys_exit_1_is_swallowed(self, monkeypatch):
        def fail(*a, **k):
            raise SystemExit(1)
        monkeypatch.setattr(build, "_build_one", fail)
        assert build._build_guarded("t", "r", "f", "c", False) is False

    def test_unexpected_exception_is_swallowed(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(build, "_build_one", boom)
        assert build._build_guarded("t", "r", "f", "c", False) is False
        assert "boom" in capsys.readouterr().out

    def test_keyboard_interrupt_propagates(self, monkeypatch):
        def interrupt(*a, **k):
            raise KeyboardInterrupt
        monkeypatch.setattr(build, "_build_one", interrupt)
        with pytest.raises(KeyboardInterrupt):
            build._build_guarded("t", "r", "f", "c", False)


class TestWatchLoop:
    def run_watch(self, monkeypatch, cfg, tmp_path, edits):
        """time.sleepを差し替え、呼び出し回数ごとにedits[n]（あれば）を実行する。editsを使い切って
        さらにsleepされたらKeyboardInterruptでループを抜ける（Ctrl+Cの模擬）。"""
        calls = []
        monkeypatch.setattr(build, "_build_one", lambda *a, **k: calls.append(a[3]))
        state = {"n": 0}

        def fake_sleep(_):
            n = state["n"]
            state["n"] += 1
            if n >= len(edits):
                raise KeyboardInterrupt
            if edits[n]:
                edits[n]()

        monkeypatch.setattr(time, "sleep", fake_sleep)
        build._watch(str(tmp_path), str(tmp_path), "fonts", [cfg])
        return calls

    def test_initial_build_only_when_nothing_changes(self, project, monkeypatch):
        tmp_path, cfg = project
        assert self.run_watch(monkeypatch, cfg, tmp_path, [None, None]) == [cfg]

    def test_rebuilds_once_after_a_change(self, project, monkeypatch):
        tmp_path, cfg = project
        a = str(tmp_path / "inputs" / "a.md")
        # sleep 0: 何も変わらない / 1: 保存 / 2: 変化検知後の待機（安定）/ 3: 再ビルド後の通常ポーリング
        calls = self.run_watch(monkeypatch, cfg, tmp_path, [None, lambda: write(a, "# changed!\n"), None, None])
        assert calls == [cfg, cfg]

    def test_output_written_by_build_does_not_retrigger(self, project, monkeypatch):
        tmp_path, cfg = project
        out = str(tmp_path / "outputs" / "doc.pdf")
        a = str(tmp_path / "inputs" / "a.md")
        calls = []

        def build_one(*args, **kwargs):
            calls.append(1)
            write(out, "pdf" * len(calls))

        monkeypatch.setattr(build, "_build_one", build_one)
        edits = [lambda: write(a, "# changed!\n"), None, None, None, None]
        state = {"n": 0}

        def fake_sleep(_):
            n = state["n"]
            state["n"] += 1
            if n >= len(edits):
                raise KeyboardInterrupt
            if edits[n]:
                edits[n]()

        monkeypatch.setattr(time, "sleep", fake_sleep)
        build._watch(str(tmp_path), str(tmp_path), "fonts", [cfg])
        assert len(calls) == 2  # 初回 + 保存1回分のみ。PDF出力では再ビルドされない

    def test_keeps_watching_after_failed_build(self, project, monkeypatch):
        tmp_path, cfg = project
        a = str(tmp_path / "inputs" / "a.md")
        calls = []

        def build_one(*args, **kwargs):
            calls.append(1)
            raise SystemExit(1)

        monkeypatch.setattr(build, "_build_one", build_one)
        edits = [lambda: write(a, "# broken!!\n"), None, lambda: write(a, "# fixed again!!\n"), None, None]
        state = {"n": 0}

        def fake_sleep(_):
            n = state["n"]
            state["n"] += 1
            if n >= len(edits):
                raise KeyboardInterrupt
            if edits[n]:
                edits[n]()

        monkeypatch.setattr(time, "sleep", fake_sleep)
        build._watch(str(tmp_path), str(tmp_path), "fonts", [cfg])
        assert len(calls) == 3  # 初回失敗後も監視を続け、2回の保存のたびに再ビルドする
