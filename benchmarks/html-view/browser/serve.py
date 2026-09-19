"""「既定のブラウザ＋ローカルサーバ」の候補（#180）の、ローカルサーバ。

固定のHTML（fixture/）を配信し、保存の検知の代わりに、標準入力の`reload`で、ブラウザへ再読み込みを通知する
（Server-Sent Events）。実際のViewerが、ファイルの変更を検知したときに行うことと同じ流れである。
ページには、読み込みの完了を知らせる小さなスクリプトを差し込む。

    python serve.py --dir <fixture> [--port 8766]

標準出力: `listening`（待ち受け開始）・`loaded`（最初の読み込みの完了）・`reloaded`（再読み込みの完了）。
標準入力: `reload`（再読み込みを通知）・`quit`（終了）。
"""
import argparse
import http.server
import os
import queue
import sys
import threading

SNIPPET = b"""<script>
fetch('/__loaded', {method: 'POST'});
new EventSource('/__events').onmessage = function (e) { if (e.data === 'reload') location.reload(); };
</script>
"""

clients = []
clients_lock = threading.Lock()
loaded_once = False


def say(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 標準出力は、通信専用にする
        pass

    def do_POST(self):
        global loaded_once
        if self.path == "/__loaded":
            say("reloaded" if loaded_once else "loaded")
            loaded_once = True
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == "/__events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            events = queue.Queue()
            with clients_lock:
                clients.append(events)
            try:
                while True:
                    events.get()
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
            except (OSError, ValueError):
                pass
            finally:
                with clients_lock:
                    if events in clients:
                        clients.remove(events)
            return
        if self.path in ("/", "/index.html"):
            with open(os.path.join(self.directory, "index.html"), "rb") as f:
                body = f.read().replace(b"</body>", SNIPPET + b"</body>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    handler = lambda *a, **k: Handler(*a, directory=args.dir, **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    say("listening")
    for line in sys.stdin:
        line = line.strip()
        if line == "reload":
            with clients_lock:
                for events in clients:
                    events.put(1)
        elif line == "quit":
            break
    server.shutdown()


if __name__ == "__main__":
    main()
