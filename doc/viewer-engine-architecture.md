# Viewer: 表示エンジンを切り替えられる構成にするための設計（#187）

Viewer（Obunzu、[#165](https://github.com/tokudiro/text-compositor/issues/165)）の表示エンジンを、Electron以外（WebView2等）にも差し替えられるようにするための設計である。既定のエンジン（Electron）の決定自体は[#180](https://github.com/tokudiro/text-compositor/issues/180)（[doc/html-viewer-benchmark.md](html-viewer-benchmark.md)）で済んでいる。本書は、その切り替えを可能にする構成を扱う[#187](https://github.com/tokudiro/text-compositor/issues/187)のうち、設計部分（[#284](https://github.com/tokudiro/text-compositor/issues/284)）を担う。実装（Pythonワーカーの拡張、WebView2殻の実装）は、本書の設計に基づき別issue（#284の残り、[#285](https://github.com/tokudiro/text-compositor/issues/285)）で行う。

## 1. 現状の分析

#187の構成案は、次の3層に分ける、というものだった。

| 部分 | 中身 | 場所の案 |
| --- | --- | --- |
| 中核 | Markdown→HTML→図、ファイルの変更検知、診断、再読み込み | Pythonの常駐ワーカー |
| 画面 | 文書の表示、エラーの帯、ズーム、検索など | HTMLとJavaScript（エンジン共通） |
| 殻 | ウィンドウ、ファイル選択、ドラッグ＆ドロップ、Pythonの起動と終了 | エンジンごとの小さな実装 |

この案が「将来こうしたい」であるのに対し、実際のコードを調べた結果、**現状はこの区分けを満たしていない**ことが分かった。

* `text_compositor/worker.py`は、依頼を1件受けて1件返すだけの、完全にステートレスなサービスである。ファイルの変更検知・キューの管理・自動更新の状態は、一切持たない。
* これらの状態は、すべて`viewer/src/main.js`（Node.js、Electronのメインプロセス）が、JavaScriptで持っている。`FileWatcher`（`watcher.js`）によるポーリング、`drain()`/`queued`/`inFlight`による変換のキュー処理、`state.autoReload`による自動更新の判断は、いずれもmain.js側の責務である。
* main.js自体でElectron固有API（`BrowserWindow`・`ipcMain`・`dialog`・`Menu`・`nativeTheme`・`screen`・`shell`）に依存する行は、本書の初版を書いた時点（594行）では21行程度に留まった。

**2026-11の見直し**: 初版のあと、main.jsは約1500行に増え、次の機能が加わった。状態管理を移す設計は、これらを前提にしなければならない。

* **タブ**（`document-tab.js`）: 1つのウィンドウが、複数の文書をタブで持つ。変換のキュー（`queued`・`inFlight`）は、タブごとにある。ワーカーは、全タブで1つで、変換は1件ずつ順に処理される（#332）。
* **監視対象の集約**: `updateWatch()`が、全タブの原稿とその参照ファイル（`DocumentTab.watchedFiles`）を、1つの`FileWatcher`にまとめて登録する。保存を検知すると、`tabsAffectedBy`が、そのファイルを持つタブだけを選び、再変換する。
* **プロジェクトモード**（#373）: 設定ファイル（`config.yaml`）も監視する。保存されたら、文書ではなく、サイドバーの章の一覧（`refreshProject()`）を作り直す。
* **原子的な保存への対応**: 保存の途中で原稿が一時的に無いとき、最大1秒（100ms×10回）待ってから再変換する。
* **ファイル監視の方式**: `watcher.js`は、`fs.watch`でディレクトリを監視し、名前で絞る。変化が150ms止まるのを待って、1回にまとめる。

したがって「1ワーカーが監視する文書は1つ」という初版の前提は成り立たない。次章以降は、文書をタブ単位（`doc`）で扱う形に改めた。

つまり、現状のmain.jsを「Electron固有の部分」と「それ以外」に物理的に2ファイル分割しても、「それ以外」は依然としてNode.js製のJavaScriptのままであり、Node.jsを持たない殻（RustでビルドするWebView2殻等）は、結局この状態管理ロジックを丸ごと再実装する羽目になる。**#187が本当に狙う「殻を小さく保つ」を実現するには、この状態管理（ファイル監視・キュー・自動更新）を、Pythonワーカー側に移す必要がある。**

## 2. 中核・画面・殻の役割分担（改訂）

上記の分析を踏まえ、役割分担を次のように定める。

* **中核（Pythonの常駐ワーカー、`text_compositor/worker.py`）**: Markdown→HTML→図の変換、ファイルの変更検知、変換のキュー処理、自動更新の状態、診断の生成。**エンジンに関わらず、この層は一切変更しない。**
* **画面（`viewer/src/chrome/`のHTML・CSS・JS、エンジン共通）**: 文書の表示領域、ツールバー、エラーの帯、ズーム、設定画面。エンジンをまたいで共有する。ただし、殻との通信部分（後述の「画面用ブリッジ」）だけは、エンジンごとに小さな実装を挟む。
* **殻（エンジンごとの小さなネイティブ実装。Electron、将来はWebView2等）**: ウィンドウの生成・大きさや位置の記憶、ファイル選択・フォルダ選択ダイアログ、ドラッグ&ドロップの受け口、Pythonワーカーの起動・停止、画面用ブリッジが呼ぶ関数の実装。**状態は持たない**（状態はすべて中核が持つため、殻は「頼まれたことをやる・起きたことを伝える」だけの薄い層になる）。

## 3. 通信方式の決定

#187の論点だった「ローカルHTTP+Server-Sent Eventsか、IPCか」は、**既存の標準入出力のJSON行プロトコル（[doc/spec.md](spec.md)14章）を、そのまま拡張する**と決める。

理由:

* 既にPython側（`Session`・`worker.py`）とJS側（`worker-client.js`）の両方に実装済みで、新しいエンジンもプロセス起動と標準入出力さえ扱えれば使える。HTTPサーバー・クライアントのライブラリを新たに殻へ持ち込む必要がない。
* ローカルポートを開かないため、ファイアウォール・ウイルス対策ソフトとの摩擦が無い。
* 既に`render_mermaid`（ワーカー→呼び出し元の逆方向リクエスト、[doc/spec.md](spec.md)14章）という「応答を待つ非同期イベント」の前例があり、後述する`rendered`イベント（応答を待たない一方向の通知）も、同じ枠組みの延長で説明できる。

## 4. 新しいワーカープロトコル

現行のプロトコル（`ping`・`shutdown`・`build`・`render_html`）に、次を追加する。プロトコルバージョンは1のまま据え置く（メソッドの追加は互換性を壊さない、[doc/spec.md](spec.md)14章の既定方針）。

### `open`: 文書を開く（以後、変更を監視する）

```
→ {"id": 1, "method": "open", "params": {"doc": "tab-1", "path": "doc.md", "csv_header": true, "lint": {...}, ...}}
← {"id": 1, "ok": true, "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
```

`doc`は、殻が決める文書の識別子（Electron殻では、タブの番号）。`path`以外の`params`は、現行の`render_html`と同じ（`csv_header`・`lint`・`plugins`・`output`・`cache_dir`・`allow_external_images`など）。応答の形も、`render_html`と同じ。ワーカーは、`doc`ごとに、直近の`open`の`params`を覚える。

* **文書は`doc`で区別する。** ワーカーは、複数の`doc`を同時に持つ（タブの数だけ）。`doc`ごとに、`path`・直近の`params`・`dependencies`（画像等の参照ファイル）を覚える。
* **再読み込み（F5）・別ファイルを開く、いずれも同じ`open`を呼ぶだけでよい。** 同じ`doc`で同じパスを開き直すのが再読み込み、別のパスを開くのが切り替えである。切り替えると、その`doc`の監視対象は、新しい`path`と`dependencies`に置き換わる（今のJSの`reload()`が`openFile(tab.file)`を呼ぶだけなのと同じ考え方）。
* **監視は、`open`の応答を返した後に始まる。** 自動更新が有効（`set_auto_reload`）なら、`path`と`dependencies`が監視対象になる。変換に失敗した`doc`も、`path`は監視し続ける（直して保存したときに、自動で更新するため）。変換の前から監視を始めるのは、最初の変換中の保存を取りこぼさないためである（#424）。
* **変換のキューは、`doc`ごとに、最新の1件だけを残す。** 変換中に同じ`doc`の`open`が重なったときは、古い待ちを捨てる（今のJSの`queued`と同じ）。捨てた依頼には、`{"ok": false, "error": {"code": "superseded", ...}}`を返す。

### `close_doc`: 文書を閉じる（監視をやめる）

```
→ {"id": 3, "method": "close_doc", "params": {"doc": "tab-1"}}
← {"id": 3, "ok": true, "result": {}}
```

タブを閉じたときに呼ぶ。その`doc`の記憶と監視を捨てる。実行中の変換は取り消せない（後述）。無い`doc`を指定しても、エラーにしない。

### `watch`: 文書以外のファイルを監視する

```
→ {"id": 4, "method": "watch", "params": {"name": "project", "files": ["C:/docs/config.yaml"]}}
← {"id": 4, "ok": true, "result": {}}
← {"event": "changed", "name": "project", "paths": ["C:/docs/config.yaml"]}
```

文書として変換しないファイルを、名前（`name`）つきで監視する。プロジェクトモード（#373）の設定ファイルが、これにあたる。`files`は、その名前の監視対象を置き換える（空配列で解除）。変更を検知すると、ワーカーは`changed`イベントだけを出し、再変換はしない。殻は、受け取ったら、章の一覧を作り直す（`refreshProject()`）。自動更新が無効（`set_auto_reload`）のときは、`changed`も出さない。

### `set_auto_reload`: 自動更新のON/OFFだけを切り替える

```
→ {"id": 2, "method": "set_auto_reload", "params": {"value": false}}
← {"id": 2, "ok": true, "result": {}}
```

開いている全文書と`watch`の監視を、まとめて有効・無効にする（今のJSの`state.autoReload`相当）。ワーカー全体で1つの値で、既定は無効。起動直後に、殻が設定の値を送る。無効の間も`doc`の記憶は保つ。有効に戻したときは、無効の間に起きた変更も検知して再変換する（監視の基準を、有効にした時点ではなく、直近の変換時点に置くため）。

### `rendered`イベント: ワーカーからの一方向通知（応答不要）

```
← {"event": "rendered", "doc": "tab-1", "path": "doc.md", "ok": true, "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
```

自動更新が有効な間に、`doc`の原稿または参照ファイルの変更を検知し、再変換が終わるたびに、ワーカーが自発的に出す。応答の形は、`open`と同じ（`ok`が偽でも、`diagnostics`に内容が入る）。`render_mermaid`と違い、呼び出し元からの返信は不要（一方向）。`open`への応答と違い、依頼の`id`は無く、`doc`で対応づける。

* 殻は、`open`への応答と`rendered`イベントを、同じ関数で画面に反映する。ただし、スクロール位置・見出しへの移動（`fragment`）・履歴の更新・開く前の注意（`notices`）は、`open`を呼んだ側の事情であり、`rendered`には関わらない。`rendered`は、同じ文書の再読み込みとして、スクロール位置を保って表示する（今のJSの`onFilesChanged`→`openFile`→`showHtml`の流れが、ここに集約される）。
* **原子的な保存への対応は、ワーカーが持つ。** 原稿が一時的に無いときは、現れるまで再変換を保留する（今のJSは最大1秒待って諦めるが、保留なら、遅れて現れた原稿も取りこぼさない）。
* 依頼とイベントは、同じ列で、1つずつ処理される。そのため、`close_doc`は、実行中の変換を取り消せない。`close_doc`より前に始まった変換の`rendered`は、`close_doc`の応答より先に届き得る。殻は、閉じた`doc`のイベントを無視する。

**JS側（`worker-client.js`）に必要な追加**: 現行の受信処理（`_start`内の`readline`ハンドラ）は、`event`と`callback`（数値）を両方持つ行だけを`_serve`（応答を待つ依頼）へ回し、`id`（数値）を持つ行だけを応答として扱う。`callback`を持たない`rendered`のような一方向イベントは、今のコードだと、どちらの条件にも合致せず黙って無視される。`_serve`とは別に、`event`はあるが`callback`が無い行を、登録済みのイベントリスナー（`main.js`が渡す）へ渡す仕組みを、`WorkerClient`に追加する必要がある。

### ワーカーを起動し直したとき

ワーカーは、起動し直すと、`doc`も自動更新の設定も忘れる。殻は、次の2つを行う（Electron殻の`worker-client.js`・`main.js`が実装済み）。

* ワーカーが、終了を頼まれていないのに終わったら（クラッシュ・時間切れでの強制終了）、次の依頼を待たずに、起動し直す。待つと、その間は、変更の検知が止まる。起動の直後に落ち続けても嵐にならないよう、5秒以内の2回目は、しない。
* 準備ができるたびに、`set_auto_reload`と、`watch`（プロジェクトの設定ファイル）を送り直す。起動し直した場合は、ファイルを開いているタブを、`open`で開き直す（監視を戻すため。変換が1回走る）。

### ファイル監視の実装

新規のポーリングコードは書かず、CLIの`--watch`が使っている`text_compositor/changes.py`の`_watch_snapshot(roots, ignore, files)`をそのまま使う。Viewerの場合、`roots=[]`・`ignore=[]`・`files=`全`doc`の`[path, *dependencies]`と、`watch`の`files`の和集合、として、個別ファイルの一覧だけを渡す（`--watch`のようなディレクトリ配下の走査は不要。監視対象は、直近の変換結果が返す`dependencies`から決まるため）。変化したパスから、影響を受ける`doc`（今のJSの`tabsAffectedBy`）と`watch`の名前を求める。CLIの`--watch`と同じ間隔（0.5秒ごとに走査し、0.3秒間変化が無くなるまで待って確定）を踏襲する。

**今のJSの`fs.watch`方式との違い**: スナップショットは、更新時刻とサイズの比較なので、原子的な保存（一時ファイルへ書いて名前を付け替える）も、まだ存在しない参照先が後から作られる場合も、検知できる（存在しない→存在する、も変化として扱うため）。一方で、検知までの遅れは、現在の約0.15秒から、最大で約0.8秒（走査0.5秒＋確定0.3秒）に延びる。自動更新の用途では許容できると判断した。体感に問題が出たときは、間隔を短くする（監視対象が数ファイルなので、走査の負荷は小さい）。

### 並行処理の設計

ワーカーは、次の3種類の「読み書き」が同時に起こり得る構成になる。

1. 殻からの新しい依頼（`open`・`close_doc`・`watch`・`set_auto_reload`・`ping`等）を、標準入力から読む。
2. 監視スレッドが変更を検知し、再変換して`rendered`イベント（または`changed`イベント）を標準出力へ書く。
3. 変換中（1でも2でも）に、Mermaid描画を殻に依頼し（`render_mermaid`）、その返信を標準入力から読む。

これらが素朴にスレッドを分けるだけだと、「標準入力を複数のスレッドが同時に読もうとする」「応答と`rendered`イベントの行が書き込み中に混ざる」という2つの事故が起こり得る。対策は以下の通り。

* **標準入力の読み手は、常に1つのスレッドに限定する。** そのスレッドは、読んだ行を「`callback`キーを持ち、待っている呼び出しがある返信」か「それ以外（新しい依頼）」かで振り分けるだけの役目に徹する。前者は、待っている側（`render_mermaid`の呼び出し元）に渡す。後者は、依頼を1件ずつ順に処理するスレッドへキューで渡す（今の「依頼を1件ずつ順に処理する」という性質を保つ）。
* **標準出力への書き込みは、`threading.Lock`で直列化する。** 依頼の応答と、監視スレッドが出す`rendered`イベントが、同時に書き込まれて行が混ざることを防ぐ。
* **実際の変換（`Session.render_html`等）の呼び出しも、同じ`threading.Lock`で直列化する。** 依頼駆動の変換と、監視駆動の再変換が、同時にTypstコンパイラやMermaidのブラウザを取り合わないようにする（今のJSの`inFlight`が果たしている役目と同じ）。

## 5. 殻が実装すべき関数の一覧

新しいエンジンの殻が実装すべき関数を、実際の`viewer/src/main.js`を分析して洗い出した。

| 分類 | 関数 | 備考 |
| --- | --- | --- |
| ウィンドウ | `create_window(bounds)` | 保存された大きさ・位置で、ウィンドウを作る |
| ウィンドウ | `create_content_view(window)` | 文書を表示する領域（ウィンドウ本体とは別のビュー） |
| ウィンドウ | `layout(chrome_height, has_document, settings_open, toolbar_position)` | 文書表示領域を、ツールバーの下（または上）に配置する |
| ウィンドウ | `load_chrome(window)` | ツールバー等のHTML（`chrome/chrome.html`）を読み込む |
| ウィンドウ | `on_resize/move/maximize(callback)` | 大きさ・位置の変更を伝える（保存用） |
| ウィンドウ | `set_background_color(color)` | 起動時・配色切り替え時の白い画面を防ぐ |
| 表示 | `show_html(html_path, same_document)` | `same_document`ならその場で再読み込み（スクロール位置を保つ）、それ以外は新規読み込み |
| 表示 | `set_zoom(level)` | ズーム倍率を反映する |
| ダイアログ | `open_file_dialog(default_dir, filters)` | ファイルを開くダイアログ |
| ダイアログ | `open_directory_dialog(default_dir)` | フォルダを選ぶダイアログ（設定画面） |
| ダイアログ | `open_external(url)` | OS既定のブラウザでURLを開く |
| 入力 | `handle_drop(paths)` | ドロップされたファイルパスを受け取る |
| メニュー | `build_menu(state) / update_menu_item(id, props)` | アプリケーションメニュー（無いエンジンでは省略可、後述） |
| プロセス | `spawn_worker(launch) / write_line(json) / read_line() → json / kill_worker()` | Pythonワーカーの起動・通信・終了 |
| アプリ | `single_instance_lock() / focus_existing_window() / on_second_instance(argv)` | 多重起動の防止 |
| アプリ | `app_directory()` | 同梱Pythonの探索起点 |
| アプリ | `theme() → light\|dark, on_theme_change(callback)` | OSのテーマ切り替えの検知 |
| 画面用ブリッジ | 「画面（chrome.js）→殻」の呼び出し一式 | 下記参照 |

**画面用ブリッジ**: `chrome.js`は、`ipcRenderer`（Electron固有）を直接呼ばず、`window.obunzuHost.*`という一枚の抽象越しに殻を呼ぶようにする。Electronでは`preload.js`が`contextBridge`でこれを実装し、WebView2ではwryが提供するpostMessage相当の機構で同じ関数群を実装する。関数の一覧は、今のIPCハンドラ（main.js末尾の`ipcMain.on(...)`群）と1対1になる: `openDialog`・`reload`・`setAutoReload`・`setCsvHeader`・`zoom`・`zoomReset`・`toggleSettings`・`setSetting`・`chooseOpenDirectory`・`clearCache`・`openPath`。

**Mermaid描画の委譲は任意**: 現状のElectron殻は、自分のChromiumを使い回してMermaidを描画する最適化（`TEXT_COMPOSITOR_MERMAID_HOST=1`、`render_mermaid`）を持つ。これは必須ではない。新しい殻がこれを実装しなければ、ワーカーは自前のPlaywright経由の描画（システムのブラウザが要る、[doc/spec.md](spec.md)11章）にフォールバックするため、殻は最小構成では実装しなくてよい。

## 6. エンジンの選び方

各エンジンは別々のネイティブ実行ファイル（Electron版の`Obunzu.exe`、WebView2版の`Obunzu-webview2.exe`等）になる想定であり、1つの実行ファイルが起動時の引数でエンジンそのものを実行時に差し替えるわけではない。したがって「選び方」は、どちらの実行ファイルを起動するか、という配布・起動の問題になる。複数エンジンを1つのインストーラーに同梱し、利用者に選ばせるか、既定のみを配布し追加エンジンは別ダウンロードにするかは、配布方法そのもの（[#168](https://github.com/tokudiro/text-compositor/issues/168)）の検討課題として、本書では扱わない。

## 7. 新しいエンジンを追加する手順

1. 「5. 殻が実装すべき関数の一覧」の関数群を、対象エンジンの言語・APIで実装する。
2. `chrome.js`が呼ぶ`window.obunzuHost.*`を、そのエンジンのIPC機構で実装する（画面用ブリッジ）。
3. `python -m text_compositor.worker`をサブプロセスとして起動し、標準入出力でJSON行プロトコル（本書「4. 新しいワーカープロトコル」）を話す。Mermaidの描画委譲は任意（実装しなければワーカー側のフォールバックに任せる）。
4. [doc/html-viewer-benchmark.md](html-viewer-benchmark.md)（#180）と同じ基準で、起動時の白い画面の出方・再読み込み時のスクロール位置の保持を、実機で確認する。
5. 配布物への組み込みは、[#168](https://github.com/tokudiro/text-compositor/issues/168)の検討課題とする。

## 8. 未解決の論点

* **画面のJavaScript依存**: 本書が扱うElectron・WebView2は、いずれもJavaScriptを実行できるため、「画面」（chrome.js）をJavaScriptのまま共有する前提を崩さない。litehtml・Blitz等のJavaScriptを使わない軽量エンジン（[#180](https://github.com/tokudiro/text-compositor/issues/180)では未評価）を実際に採用する段になったときは、画面（ツールバー・エラーの帯等）をネイティブ側で作り直す必要があり、その時点で改めて設計する。今回は先送りする。
* **メニューの扱い**: アプリケーションメニュー（`Menu.buildFromTemplate`）を持たないエンジン・OSの場合の代替（ツールバーへの統合等）は、実際にWebView2殻を実装する際に決める。

## 9. 移行計画

1. **本書（設計、[#284](https://github.com/tokudiro/text-compositor/issues/284)の一部）**
2. **設計の改訂**（2026-11）。タブ・プロジェクトモード・監視方式の現状に合わせて、4章を書き直した（本書の1章末尾と4章）。
3. **`text_compositor/worker.py`の並行処理化**。標準入力の読み手を1スレッドにし、標準出力と変換呼び出しを`Lock`で直列化する。新しいメソッドは足さない。成功の判定は、既存の`worker-integration.test.js`とPython側のテストが、変更なしで通ること。
4. **`open`・`close_doc`・`watch`・`set_auto_reload`・`rendered`・`changed`の実装**（`worker.py`）。成功の判定は、Python側のテストが通ること。この段階では、`main.js`は変えない。
5. **`worker-client.js`の一方向イベント対応と、`main.js`の簡素化**。`watcher.js`・`drain()`・`tabsAffectedBy`・`DocumentTab.watchedFiles`等のJS側の状態管理を削除する。成功の判定は、`viewer/test/`が通ることと、`check-*.js`・実機で、タブ・プロジェクトモード・自動更新が従来どおり動くこと。
6. **WebView2（wry）殻の実装**（[#285](https://github.com/tokudiro/text-compositor/issues/285)）。3〜5で確定したプロトコルに乗るだけでよく、状態管理の再実装は不要になる。

3〜5は[#284](https://github.com/tokudiro/text-compositor/issues/284)の残り作業、6は#285で扱う。
