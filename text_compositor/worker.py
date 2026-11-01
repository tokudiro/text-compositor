"""常駐ワーカー（#167）: 標準入出力のJSON行で依頼を受け、単一のMarkdownをPDFにする。

GUI版Viewerが、Pythonをサブプロセスとして常駐させ、これに依頼する（#166の決定）。

    python -m text_compositor.worker

プロトコル（バージョン1）。標準入力へ、1行に1つのJSONオブジェクトを書く。標準出力へ、1行に1つの
JSONオブジェクトが返る。文字コードは、UTF-8。ワーカーは、依頼を1つずつ順に処理する。

起動時に、準備ができたことを示すイベントを1行出す。
    {"event": "ready", "protocol": 1, "version": "0.4.6"}

依頼: {"id": <任意の値。応答にそのまま返る>, "method": <メソッド名>, "params": {...}}
  - `build`  : Markdownをビルドする。params: `path`（必須）・`output`・`template`・`plugins`・
               `document`・`variables`・`config`・`lint`・`keep_temp`（意味は、`Session.build`と同じ。
               `lint`は、`{lintの名前: 真偽値}`。原稿の警告のON/OFF。例: `{"bold": false}`。#271）。
  - `render_html`: Markdown（または図の単体ファイル）をHTMLにする（実験的、#161）。params: `path`（必須）・
               `output`・`plugins`・`variables`・`config`・`csv_header`（意味は、`Session.render_html`と同じ。
               `csv_header`は、真偽値。`.csv`の1行目を見出し行にするか。既定`true`。#220）。
               `allow_external_images`は、真偽値。外部の画像（`https://...`等）を読み込むか。既定`false`
               （方針2章「ローカルに閉じる」。#238）。
               `cache_dir`は、文字列。図のSVGのキャッシュのフォルダ。`output`とともに指定すると、原稿のフォルダに、
               何も書かない。#258）。
               `lint`は、`build`と同じ。
  - `list_chapters`: 設定ファイルの`chapters`を、ファイルの一覧にする（Viewerのサイドバー用、#373）。params: `path`
               （必須。設定ファイル）。中身は読まない。設定の誤りでも、ワーカーは終了しない。
  - `open`   : 文書を開き、以後、原稿と参照ファイルの変更を監視する（#284）。params: `doc`（必須。文書の識別子）と、
               `render_html`と同じ。応答も、`render_html`と同じ。同じ`doc`の`open`が変換中に重なったら、最後の1件だけを
               処理し、古い依頼には`error.code`が`superseded`の応答を返す。
  - `close_doc`: `doc`の記憶と監視を捨てる。params: `doc`（必須）。
  - `watch`  : 文書ではないファイル（プロジェクトの設定ファイル）の監視。params: `name`・`files`（空配列で解除）。
  - `set_auto_reload`: 自動更新のON/OFF（既定OFF）。params: `value`（真偽値）。ONの間だけ、次のイベントが出る。
  - `ping`   : 生きているかの確認。
  - `shutdown`: 応答を返した後、Mermaidのブラウザ等を片付けて、終了する。

応答（`build`）: {"id": ..., "ok": true|false, "pdf": "...", "diagnostics": [...], "timings_ms": {...}}
  `ok`は、ビルドの成否。失敗（`ok: false`）でも、`diagnostics`に、エラーの位置つきの内容が入る。
  診断1件: {"severity": "error|warning|hint|info", "message": ..., "file": ..., "line": ..., "detail": ...}
応答（`render_html`）: {"id": ..., "ok": true|false, "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
  `html`は、生成したHTMLの絶対パス（図・画像は、そこからの相対パスで参照される）。`dependencies`は、原稿が参照している
  ローカルのファイル（画像など）の絶対パスで、変更を検知して自動で更新するために使う（成功時のみ）。他は、`build`と同じ。
  プロトコルのバージョンは、1のまま（メソッドの追加は、互換性を壊さない）。
イベント（ワーカーから。応答を待たない。`id`は無い）。自動更新がONの間だけ出る（#284）。
  {"event": "rendered", "doc": ..., "path": ..., "ok": ..., "html": ..., "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
    `doc`の変更を検知して変換し直した結果。`open`の応答と同じ形。
  {"event": "changed", "name": ..., "paths": [...]}   `watch`した対象の変更。変換はしない。
図の描画の依頼（ワーカーから、呼び出し元へ）。環境変数`TEXT_COMPOSITOR_MERMAID_HOST=1`で起動されたときだけ、
Mermaidと、Vega・Vega-Lite・WaveDrom・Bytefieldの図を、Playwrightとシステムのブラウザではなく、呼び出し元（ViewerのElectron。#207・#351・#392・#300）に描画してもらう。
（Graphvizは、呼び出し元に任せず、ワーカーが、Typstのdiagraphで描く。#264）
依頼（`build`・`render_html`）の処理中に、標準出力へ、1行のイベントを出し、標準入力で、応答を1行待つ。
  ワーカー → 呼び出し元: {"event": "render_mermaid", "callback": <番号>, "diagram_id": ..., "code": "...", "js": "<mermaid.min.jsのパス>"}
  Vega・Vega-Liteの図も、同じ形で依頼する（#351）:
  ワーカー → 呼び出し元: {"event": "render_vega", "callback": <番号>, "diagram_id": ..., "lang": "vega-lite"|"vega", "spec": {...},
                         "script": "<ブラウザで実行する描画スクリプト>", "js": {"vega": "<vega.min.jsのパス>", "vega_lite": "<vega-lite.min.jsのパス>"}}
  呼び出し元は、両方のjsを読み込んだページで、`script`（`async ([lang, spec]) => svg`という関数の式）を、`[lang, spec]`で呼び、SVGを返す。
  応答は、`render_mermaid`と同じ。
  WaveDromの図も、同じ形で依頼する（#392）:
  ワーカー → 呼び出し元: {"event": "render_wavedrom", "callback": <番号>, "diagram_id": ..., "spec": {...},
                         "script": "<ブラウザで実行する描画スクリプト>", "js": {"skin": "<default.jsのパス>", "wavedrom": "<wavedrom.min.jsのパス>"}}
  呼び出し元は、両方のjsを（skinが先）読み込んだページで、`script`（`async ([spec]) => svg`という関数の式）を、`[spec]`で呼び、SVGを返す。
  ページには、描画先の`<div id="WaveDrom_Display_0">`が要る。応答は、`render_mermaid`と同じ。
  Bytefieldの図も、同じ形で依頼する（#300）:
  ワーカー → 呼び出し元: {"event": "render_bytefield", "callback": <番号>, "diagram_id": ..., "source": "...",
                         "script": "<ブラウザで実行する描画スクリプト>", "js": {"bytefield": "<lib.jsのパス>"}}
  呼び出し元は、lib.jsを読み込んだページで、`script`（`async ([source]) => svg`という関数の式）を、`[source]`で呼び、SVGを返す。応答は、`render_mermaid`と同じ。
  呼び出し元 → ワーカー: {"callback": <同じ番号>, "ok": true, "svg": "..."} または {"callback": <同じ番号>, "ok": false, "error": "..."}
  待っている間に届いた、番号の違う行は、読み捨てる。呼び出し元が、標準入力を閉じたときは、描画の失敗になる。
応答（`list_chapters`）: {"id": ..., "ok": true, "result": {"items": [...], "warnings": [...]}}。`items`は、書いた順序で、
  `{"kind": "file", "name": ..., "path": <絶対パス。基準は`inputs.dir`>}`・`{"kind": "section", "name": ..., "children": [...]}`・
  `{"kind": "aggregate", "name": <`title`、無ければフォルダ名>, "path": <フォルダの絶対パス>}`（フォルダを1つの表にする章。
  1つのファイルではないため、呼び出し側は、開けない項目として扱う。#478。古い呼び出し側は、知らない`kind`を読み飛ばす）。
  読めない設定（存在しない・構文の誤り・`chapters`が無い）は、`{"ok": false, "error": {"code": "bad_config", ...}}`。
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
import queue
import sys
import threading
from typing import Any, Dict, List, Optional, TextIO

from text_compositor import __version__
from text_compositor import host_renderers as _host_renderers
from text_compositor.api import Session
from text_compositor.chapter_list import ChapterListError, list_chapters
from text_compositor.lints import check_lint_overrides
from text_compositor.worker_watch import WatchState

PROTOCOL_VERSION = 1

# 変更の検知（#284）。CLIの`--watch`と同じ間隔: 0.5秒ごとに調べ、0.3秒変化が止まるのを待って確定する
_POLL_INTERVAL = 0.5
_SETTLE = 0.3

_BUILD_PARAMS = ("output", "template", "plugins", "document", "variables", "config", "lint", "keep_temp")
_HTML_PARAMS = ("output", "plugins", "variables", "config", "csv_header", "allow_external_images", "cache_dir", "lint")


# 応答とイベント（`rendered`等）が、別のスレッドから同時に書かれても、1行が混ざらないようにする（#284）
_write_lock = threading.Lock()


def _write(out: TextIO, obj: Dict[str, Any]) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _write_lock:
        out.write(line)
        out.flush()


class _Reader:
    """標準入力の唯一の読み手（#284）。専用のスレッドで1行ずつ読み、行を2つに振り分ける。

    - `callback`（数値）を持つ行: 描画を依頼した側（`HostRenderer`）への返信。番号ごとに預かり、`wait_reply`で渡す。
    - それ以外: 新しい依頼。到着順に`next_request`で渡す（依頼は、1つずつ順に処理される）。JSONとして読めない行も、
      ここでは判断せず、依頼として渡す（誤りの応答は、依頼を処理する側が返す）。

    標準入力を複数のスレッドが読み合うと、行を取り合ってしまう。そのため、読むのはこのスレッドだけにする。
    """

    def __init__(self, stdin: TextIO) -> None:
        self._stdin = stdin
        self._requests: "queue.Queue[Any]" = queue.Queue()
        self._cond = threading.Condition()
        self._replies: Dict[int, Dict[str, Any]] = {}
        self._closed = False
        # daemon: 標準入力の読み待ちのまま、プロセスが終われるようにする（`shutdown`は、入力が閉じられる前に来る）
        threading.Thread(target=self._run, name="worker-stdin", daemon=True).start()

    def _run(self) -> None:
        try:
            while True:
                line = self._stdin.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    self._dispatch(line)
        finally:
            with self._cond:
                self._closed = True
                self._cond.notify_all()
            self._requests.put(None)

    def _dispatch(self, line: str) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            message = None
        if isinstance(message, dict) and isinstance(message.get("callback"), int):
            with self._cond:
                self._replies[message["callback"]] = message
                self._cond.notify_all()
            return
        self._requests.put(line)

    def next_request(self, block: bool = True) -> Any:
        """次の依頼を返す。依頼は、標準入力の行（文字列）か、`post`された内部の依頼。標準入力が閉じられ、
        依頼を読み切ったら、Noneを返す。`block=False`で、待たずに取れる依頼が無いときは、`queue.Empty`を投げる。"""
        return self._requests.get(block)

    def post(self, item: Any) -> None:
        """内部の依頼（監視スレッドが見つけた変更）を、標準入力の行と同じ順番の列に加える。"""
        self._requests.put(item)

    def wait_reply(self, number: int) -> Optional[Dict[str, Any]]:
        """番号が`number`の返信を待って返す。届く前に標準入力が閉じられたら、Noneを返す。"""
        with self._cond:
            while number not in self._replies and not self._closed:
                self._cond.wait()
            return self._replies.pop(number, None)


def _protocol_error(request_id: Any, code: str, message: str) -> Dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def _check_lint_param(request_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`params.lint`（{lintの名前: 真偽値}。#271）の誤りを、プロトコルエラーにする。無ければ、None。"""
    if "lint" not in params or params["lint"] is None:
        return None
    problem = check_lint_overrides(params["lint"])
    return _protocol_error(request_id, "bad_request", f"'params.lint': {problem}") if problem else None


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
    if method == "list_chapters":
        path = params.get("path")
        if not isinstance(path, str) or not path:
            return _protocol_error(request_id, "bad_request", "'params.path' (a string) is required.")
        try:
            return {"id": request_id, "ok": True, "result": list_chapters(path)}
        except ChapterListError as e:
            return _protocol_error(request_id, "bad_config", str(e))
    if method == "render_html":
        path = params.get("path")
        if not isinstance(path, str) or not path:
            return _protocol_error(request_id, "bad_request", "'params.path' (a string) is required.")
        unknown = sorted(set(params) - set(_HTML_PARAMS) - {"path"})
        if unknown:
            return _protocol_error(request_id, "bad_request", f"Unknown params: {', '.join(unknown)}.")
        if "csv_header" in params and not isinstance(params["csv_header"], bool):
            return _protocol_error(request_id, "bad_request", "'params.csv_header' must be a boolean.")
        if "allow_external_images" in params and not isinstance(params["allow_external_images"], bool):
            return _protocol_error(request_id, "bad_request", "'params.allow_external_images' must be a boolean.")
        for name in ("output", "cache_dir"):
            if name in params and params[name] is not None and not isinstance(params[name], str):
                return _protocol_error(request_id, "bad_request", f"'params.{name}' must be a string.")
        bad_lint = _check_lint_param(request_id, params)
        if bad_lint:
            return bad_lint
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
        bad_lint = _check_lint_param(request_id, params)
        if bad_lint:
            return bad_lint
        options = {k: params[k] for k in _BUILD_PARAMS if k in params}
        output = options.pop("output", None)
        result = session.build(path, output, **options)
        response = result.to_dict()
        response["id"] = request_id
        return response
    return _protocol_error(request_id, "unknown_method", f"Unknown method: {method!r}.")


class HostRenderer:
    """Mermaidの描画を、呼び出し元（ViewerのElectron）に、標準入出力で依頼する（#207）。依頼は、1つずつ順に処理される。"""

    def __init__(self, reader: _Reader, out: TextIO) -> None:
        self._reader = reader
        self._out = out
        self._next = 0

    def render_mermaid(self, diagram_id: str, code: str, js_path: str) -> str:
        return self._request("render_mermaid", "Mermaid", {"diagram_id": diagram_id, "code": code, "js": js_path})

    def render_vega(self, diagram_id: str, lang: str, spec: dict, script: str, js: dict) -> str:
        """Vega・Vega-Liteの描画を依頼する（#351）。`script`は、ブラウザで実行する描画スクリプト（vega_render.RENDER_SCRIPT）。"""
        return self._request("render_vega", "Vega", {"diagram_id": diagram_id, "lang": lang, "spec": spec, "script": script, "js": js})

    def render_wavedrom(self, diagram_id: str, spec: dict, script: str, js: dict) -> str:
        """WaveDromの描画を依頼する（#392）。`script`は、ブラウザで実行する描画スクリプト（wavedrom_render.RENDER_SCRIPT）。"""
        return self._request("render_wavedrom", "WaveDrom", {"diagram_id": diagram_id, "spec": spec, "script": script, "js": js})

    def render_bytefield(self, diagram_id: str, source: str, script: str, js: dict) -> str:
        """Bytefield-svgの描画を依頼する（#300）。`script`は、ブラウザで実行する描画スクリプト（bytefield_render.RENDER_SCRIPT）。"""
        return self._request("render_bytefield", "Bytefield", {"diagram_id": diagram_id, "source": source, "script": script, "js": js})

    def _request(self, event: str, label: str, fields: Dict[str, Any]) -> str:
        self._next += 1
        number = self._next
        _write(self._out, {"event": event, "callback": number, **fields})
        reply = self._reader.wait_reply(number)   # 待っている番号ではない行は、読み手が預かるだけで、ここへは届かない
        if reply is None:
            raise RuntimeError(f"The host application closed the connection while rendering a {label} diagram.")
        if reply.get("ok") is True and isinstance(reply.get("svg"), str):
            return reply["svg"]
        raise RuntimeError(str(reply.get("error") or f"The host application could not render the {label} diagram."))


class _Documents:
    """Viewerが開いている文書（`doc`）の記憶と、変更の検知（#284）。状態は、依頼を処理するスレッドだけが触る
    （監視の判定を持つ`WatchState`だけが、監視スレッドからも触られる）。"""

    METHODS = ("open", "close_doc", "watch", "set_auto_reload")

    def __init__(self, session: Session, watch_state: WatchState) -> None:
        self._session = session
        self._watch = watch_state
        self._docs: Dict[str, Dict[str, Any]] = {}   # doc -> {"path", "params", "deps"}
        self._watches: Dict[str, List[str]] = {}     # 名前 -> 監視するファイル

    def has_doc(self, doc: str) -> bool:
        return doc in self._docs

    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = request.get("id")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return _protocol_error(request_id, "bad_request", "'params' must be an object.")
        handlers = {"open": self._open, "close_doc": self._close_doc, "watch": self._watch_files,
                    "set_auto_reload": self._set_auto_reload}
        return handlers[request["method"]](request_id, params)

    def _open(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        doc, path = params.get("doc"), params.get("path")
        if not isinstance(doc, str) or not doc:
            return _protocol_error(request_id, "bad_request", "'params.doc' (a string) is required.")
        if not isinstance(path, str) or not path:
            return _protocol_error(request_id, "bad_request", "'params.path' (a string) is required.")
        render_params = {k: v for k, v in params.items() if k != "doc"}
        previous = self._docs.get(doc)
        # 変換の前から監視する。変換の最中の保存を取りこぼさないため（#424）
        deps_before = previous["deps"] if previous and previous["path"] == path else []
        self._watch.begin(("doc", doc), [path, *deps_before])
        response = handle_request(self._session, {"id": request_id, "method": "render_html", "params": render_params})
        if "error" in response:   # 誤った依頼。それまでの文書の記憶を、そのまま保つ
            if previous:
                self._watch.begin(("doc", doc), [previous["path"], *previous["deps"]])
            else:
                self._watch.remove(("doc", doc))
            return response
        self._remember(doc, path, render_params, response, deps_before)
        return response

    def _remember(self, doc: str, path: str, render_params: Dict[str, Any], response: Dict[str, Any],
                  deps_before: List[str]) -> None:
        # 変換に失敗したときは、直前の参照ファイルを保つ（直して保存したときに、自動で更新できるように）
        deps = list(response.get("dependencies") or []) if response.get("ok") else deps_before
        self._docs[doc] = {"path": path, "params": render_params, "deps": deps}
        self._watch.finish(("doc", doc), [path, *deps])

    def rerender(self, doc: str) -> Optional[Dict[str, Any]]:
        """監視が見つけた変更で、文書を変換し直し、`rendered`イベントにして返す。文書が閉じられていたら、None。"""
        info = self._docs.get(doc)
        if info is None:
            return None
        self._watch.begin(("doc", doc), [info["path"], *info["deps"]])
        response = handle_request(self._session, {"id": None, "method": "render_html", "params": info["params"]})
        response.pop("id", None)
        self._remember(doc, info["path"], info["params"], response, info["deps"])
        return {"event": "rendered", "doc": doc, "path": info["path"], **response}

    def changed_event(self, name: str, paths: List[str]) -> Dict[str, Any]:
        """`watch`の対象の変更を、`changed`イベントにして返す。次の変更を見つけられるよう、基準を取り直す。"""
        self._watch.begin(("watch", name), self._watches.get(name, []))
        return {"event": "changed", "name": name, "paths": paths}

    def _close_doc(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        doc = params.get("doc")
        if not isinstance(doc, str) or not doc:
            return _protocol_error(request_id, "bad_request", "'params.doc' (a string) is required.")
        self._docs.pop(doc, None)
        self._watch.remove(("doc", doc))
        return {"id": request_id, "ok": True, "result": {}}

    def _watch_files(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name, files = params.get("name"), params.get("files")
        if not isinstance(name, str) or not name:
            return _protocol_error(request_id, "bad_request", "'params.name' (a string) is required.")
        if not isinstance(files, list) or not all(isinstance(f, str) and f for f in files):
            return _protocol_error(request_id, "bad_request", "'params.files' must be an array of strings.")
        if files:
            self._watches[name] = list(files)
            self._watch.begin(("watch", name), list(files))
        else:
            self._watches.pop(name, None)
            self._watch.remove(("watch", name))
        return {"id": request_id, "ok": True, "result": {}}

    def _set_auto_reload(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        value = params.get("value")
        if not isinstance(value, bool):
            return _protocol_error(request_id, "bad_request", "'params.value' (a boolean) is required.")
        self._watch.enabled = value
        return {"id": request_id, "ok": True, "result": {}}


def _parse(item: Any) -> Any:
    """依頼の行を読む。JSONでなければ、("bad_json", 説明)。内部の依頼（タプル）は、そのまま返す。"""
    if isinstance(item, tuple):
        return item
    try:
        return json.loads(item)
    except json.JSONDecodeError as e:
        return ("bad_json", f"Invalid JSON: {e}")


def _is_open(request: Any) -> bool:
    if not isinstance(request, dict) or request.get("method") != "open":
        return False
    params = request.get("params")
    return isinstance(params, dict) and isinstance(params.get("doc"), str) and bool(params["doc"])


def _handle(session: Session, documents: "_Documents", request: Any) -> Dict[str, Any]:
    if isinstance(request, dict) and request.get("method") in _Documents.METHODS:
        return documents.handle(request)
    return handle_request(session, request)


def _take_batch(reader: _Reader) -> "tuple[list, bool]":
    """いま届いている依頼を、まとめて取る（1件は、届くまで待つ）。戻り値: (依頼の列, 標準入力が閉じられたか)。"""
    items: list = []
    item = reader.next_request()
    while True:
        if item is None:
            return items, True
        items.append(item)
        try:
            item = reader.next_request(block=False)
        except queue.Empty:
            return items, False


def _watch_loop(watch_state: WatchState, reader: _Reader, stop: threading.Event) -> None:
    """一定の間隔で変更を調べ、見つけたら、依頼の列に加える（変換は、依頼を処理するスレッドが行う）。"""
    while not stop.wait(_POLL_INTERVAL):
        try:
            for key, paths in watch_state.poll():
                reader.post(("changed", key, paths))
        except Exception as e:  # 一時的な読み取りの失敗で、監視を止めない
            print(f"watch error: {type(e).__name__}: {e}", file=sys.stderr)


def serve(stdin: TextIO, out: TextIO, host_renderer: bool = False) -> int:
    """依頼を1行ずつ読み、応答を1行ずつ書く。stdinが閉じられるか、`shutdown`を受けたら、終了する。"""
    session = Session()
    reader = _Reader(stdin)
    watch_state = WatchState(settle=_SETTLE)
    documents = _Documents(session, watch_state)
    stop_watching = threading.Event()
    threading.Thread(target=_watch_loop, args=(watch_state, reader, stop_watching), name="worker-watch", daemon=True).start()
    if host_renderer:
        host = HostRenderer(reader, out)
        _host_renderers.set_mermaid_host_renderer(host.render_mermaid)
        _host_renderers.set_vega_host_renderer(host.render_vega)
        _host_renderers.set_wavedrom_host_renderer(host.render_wavedrom)
        _host_renderers.set_bytefield_host_renderer(host.render_bytefield)
    try:
        _write(out, {"event": "ready", "protocol": PROTOCOL_VERSION, "version": __version__})
        shutdown = False
        while not shutdown:
            items, eof = _take_batch(reader)
            parsed = [_parse(item) for item in items]
            # 同じ文書の`open`が重なったら、最後の1件だけを処理する。文書の`open`がある間は、変更による変換し直しは要らない
            last_open = {p["params"]["doc"]: i for i, p in enumerate(parsed) if _is_open(p)}
            seen_changes = set()
            for i, request in enumerate(parsed):
                try:
                    if isinstance(request, tuple) and request[0] == "bad_json":
                        _write(out, _protocol_error(None, "bad_json", request[1]))
                    elif isinstance(request, tuple):   # ("changed", キー, パスの一覧)
                        _, key, paths = request
                        if key[0] == "watch":
                            _write(out, documents.changed_event(key[1], paths))
                        elif key[1] not in last_open and key not in seen_changes:
                            seen_changes.add(key)
                            event = documents.rerender(key[1])
                            if event is not None:
                                _write(out, event)
                    elif _is_open(request) and last_open[request["params"]["doc"]] != i:
                        _write(out, _protocol_error(request.get("id"), "superseded", "A newer 'open' for the same 'doc' replaced this request."))
                    else:
                        response = _handle(session, documents, request)
                        shutdown = bool(response.pop("_shutdown", False))
                        _write(out, response)
                        if shutdown:
                            break
                except Exception as e:  # 想定外の例外でも、ワーカーを落とさない
                    if isinstance(request, tuple):   # 依頼ではなく、監視が起こした処理。応答の宛先が無いので、記録だけ残す
                        print(f"worker error: {type(e).__name__}: {e}", file=sys.stderr)
                        continue
                    request_id = request.get("id") if isinstance(request, dict) else None
                    _write(out, _protocol_error(request_id, "internal_error", f"{type(e).__name__}: {e}"))
            if eof:
                break
        return 0
    finally:
        stop_watching.set()
        if host_renderer:
            _host_renderers.set_mermaid_host_renderer(None)
            _host_renderers.set_vega_host_renderer(None)
            _host_renderers.set_wavedrom_host_renderer(None)
            _host_renderers.set_bytefield_host_renderer(None)
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
    code = serve(stdin, protocol_out, host_renderer=os.environ.get("TEXT_COMPOSITOR_MERMAID_HOST") == "1")
    # 標準入力を読むスレッド（_Reader）は、`shutdown`のあとも読み待ちで残る。通常の終了処理は、そのスレッドが
    # 握る標準入力の読み取りの錠に触れ、Windowsでは異常終了する（終了コード0xC0000005）ことを確かめた。
    # セッションの片付けは、serveの中で済んでいるため、残りの出力を書き出して、すぐ終える。
    protocol_out.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
