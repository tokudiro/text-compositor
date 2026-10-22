"""ヘッドレスChromeの起動待ち（#529）のテスト。実際のChromeは起動せず、偽のプロセスで確かめる。"""
import os

import pytest

import text_compositor.mermaid as mermaid_mod


class FakeProc:
    def __init__(self, exit_code=None, on_poll=None):
        self.exit_code = exit_code
        self.on_poll = on_poll
        self.terminated = False

    def poll(self):
        if self.on_poll:
            self.on_poll()
        return self.exit_code

    def terminate(self):
        self.terminated = True


@pytest.fixture
def fast(monkeypatch):
    """待ち時間を短くする（0.25秒の待ちを0.01秒に、上限を0.3秒に）。"""
    monkeypatch.setattr(mermaid_mod, "_LAUNCH_TIMEOUT_SECONDS", 0.3)
    real_sleep = mermaid_mod.time.sleep
    monkeypatch.setattr(mermaid_mod.time, "sleep", lambda s: real_sleep(0.01))


def launch(monkeypatch, tmp_path, proc):
    monkeypatch.setattr(mermaid_mod.subprocess, "Popen", lambda *a, **k: proc)
    return mermaid_mod._launch_headless_chrome("chrome", str(tmp_path))


def test_returns_the_port_chrome_writes(fast, monkeypatch, tmp_path):
    port_file = tmp_path / "DevToolsActivePort"
    proc = FakeProc(on_poll=lambda: port_file.write_text("9222\n/devtools/browser/x", encoding="utf-8"))
    result_proc, port = launch(monkeypatch, tmp_path, proc)
    assert result_proc is proc and port == 9222


def test_an_empty_first_line_is_read_again(fast, monkeypatch, tmp_path):
    """Chromeが書き込み途中で、1行目が空のとき、エラーにせず、読み直す。"""
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("", encoding="utf-8")
    calls = []

    def fill_in_later():
        calls.append(1)
        if len(calls) == 3:
            port_file.write_text("9333\n", encoding="utf-8")

    result_proc, port = launch(monkeypatch, tmp_path, FakeProc(on_poll=fill_in_later))
    assert port == 9333


def test_a_slow_start_reports_how_long_it_waited(fast, monkeypatch, tmp_path, capsys):
    proc = FakeProc()
    with pytest.raises(SystemExit):
        launch(monkeypatch, tmp_path, proc)
    captured = capsys.readouterr()
    message = captured.out + captured.err
    assert "did not become ready in time" in message and "still starting" in message and "seconds" in message
    assert proc.terminated


def test_an_exited_browser_reports_its_exit_code(fast, monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit):
        launch(monkeypatch, tmp_path, FakeProc(exit_code=139))
    captured = capsys.readouterr()
    assert "exited with code 139" in captured.out + captured.err


def test_the_wait_limit_is_long_enough_for_a_cold_start_on_ci():
    """CIのランナーで、初回の起動が20秒を超えることがあった（#529）。"""
    assert mermaid_mod._LAUNCH_TIMEOUT_SECONDS >= 60
