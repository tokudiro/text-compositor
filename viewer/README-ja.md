# text-compositor Viewer

[English](README.md) | 日本語

text-compositorの、閲覧専用のMarkdown Viewerです（Electron製）。Markdownファイルを開くと、Pythonの常駐ワーカー（`render_html`。仕様書[doc/spec.md](../doc/spec.md)の14章）でHTMLにして、図（Mermaid・PlantUML・D2・`svg`）を、画像として表示します。エディタもPDF出力もありません。

表示エンジンは、計測で決めました（[doc/html-viewer-benchmark.md](../doc/html-viewer-benchmark.md)）。Electronに`--disable-gpu --in-process-gpu`を付けた構成が、体感で最速だったため、既定で、この引数を使います（`VIEWER_GPU=1`で、無効にできます）。

このディレクトリは、PyPIのPythonパッケージとは別のNode.jsプロジェクトです。sdist・wheelには含まれません。

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
| ファイルを開く | `Ctrl+O`、ウィンドウへのドラッグ＆ドロップ、コマンドラインの引数。起動中に、別のファイルを開くと、既存のウィンドウで表示します。 |
| 再読み込み | `F5`・`Ctrl+R`・**再読み込み**ボタン。スクロール位置は、保たれます。 |
| ズーム | `Ctrl`＋マウスホイール、`Ctrl`＋`+`・`-`、`Ctrl+0`（100%） |
| エラーの詳細の開閉 | エラー・警告の帯をクリック |

開けるファイル: Markdown（`.md`・`.markdown`）と、図の単体ファイル（`.mmd`・`.puml`・`.d2`。`.dot`は、HTML出力がGraphvizに対応する（#181）まで、警告つきのコード表示です）。

変換中は、「変換中…」を表示します。変換に失敗したときは、直前に成功した表示を残したまま、原因（分かる場合は、Markdownの行）を、ツールバーの下に一覧します。文書の中のWebのリンクは、既定のブラウザで開きます。Markdownファイルを指すリンクや、ドロップしたファイルは、Viewerで開きます。それ以外の遷移で、表示が文書から離れることはありません。

ファイルの変更を検知した自動の再読み込みは、まだありません（#170）。

## 環境変数

| 変数 | 意味 |
| --- | --- |
| `TEXT_COMPOSITOR_PYTHON` | ワーカーを動かすPython実行ファイル |
| `TEXT_COMPOSITOR_PYTHONPATH` | ワーカーの`PYTHONPATH`に加える（`pip install`せずに、リポジトリを直接使う場合） |
| `VIEWER_GPU=1` | `--disable-gpu --in-process-gpu`を使わず、Chromiumの標準のGPU設定にする |
| `VIEWER_TRACE=1` | 起動の各段階の時刻を、標準エラーへ出す |
| `VIEWER_DEBUG=1` | 「表示」メニューに、開発者ツールの項目を加える |

## 構成

| パス | 内容 |
| --- | --- |
| `src/main.js` | メインプロセス: ウィンドウ、メニュー、変換の流れ、遷移の規則 |
| `src/worker-client.js` | Pythonのワーカーのクライアント（標準入出力のJSON行） |
| `src/python.js` | ワーカーを動かすPythonを探す |
| `src/diagnostics.js` | ワーカーの診断を、画面に出す形にする |
| `src/targets.js` | 開けるファイルの判定と、リンク・ドロップの扱い |
| `src/chrome/` | ツールバー・エラーの帯・診断の一覧 |
| `test/` | `node --test`のテスト（偽のワーカーで、異常終了・時間切れ・再起動を確認） |

## テスト

```bash
cd viewer
npm test
```

## サードパーティのコンポーネント

Electron（MIT）と、同梱のChromiumです。配布物に付けるライセンス表記の一覧は、#168で扱います。
