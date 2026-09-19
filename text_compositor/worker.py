"""常駐ワーカー（#167）: 標準入出力のJSON行で依頼を受け、単一のMarkdownをPDFにする。

GUI版Viewerが、Pythonをサブプロセスとして常駐させ、これに依頼する（#166の決定）。

    python -m text_compositor.worker

プロトコル（バージョン1）。標準入力へ、1行に1つのJSONオブジェクトを書く。標準出力へ、1行に1つの
JSONオブジェクトが返る。文字コードは、UTF-8。ワーカーは、依頼を1つずつ順に処理する。

起動時に、準備ができたことを示すイベントを1行出す。
    {"event": "ready", "protocol": 1, "version": "0.3.0"}

依頼: {"id": <任意の値。応答にそのまま返る>, "method": <メソッド名>, "params": {...}}
  - `build`  : Markdownをビルドする。params: `path`（必須）・`output`・`template`・`plugins`・
               `document`・`variables`・`config`・`keep_temp`（意味は、`Session.build`と同じ）。
  - `render_html`: Markdown（または図の単体ファイル）をHTMLにする（実験的、#161）。params: `path`（必須）・
               `output`・`plugins`・`variables`・`config`・`csv_header`（意味は、`Session.render_html`と同じ。
               `csv_header`は、真偽値。`.csv`の1行目を見出し行にするか。既定`true`。#220）。
  - `ping`   : 生きているかの確認。
  - `shutdown`: 応答を返した後、Mermaidのブラウザ等を片付けて、終了する。

応答（`build`）: {"id": ..., "ok": true|false, "pdf": "...", "diagnostics": [...], "timings_ms": {...}}
  `ok`は、ビルドの成否。失敗（`ok: false`）でも、`diagnostics`に、エラーの位置つきの内容が入る。
  診断1件: {"severity": "error|warning|hint|info", "message": ..., "file": ..., "line": ..., "detail": ...}
応答（`render_html`）: {"id": ..., "ok": true|false, "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
  `html`は、生成したHTMLの絶対パス（図・画像は、そこからの相対パスで参照される）。`dependencies`は、原稿が参照している
  ローカルのファイル（画像など）の絶対パスで、変更を検知して自動で更新するために使う（成功時のみ）。他は、`build`と同じ。
  プロトコルのバージョンは、1のまま（メソッドの追加は、互換性を壊さない）。
Mermaidの描画の依頼（ワーカーから、呼び出し元へ）。環境変数`TEXT_COMPOSITOR_MERMAID_HOST=1`で起動されたときだけ、
Mermaidの図を、Playwrightとシステムのブラウザではなく、呼び出し元（ViewerのElectron。#207）に描画してもらう。
依頼（`build`・`render_html`）の処理中に、標準出力へ、1行のイベントを出し、標準入力で、応答を1行待つ。
  ワーカー → 呼び出し元: {"event": "render_mermaid", "callback": <番号>, "diagram_id": ..., "code": "...", "js": "<mermaid.min.jsのパス>"}
  呼び出し元 → ワーカー: {"callback": <同じ番号>, "ok": true, "svg": "..."} または {"callback": <同じ番号>, "ok": false, "error": "..."}
  待っている間に届いた、番号の違う行は、読み捨てる。呼び出し元が、標準入力を閉じたときは、描画の失敗になる。
応答（その他）: {"id": ..., "ok": true, "result": {...}}
プロトコルの誤り（JSONでない、未知のメソッド、引数の不足）: {"id": ..., "ok": false, "error": {"code": ..., "message": ...}}
  `error`キーがあれば、依頼が処理されていない。

標準出力は通信専用で、ビルド中にライブラリや外部プロセスが出力しても、通信路を壊さない（起動時に、
標準出力の書き込み先を標準エラーへ付け替え、通信には複製した元の標準出力を使う）。
"""
from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, Dict, Optional, TextIO

from text_compositor import __version__
from text_compositor import build as _build
from text_compositor.api import Session

PROTOCOL_VERSION = 1

_BUILD_PARAMS = ("output", "template", "plugins", "document", "variables", "config", "keep_temp")
_HTML_PARAMS = ("output", "plugins", "variables", "config", "csv_header")


def _write(out: TextIO, obj: Dict[str, Any]) -> None:
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


def _protocol_error(request_id: Any, code: str, message: str) -> Dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def handle_request(session: Session, request: Any) -> Optional[Dict[str, Any]]:
    """1つの依頼を処理して、応答（辞書）を返す。`shutdown`は、応答に`"_shutdown": True`を付ける。"""
    if not isinstance(request, dict):
        return _protocol_error(None, "bad_request", "A request must be a JSON object.")
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _protocol_error(request_id, "bad_request", "'params' must be an object.")

    if method == "ping":
        return {"id": request_id, "ok": True, "result": {"pong": True}}
    if method == "shutdown":
        return {"id": request_id, "ok": True, "result": {}, "_shutdown": True}
    if method == "render_html":
        path = params.get("path")
        if not isinstance(path, str) or not path:
            return _protocol_error(request_id, "bad_request", "'params.path' (a string) is required.")
        unknown = sorted(set(params) - set(_HTML_PARAMS) - {"path"})
        if unknown:
            return _protocol_error(request_id, "bad_request", f"Unknown params: {', '.join(unknown)}.")
        if "csv_header" in params and not isinstance(params["csv_header"], bool):
            return _protocol_error(request_id, "bad_request", "'params.csv_header' must be a boolean.")
        options = {k: params[k] for k in _HTML_PARAMS if k in params}
        output = options.pop("output", None)
        result = session.render_html(path, output, **options)
        response = result.to_dict()
        response["id"] = request_id
        return response
    if method == "build":
        path = params.get("path")
        if not isinstance(path, str) or not path:
            return _protocol_error(request_id, "bad_request", "'params.path' (a string) is required.")
        unknown = sorted(set(params) - set(_BUILD_PARAMS) - {"path"})
        if unknown:
            return _protocol_error(request_id, "bad_request", f"Unknown params: {', '.join(unknown)}.")
        options = {k: params[k] for k in _BUILD_PARAMS if k in params}
        output = options.pop("output", None)
        result = session.build(path, output, **options)
        response = result.to_dict()
        response["id"] = request_id
        return response
    return _protocol_error(request_id, "unknown_method", f"Unknown method: {method!r}.")


class HostMermaid:
    """Mermaidの描画を、呼び出し元（ViewerのElectron）に、標準入出力で依頼する（#207）。依頼は、1つずつ順に処理される。"""

    def __init__(self, stdin: TextIO, out: TextIO) -> None:
        self._stdin = stdin
        self._out = out
        self._next = 0

    def render(self, diagram_id: str, code: str, js_path: str) -> str:
        self._next += 1
        number = self._next
        _write(self._out, {"event": "render_mermaid", "callback": number, "diagram_id": diagram_id, "code": code, "js": js_path})
        while True:
            line = self._stdin.readline()
            if not line:
                raise RuntimeError("The host application closed the connection while rendering a Mermaid diagram.")
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(reply, dict) or reply.get("callback") != number:
                continue   # 待っている応答ではない行は、読み捨てる
            if reply.get("ok") is True and isinstance(reply.get("svg"), str):
                return reply["svg"]
            raise RuntimeError(str(reply.get("error") or "The host application could not render the Mermaid diagram."))

def serve(stdin: TextIO, out: TextIO, host_mermaid: bool = False) -> int:
    """依頼を1行ずつ読み、応答を1行ずつ書く。stdinが閉じられるか、`shutdown`を受けたら、終了する。"""
    session = Session()
    if host_mermaid:
        _build.set_mermaid_host_renderer(HostMermaid(stdin, out).render)
    try:
        _write(out, {"event": "ready", "protocol": PROTOCOL_VERSION, "version": __version__})
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                _write(out, _protocol_error(None, "bad_json", f"Invalid JSON: {e}"))
                continue
            try:
                response = handle_request(session, request)
            except Exception as e:  # 想定外の例外でも、ワーカーを落とさない
                request_id = request.get("id") if isinstance(request, dict) else None
                response = _protocol_error(request_id, "internal_error", f"{type(e).__name__}: {e}")
            shutdown = bool(response.pop("_shutdown", False))
            _write(out, response)
            if shutdown:
                break
        return 0
    finally:
        if host_mermaid:
            _build.set_mermaid_host_renderer(None)
        session.close()


def main() -> int:
    # 通信路（標準出力）を、ビルド中の出力から守る。元の標準出力を複製して通信専用にし、標準出力
    # そのもの（fd 1）は、標準エラーへ付け替える。外部プロセス（playwright install等）が継承する
    # fd 1への書き込みも、標準エラーへ回る。文字コードは、Windowsの既定（cp932等）に左右されないよう、UTF-8にする。
    sys.stdout.flush()
    protocol_out = io.TextIOWrapper(io.FileIO(os.dup(1), "w"), encoding="utf-8", newline="\n", write_through=True)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    return serve(stdin, protocol_out, host_mermaid=os.environ.get("TEXT_COMPOSITOR_MERMAID_HOST") == "1")


if __name__ == "__main__":
    sys.exit(main())
