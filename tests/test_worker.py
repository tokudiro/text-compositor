"""常駐ワーカー（worker.py、#167）のテスト。"""
import io
import json
import os
import subprocess
import sys

import pytest

from text_compositor import worker
from text_compositor.api import BuildResult, HtmlResult
from text_compositor.diagnostics import Diagnostic

# 子プロセスが、pipインストールしていない環境（クローンして直接使う場合）でも、このリポジトリの
# text_compositorをimportできるようにする
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBPROCESS_ENV = dict(os.environ, PYTHONPATH=REPO_ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))


class FakeSession:
    def __init__(self, result=None):
        self.calls = []
        self.closed = False
        self.result = result or BuildResult(ok=True, pdf_path="/x/o.pdf", timings_ms={"total": 1.0})

    def build(self, path, output=None, **options):
        self.calls.append((path, output, options))
        return self.result

    def render_html(self, path, output=None, **options):
        self.html_calls = getattr(self, "html_calls", []) + [(path, output, options)]
        return HtmlResult(ok=True, html_path="/x/o.html", timings_ms={"total": 1.0})

    def close(self):
        self.closed = True


class TestHandleRequest:
    def test_ping(self):
        assert worker.handle_request(FakeSession(), {"id": 7, "method": "ping"}) == {
            "id": 7, "ok": True, "result": {"pong": True}}

    def test_shutdown_is_flagged(self):
        response = worker.handle_request(FakeSession(), {"id": 1, "method": "shutdown"})
        assert response["_shutdown"] is True and response["ok"] is True

    def test_build_passes_the_parameters_and_echoes_the_id(self):
        session = FakeSession()
        response = worker.handle_request(session, {
            "id": "abc", "method": "build",
            "params": {"path": "a.md", "output": "o.pdf", "template": "paper", "plugins": {"mermaid": False},
                       "document": {"toc": True}, "variables": {"K": "v"}, "config": {"x": 1}, "keep_temp": True}})
        assert session.calls == [("a.md", "o.pdf", {
            "template": "paper", "plugins": {"mermaid": False}, "document": {"toc": True},
            "variables": {"K": "v"}, "config": {"x": 1}, "keep_temp": True})]
        assert response["id"] == "abc" and response["ok"] is True and response["pdf"] == "/x/o.pdf"
        assert "error" not in response

    def test_render_html_passes_the_parameters_and_echoes_the_id(self):
        session = FakeSession()
        response = worker.handle_request(session, {
            "id": "h1", "method": "render_html",
            "params": {"path": "a.md", "output": "o.html", "plugins": {"mermaid": False},
                       "variables": {"K": "v"}, "config": {"x": 1}}})
        assert session.html_calls == [("a.md", "o.html", {
            "plugins": {"mermaid": False}, "variables": {"K": "v"}, "config": {"x": 1}})]
        assert response == {"id": "h1", "ok": True, "html": "/x/o.html", "diagnostics": [],
                            "timings_ms": {"total": 1.0}, "dependencies": []}

    @pytest.mark.parametrize("params", [
        None,
        {"path": ""},
        {"path": "a.md", "template": "paper"},  # buildにあって、render_htmlに無い引数
        {"path": "a.md", "keep_temp": True},
    ])
    def test_render_html_rejects_bad_parameters(self, params):
        request = {"id": 1, "method": "render_html"}
        if params is not None:
            request["params"] = params
        response = worker.handle_request(FakeSession(), request)
        assert response["ok"] is False and response["error"]["code"] == "bad_request"

    def test_a_failed_build_is_not_a_protocol_error(self):
        failed = BuildResult(ok=False, diagnostics=[Diagnostic("error", "boom", file="a.md", line=3)])
        response = worker.handle_request(FakeSession(failed), {"id": 1, "method": "build", "params": {"path": "a.md"}})
        assert response["ok"] is False and "error" not in response
        assert response["diagnostics"] == [
            {"severity": "error", "message": "boom", "file": "a.md", "line": 3, "detail": None}]

    @pytest.mark.parametrize("request_,code", [
        ("not an object", "bad_request"),
        ({"id": 1, "method": "nope"}, "unknown_method"),
        ({"id": 1}, "unknown_method"),
        ({"id": 1, "method": "build"}, "bad_request"),
        ({"id": 1, "method": "build", "params": {"path": ""}}, "bad_request"),
        ({"id": 1, "method": "build", "params": {"path": "a.md", "bogus": 1}}, "bad_request"),
        ({"id": 1, "method": "build", "params": "x"}, "bad_request"),
    ])
    def test_protocol_errors(self, request_, code):
        response = worker.handle_request(FakeSession(), request_)
        assert response["ok"] is False and response["error"]["code"] == code


class TestServe:
    def run(self, lines, session=None):
        session = session or FakeSession()
        original = worker.Session
        worker.Session = lambda: session
        try:
            out = io.StringIO()
            code = worker.serve(io.StringIO("".join(line + "\n" for line in lines)), out)
        finally:
            worker.Session = original
        return code, [json.loads(l) for l in out.getvalue().splitlines()], session

    def test_ready_event_comes_first(self):
        _, responses, _ = self.run([])
        assert responses[0]["event"] == "ready" and responses[0]["protocol"] == worker.PROTOCOL_VERSION
        assert "version" in responses[0]

    def test_answers_in_order_and_stops_at_shutdown(self):
        code, responses, session = self.run([
            json.dumps({"id": 1, "method": "ping"}),
            "",
            json.dumps({"id": 2, "method": "shutdown"}),
            json.dumps({"id": 3, "method": "ping"}),
        ])
        assert code == 0
        assert [r.get("id") for r in responses[1:]] == [1, 2]
        assert "_shutdown" not in responses[2]
        assert session.closed

    def test_survives_broken_json(self):
        _, responses, _ = self.run(["{not json", json.dumps({"id": 5, "method": "ping"})])
        assert responses[1]["error"]["code"] == "bad_json" and responses[1]["id"] is None
        assert responses[2]["id"] == 5 and responses[2]["ok"] is True

    def test_survives_an_internal_error(self):
        class Boom(FakeSession):
            def build(self, *a, **k):
                raise RuntimeError("kaboom")
        _, responses, _ = self.run([
            json.dumps({"id": 1, "method": "build", "params": {"path": "a.md"}}),
            json.dumps({"id": 2, "method": "ping"}),
        ], Boom())
        assert responses[1]["error"]["code"] == "internal_error" and "kaboom" in responses[1]["error"]["message"]
        assert responses[2]["ok"] is True

    def test_closes_the_session_when_stdin_ends(self):
        _, _, session = self.run([json.dumps({"id": 1, "method": "ping"})])
        assert session.closed

    def test_non_ascii_is_written_as_is(self):
        out = io.StringIO()
        worker._write(out, {"message": "日本語"})
        assert out.getvalue() == '{"message": "日本語"}\n'


class TestProcess:
    """実際に、別プロセスとして起動して、標準入出力で通信する。"""

    def start(self):
        return subprocess.Popen([sys.executable, "-m", "text_compositor.worker"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=SUBPROCESS_ENV, cwd=REPO_ROOT)

    @staticmethod
    def send(proc, obj):
        proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        proc.stdin.flush()

    @staticmethod
    def receive(proc):
        return json.loads(proc.stdout.readline().decode("utf-8"))

    def test_ping_and_shutdown(self):
        proc = self.start()
        try:
            assert self.receive(proc)["event"] == "ready"
            self.send(proc, {"id": 1, "method": "ping"})
            assert self.receive(proc) == {"id": 1, "ok": True, "result": {"pong": True}}
            self.send(proc, {"id": 2, "method": "shutdown"})
            assert self.receive(proc)["id"] == 2
            assert proc.wait(timeout=20) == 0
        finally:
            proc.kill()
            proc.stdout.close()
            proc.stderr.close()
            proc.stdin.close()

    def test_builds_over_stdio_with_utf8_paths(self, tmp_path):
        md = tmp_path / "日本語の原稿.md"
        md.write_text("# 見出し\n\n本文。\n", encoding="utf-8")
        out = tmp_path / "出力" / "結果.pdf"
        proc = self.start()
        try:
            assert self.receive(proc)["event"] == "ready"
            self.send(proc, {"id": 1, "method": "build", "params": {
                "path": str(md), "output": str(out), "plugins": {"mermaid": False}}})
            response = self.receive(proc)
            assert response["ok"] is True, response
            assert response["pdf"] == str(out) and out.read_bytes().startswith(b"%PDF")
            # 2回目は、同じワーカーで、原稿を書き換えて再ビルドする（常駐）
            md.write_text("# 見出し\n\n```dot {width=bogus}\ndigraph { a -> b }\n```\n", encoding="utf-8")
            self.send(proc, {"id": 2, "method": "build", "params": {
                "path": str(md), "output": str(out), "plugins": {"mermaid": False}}})
            failed = self.receive(proc)
            assert failed["ok"] is False and failed["id"] == 2
            assert failed["diagnostics"][0]["line"] == 3 and failed["diagnostics"][0]["file"] == str(md)
            self.send(proc, {"id": 3, "method": "shutdown"})
            self.receive(proc)
            assert proc.wait(timeout=20) == 0
        finally:
            proc.kill()
            proc.stdout.close()
            proc.stderr.close()
            proc.stdin.close()

    def test_renders_html_over_stdio_and_keeps_working_after_a_failure(self, tmp_path):
        md = tmp_path / "日本語の原稿.md"
        md.write_text("# 見出し\n\n本文。\n", encoding="utf-8")
        out = tmp_path / "出力" / "結果.html"
        plugins = {"mermaid": False, "plantuml": False, "d2": False}
        proc = self.start()
        try:
            assert self.receive(proc)["event"] == "ready"
            self.send(proc, {"id": 1, "method": "render_html", "params": {
                "path": str(md), "output": str(out), "plugins": plugins}})
            response = self.receive(proc)
            assert response["ok"] is True, response
            assert response["html"] == str(out) and "<h1>見出し</h1>" in out.read_text(encoding="utf-8")
            # 失敗（存在しないファイル）でも、ワーカーは、同じまま動き続ける
            self.send(proc, {"id": 2, "method": "render_html", "params": {"path": str(tmp_path / "none.md")}})
            failed = self.receive(proc)
            assert failed["ok"] is False and "error" not in failed and failed["diagnostics"][0]["severity"] == "error"
            self.send(proc, {"id": 3, "method": "shutdown"})
            self.receive(proc)
            assert proc.wait(timeout=20) == 0
        finally:
            proc.kill()
            proc.stdout.close()
            proc.stderr.close()
            proc.stdin.close()

    def test_stray_output_cannot_corrupt_the_protocol_channel(self):
        """ビルド中に、printや、fd 1への直接の書き込みがあっても、標準出力はJSON行だけになる。"""
        code = (
            "import os, sys\n"
            "import text_compositor.worker as w\n"
            "def fake_serve(stdin, out):\n"
            "    print('stray print')\n"
            "    os.write(1, b'stray fd write\\n')\n"
            "    out.write('{\"event\": \"x\"}\\n'); out.flush()\n"
            "    return 0\n"
            "w.serve = fake_serve\n"
            "sys.exit(w.main())\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, input=b"",
                              env=SUBPROCESS_ENV, cwd=REPO_ROOT)
        assert proc.returncode == 0
        assert proc.stdout == b'{"event": "x"}\n'
        assert b"stray print" in proc.stderr and b"stray fd write" in proc.stderr
