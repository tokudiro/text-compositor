# Obunzu（お文図）

[English](README.md) | 日本語

Docs・Diagrams・Design as Codeのための、高速で閲覧専用のMarkdown Viewerです（text-compositorを土台にした、Electron製）。名前は、Observe（観察する）と文図（ぶんず、文章と図）を合わせた造語で、「おぶんず」と読みます。Markdownファイルを開くと、Pythonの常駐ワーカー（`render_html`。仕様書[doc/spec.md](../doc/spec.md)の14章）でHTMLにして、図（Mermaid・PlantUML・D2・`svg`）を、画像として表示します。エディタもPDF出力もありません。

見た目の方針（色・余白・フォント）は、[doc/viewer-visual-design.md](../doc/viewer-visual-design.md)にあります。

表示エンジンは、計測で決めました（[doc/html-viewer-benchmark.md](../doc/html-viewer-benchmark.md)）。Electronに`--disable-gpu --in-process-gpu`を付けた構成が、体感で最速だったため、既定で、この引数を使います（`VIEWER_GPU=1`で、無効にできます）。

このディレクトリは、PyPIのPythonパッケージとは別のNode.jsプロジェクトです。sdist・wheelには含まれません。

ウィンドウのタイトルに出るバージョンは、`package.json`の`version`です。`pyproject.toml`のtext-compositorのバージョンと、同じ値にそろえます（`tests/test_viewer_version.py`が確認します）。版上げのときは、`package-lock.json`も含めて、あわせて上げます。

## 実行

必要なもの: [Node.js](https://nodejs.org/) 20以上と、`text_compositor`を依存パッケージごとimportできるPython。

```bash
cd viewer
npm install
npm start -- path/to/file.md
```

ワーカーを動かすPythonは、次の順に探します。

1. 環境変数`TEXT_COMPOSITOR_PYTHON`（Python実行ファイルのフルパス）
2. アプリの隣の`python-embed/`（配布物用。#168）
3. `PATH`上の`python`・`python3`・`py`

パッケージをインストールせず、リポジトリを直接使う場合は、環境変数`TEXT_COMPOSITOR_PYTHONPATH`に、リポジトリのルートを指定します。ワーカーの`PYTHONPATH`の先頭に加わります。

Pythonが見つからなくても、ウィンドウは開き、対処を案内します。

## 使い方

| 操作 | 方法 |
| --- | --- |
| ファイルを開く | `Ctrl+O`、ウィンドウへのドラッグ＆ドロップ、コマンドラインの引数。起動中に、別のファイルを開くと、既存のウィンドウで表示します。`Ctrl+O`のダイアログは、前回開いたファイルのフォルダから始まり、種類（文・Markdown・図・CSV）で絞り込めます。「文」は、MarkdownとText（`.txt`）です。 |
| 再読み込み | `F5`・`Ctrl+R`・再読み込みのボタン。スクロール位置は、保たれます。 |
| CSVの見出し行 | `.csv`を開いているときだけ、ツールバーの表のボタン（または、「表示」メニューの「CSV: 1行目を見出しにする」）で、1行目を見出しにするか、すべてデータ行にするかを、切り替えます。切り替えは、覚えておきます。 |
| ズーム | `Ctrl`＋マウスホイール、`Ctrl`＋`+`・`-`、`Ctrl+0`（100%）。ツールバーの拡大率の表示を押しても、実寸に戻ります。 |
| 設定 | ツールバーの歯車のボタン、または`Ctrl+,`。「← 戻る」ボタン、`Esc`、歯車のボタンで閉じます。ファイルを開く・再読み込みでも、閉じます。 |
| エラーの詳細の開閉 | エラー・警告の帯をクリック |

開けるファイル: Markdown（`.md`・`.markdown`）、図の単体ファイル（`.mmd`・`.puml`・`.d2`・`.dot`・`.gv`は、図として表示します。Graphvizは、Viewer自身が、Viz.jsで描画します。Viz.jsは、初回に取得します）、Text（`.txt`。等幅の素のテキストで表示し、Markdownとしては解釈しません）、CSV（`.csv`。1行目を見出しにした表）、SVG（`.svg`。画像）。TextとCSVは、UTF-8（BOMなし）だけに対応します（Shift_JIS・UTF-16・BOMつきのUTF-8は、エラーです）。大きなファイルは、先頭の512 KBだけを表示し、案内を出します。それ以外（`.yaml`・`.json`・ソースコード・`.html`・SVG以外の画像・PDF・拡張子のないファイル・未知の拡張子・フォルダ）は、開かずに、エラーの帯で、開けるファイルを案内します。`.yaml`・`.json`・ソースコードのハイライト表示は、今後対応する予定です（#218）。コマンドラインで指定した、存在しないファイルも、案内が出ます。複数のファイルをドロップしたときは、最初の1つを開きます。文書の中の、ローカルのファイルへのリンクは、Viewerで開きます（開けないファイルなら、同じ案内が出ます）。

変換中は、「変換中…」を表示します。変換に失敗したときは、直前に成功した表示を残したままにします。エラーの帯には、1行の要約を出します。新しいエラーが出ると、詳細の一覧も開き、項目ごとに、原稿の行（分かる場合）と、ツールの出力を見せます（エラーは赤、警告は黄の印と線）。帯を押すと、一覧を閉じる・開くができます。文書の中のWebのリンクは、既定のブラウザで開きます。Markdownファイルを指すリンクや、ドロップしたファイルは、Viewerで開きます。それ以外の遷移で、表示が文書から離れることはありません。

**自動で更新**: 開いているMarkdownファイルや、それが参照する画像を保存すると、表示が自動で更新されます（保存から約0.18秒。スクロール位置は保たれます）。ツールバーの稲妻のトグル（オンのときは、色が付きます。「表示」メニューでも切り替えられます）で、切り替えられます。詳細:

- ファイルそのものではなく、ファイルのあるディレクトリを監視します。エディタの原子的な保存（一時ファイルへ書いて、名前を付け替える）も、検知します。まだ存在しないファイル（あとから作る画像）も、監視します。
- 変更は、まとめます。最後の変更から150 ms後に、変換を始めます。変換中の保存は、もう1回の変換として、順番を待ちます。
- 変換に失敗しても、直前の表示が残り、原稿の監視は続きます。直して保存すると、自動で回復します。
- 参照するファイルは、ワーカー（`render_html`の`dependencies`）が返します。

`node scripts/check-auto-reload.js`は、Viewerを起動して、これらの動作と、更新の速さを確認します（ElectronとPythonのワーカーが要ります。`npm test`には含みません）。

## 設定

設定画面（歯車のボタン）には、3つの項目があります。**ツールバーの位置**（上・下。エラーの帯も、ツールバーの側に移ります）と、**配色**（OSに合わせる・ライト・ダーク）と、**ファイルを開く場所**（`Ctrl+O`のダイアログが、最初に見せるフォルダ）です。ファイルを開く場所は、次の3つから選びます。「OSにゆだねる」は、場所を指定しません。「前回開いたフォルダ」（既定）は、前回開いたファイルのフォルダです。「特定のフォルダ」は、「フォルダを選ぶ…」で決めたフォルダです。前回開いたフォルダ・特定のフォルダが、未設定・消えているときは、ドキュメントのフォルダから始まります。変更は、すぐに反映されます。自動で更新のトグルも、保存されます。

ウィンドウの大きさ・位置（最大化の状態も）も、記憶します。保存された位置が、今のどの画面にも収まらないとき（外付けの画面を外したあとなど）は、大きさだけを戻します。

設定は、アプリのユーザーデータのフォルダ（Windowsでは`%APPDATA%\Obunzu`）に、`settings.json`として保存されます。ファイルがない・壊れている・値が想定外のときは、既定値に戻るため、起動は止まりません。

## 配布物（Windows）

`npm run build-dist`で、Pythonをインストールしなくても動く、ポータブルなZIP（`dist/Obunzu-<バージョン>-win-x64.zip`、約162 MB）を作ります。中身は、Electronのアプリと、その隣の組込版Python（`python-embed/`。HTML出力に必要なパッケージだけ）と、サードパーティのライセンス表記（`licenses/`）です。`typst`（PDF専用）と`playwright`は、同梱しません。Mermaidの図は、Electron自身のChromiumで描画します（`playwright`も、ChromeやEdgeも、要りません。#207）。`node scripts/check-dist.js`は、展開したアプリを、環境変数からPythonへの手がかりをすべて外して、起動し、確認します。同梱物・サイズ・初回に取得するもの・ライセンス・更新の方法は、[doc/viewer-distribution.md](../doc/viewer-distribution.md)にあります。
## 環境変数

| 変数 | 意味 |
| --- | --- |
| `TEXT_COMPOSITOR_PYTHON` | ワーカーを動かすPython実行ファイル |
| `TEXT_COMPOSITOR_PYTHONPATH` | ワーカーの`PYTHONPATH`に加える（`pip install`せずに、リポジトリを直接使う場合） |
| `VIEWER_GPU=1` | `--disable-gpu --in-process-gpu`を使わず、Chromiumの標準のGPU設定にする |
| `VIEWER_TRACE=1` | 起動の各段階の時刻を、標準エラーへ出す |
| `VIEWER_DEBUG=1` | 「表示」メニューに、開発者ツールの項目を加える |
| `VIEWER_THEME=light` / `dark` | OSの設定・設定画面に関わらず、配色を固定する（両方の見た目の確認用） |

## 構成

| パス | 内容 |
| --- | --- |
| `src/main.js` | メインプロセス: ウィンドウ、メニュー、変換の流れ、遷移の規則 |
| `src/worker-client.js` | Pythonのワーカーのクライアント（標準入出力のJSON行） |
| `src/python.js` | ワーカーを動かすPythonを探す |
| `src/diagnostics.js` | ワーカーの診断を、画面に出す形にする |
| `src/targets.js` | 開けるファイルの判定と、リンク・ドロップの扱い |
| `src/mermaid-host.js` | ワーカーの依頼で、非表示のウィンドウに、Mermaidの図を描画する（#207） |
| `src/settings.js` | 設定の読み書き（壊れていても、既定値で動く） |
| `src/watcher.js` | 開いているファイルと、参照するファイルを監視する |
| `scripts/check-auto-reload.js` | Viewerを起動して、自動更新を確認する（手動） |
| `scripts/check-open-files.js` | .txt・.csv・.svg・図の単体ファイル・対象外のファイル・フォルダ・存在しないファイル・大きなファイルを、コマンドラインで開いて、表示と案内を確認する（手動） |
| `scripts/check-window.js` | 設定画面を閉じる操作を、実際のキー操作で確認する（手動。Windowsのみ） |
| `scripts/check-window-state.js` | ウィンドウの大きさ・位置・最大化が、再起動後に戻ることを確認する（手動。Windowsのみ） |
| `scripts/build-dist.js` | Windows向けのポータブルZIP（Electron + 組込版Python + 必要最小限のパッケージ + ライセンス表記）を作る |
| `scripts/check-dist.js` | 展開した配布物を、Pythonへの手がかりを外した環境で起動して、確認する（手動。Windowsのみ） |
| `scripts/check-embed-dependencies.py` | 組込版Pythonが、同梱のDLLと、Windows標準のDLLだけに依存することを確認する（`pefile`が要る。手動） |
| `dist-requirements.txt` | 配布物に同梱するPythonのパッケージ（版を固定。`typst`と`playwright`は、外す） |
| `scripts/build-icons.js` | `assets/icon.svg`から、`assets/icon.ico`と`assets/icon.png`を書き出す |
| `assets/` | アプリのアイコン（元のSVGと、書き出した`.ico`・`.png`） |
| `src/chrome/` | ツールバー・エラーの帯・診断の一覧 |
| `test/` | `node --test`のテスト（偽のワーカーで、異常終了・時間切れ・再起動を確認。実際のPythonワーカーとの結合も確認） |

## アイコン

空色の角丸の四角に、文書のページと、小さな図（2つのノードを矢印でつなぐ）を重ねた絵です。Obunzuが表示する、文章と図を、いっしょに表します。元は`assets/icon.svg`です。自作で、リポジトリのライセンス（MIT）に従います。第三者の絵や、キャラクターの絵は、使っていません。

`assets/icon.svg`を変えたら、書き出し直して、結果をコミットします。`icon.ico`には、16・24・32・48・64・128・256 pxを入れます。SVGの描画は、Electronが行うため、追加のパッケージは要りません。

```bash
cd viewer
npm run build-icons
```

## テスト

```bash
cd viewer
npm test
```

`test/worker-integration.test.js`は、実際のPythonワーカーを起動して、`render_html`の往復（MarkdownとCSV、存在しないファイル、ワーカーの常駐）を確認します。`dist-requirements.txt`のパッケージが入ったPythonが要り、無いときは飛ばします。環境変数`REQUIRE_WORKER_INTEGRATION=1`を付けると、飛ばさず、失敗にします。

CI（`.github/workflows/viewer.yml`）は、`viewer/`や`text_compositor/`を変えたPR・pushで、Windowsで`npm test`を実行します。Electronは、起動しません。タグ`obunzu-v<バージョン>`をpushすると、ポータブルなZIPを作り、GitHub Releaseに添付します（`.github/workflows/viewer-release.yml`。[doc/viewer-distribution.md](../doc/viewer-distribution.md)）。

## サードパーティのコンポーネント

Electron（MIT）と、同梱のChromiumです。配布物に付けるライセンス表記の一覧は、#168で扱います。
