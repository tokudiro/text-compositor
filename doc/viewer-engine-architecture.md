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
* main.js自体でElectron固有API（`BrowserWindow`・`ipcMain`・`dialog`・`Menu`・`nativeTheme`・`screen`・`shell`）に依存する行は、594行中21行程度に留まる。

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
→ {"id": 1, "method": "open", "params": {"path": "doc.md", "auto_reload": true, "csv_header": true}}
← {"id": 1, "ok": true, "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
```

応答の形は、現行の`render_html`と同じ。`auto_reload: true`のときは、応答を返した後、`path`とその`dependencies`（画像等の参照ファイル）の変更監視を、ワーカー内部で開始する。

* **再読み込み（F5）・別ファイルを開く、いずれも同じ`open`を呼ぶだけでよい。** 「今開いている文書を、同じパスで開き直す」のが再読み込み、「別のパスで開く」のが切り替えであり、呼び出し側から見て特別扱いは不要（今のJSの`reload()`が`openFile(state.file)`を呼ぶだけなのと同じ考え方）。
* 1ワーカーにつき、監視する文書は常に1つ（Viewerが1ウィンドウ1文書のため）。新しい`open`は、それまでの監視を置き換える。

### `set_auto_reload`: 自動更新のON/OFFだけを切り替える

```
→ {"id": 2, "method": "set_auto_reload", "params": {"value": false}}
← {"id": 2, "ok": true, "result": {}}
```

現在開いている文書はそのままに、監視の開始・停止だけを切り替える（今のJSの`setAutoReload`相当）。開いている文書が無ければ何もしない。

### `rendered`イベント: ワーカーからの一方向通知（応答不要）

```
← {"event": "rendered", "path": "doc.md", "html": "...", "diagnostics": [...], "timings_ms": {...}, "dependencies": [...]}
```

監視中に変更を検知し、再変換が終わるたびに、ワーカーが自発的に出す。`render_mermaid`と違い、呼び出し元からの返信は不要（一方向）。殻は、これを受け取ったら画面に反映するだけでよい（今のJSの`onFilesChanged`→`openFile`→`showHtml`の一連の流れが、ここに集約される）。

**JS側（`worker-client.js`）に必要な追加**: 現行の受信処理（`_start`内の`readline`ハンドラ）は、`event`と`callback`（数値）を両方持つ行だけを`_serve`（応答を待つ依頼）へ回し、`id`（数値）を持つ行だけを応答として扱う。`callback`を持たない`rendered`のような一方向イベントは、今のコードだと、どちらの条件にも合致せず黙って無視される。`_serve`とは別に、`event`はあるが`callback`が無い行を、登録済みのイベントリスナー（`main.js`が渡す）へ渡す仕組みを、`WorkerClient`に追加する必要がある。

### ファイル監視の実装

新規のポーリングコードは書かず、CLIの`--watch`が使っている`text_compositor/changes.py`の`_watch_snapshot(roots, ignore, files)`をそのまま使う。Viewerの場合、`roots=[]`・`ignore=[]`・`files=[path, *dependencies]`として、個別ファイルの一覧だけを渡す（`--watch`のようなディレクトリ配下の走査は不要。監視対象は、直近の変換結果が返す`dependencies`から決まるため）。CLIの`--watch`と同じ間隔（0.5秒ごとに走査し、0.3秒間変化が無くなるまで待って確定）を踏襲する。

### 並行処理の設計

ワーカーは、次の3種類の「読み書き」が同時に起こり得る構成になる。

1. 殻からの新しい依頼（`open`・`set_auto_reload`・`ping`等）を、標準入力から読む。
2. 監視スレッドが変更を検知し、再変換して`rendered`イベントを標準出力へ書く。
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
2. **`text_compositor/worker.py`の拡張**（`open`・`set_auto_reload`・`rendered`イベント・並行処理の実装）と、`viewer/src/main.js`をこれに合わせて簡素化する（`watcher.js`・`drain()`等のJS側の状態管理を削除する）。既存の`viewer/test/`が通ること、Electron版Obunzuが実機で従来どおり動くことを確認する。
3. **WebView2（wry）殻の実装**（[#285](https://github.com/tokudiro/text-compositor/issues/285)）。2で確定したプロトコルに乗るだけでよく、状態管理の再実装は不要になる。

2・3は、それぞれ既存issue（#284の残り作業／#285）で扱う。本書はその前提となる設計を固めるものであり、コードの変更は含まない。
