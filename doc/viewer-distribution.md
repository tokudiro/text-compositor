# Obunzu: Windows向けの配布物（#168）

Pythonをインストールしていない環境でも動く、Obunzu（Viewer。[#165](https://github.com/tokudiro/text-compositor/issues/165)）の配布物の、形式・同梱物・作り方・更新の方法をまとめる。

## 配布の形式

- **ポータブルなZIP**（`Obunzu-<バージョン>-win-x64.zip`）。展開して、`obunzu.exe`を起動する。インストーラは、作らない（インストールも、レジストリへの書き込みも、要らない。削除は、フォルダごと消すだけ）。
- ZIPの大きさは、**約162 MB**。展開後は、**約391 MB**。Electron（Chromium）が、ほとんどを占める。この大きさは、許容する（[#180](https://github.com/tokudiro/text-compositor/issues/180)。削減は、行わない）。
- コード署名は、していない。そのため、Windowsの「SmartScreen」が、初回の起動で、警告を出す可能性がある（推測）。署名は、必要が出たときに、別に検討する。

```text
Obunzu-0.3.0-win-x64/
  obunzu.exe                 Electronのアプリ（アイコン・バージョン情報つき）
  resources/app.asar         Viewerのコード（src/・assets/）
  python-embed/              組込版Python（python.orgのembeddable package）
    Lib/site-packages/       必要最小限のパッケージ + text_compositor
  licenses/                  サードパーティのライセンス表記
  LICENSE, LICENSES.chromium.html   ElectronとChromiumのライセンス
```

## 同梱するもの・しないもの

方針は、「Viewerの動作に必要なものだけを、事前に入れる。それ以外は、必要になったときに、取得または案内する」（利用者の要望）。

| 種類 | 扱い | サイズ（展開後） |
|------|------|------------------|
| Electron（Chromium） | 同梱 | 約367.5 MB |
| Viewerのコード（`resources/`） | 同梱 | 0.1 MB |
| 組込版Python 3.12.10 | 同梱 | 約21.5 MB |
| Pythonのパッケージ（`markdown-it-py`・`mdurl`・`mdit-py-plugins`・`PyYAML`・`platformdirs`）と、`text_compositor` | 同梱 | 約2.3 MB（`text_compositor`は0.6 MB、`markdown_it`は0.4 MB、`yaml`は0.7 MB） |
| ライセンス表記 | 同梱 | 0.1 MB未満 |
| **`typst`**（PDF用のコンパイラ） | **同梱しない** | 約59 MB（外した分） |
| **`playwright`**（Mermaidの描画用） | **同梱しない** | 約106 MB（外した分。うち、Node.jsのドライバが約88 MB） |
| PlantUML・D2・Mermaid用のブラウザ・Noto Sans JP | 同梱しない（下の表） | - |

### `typst`を、同梱から外せるか（結果: 外せる。外した）

- `build.py`は、`typst`を、読み込み時に、`import`していた。これを、**初めて使うとき**（Typstのコンパイル）に、`import`するように変えた（`_LazyTypst`）。HTML出力（`render_html`）と、それを使うViewerは、`typst`なしで動く。
- 確認: `typst`と`playwright`を、`import`できない状態にして、パッケージの読み込みと、HTML出力（`render_html`）が成功する（`tests/test_distribution.py`）。PDFを作るときに`typst`がなければ、「`typst`が要る。HTML出力には要らない」というメッセージになる。
- 配布物の依存は、`viewer/dist-requirements.txt`に、版を固定して書く。`pyproject.toml`の依存と、ずれていないことを、テストで確認する。

## 同梱しないもの（必要になったときに、取得・案内する）

`text_compositor`が、必要になったときに、取得して、キャッシュする（`%LOCALAPPDATA%\text-compositor\Cache\`）。取得の失敗は、再試行し（[#189](https://github.com/tokudiro/text-compositor/issues/189)）、SHA256で確認する。

| もの | 使う場面 | サイズ | 取得元 |
|------|----------|--------|--------|
| PlantUMLの`plantuml-mit-1.2026.6.jar` | `plantuml`の図 | 約16.8 MB | GitHub Releases（`plantuml/plantuml`） |
| Java（Eclipse Temurin JRE 21） | `plantuml`の図。システムにJava 11以上があれば、それを使う | 約49.7 MB（取得）、展開後 約144.5 MB | GitHub Releases（`adoptium/temurin21-binaries`） |
| D2のCLI（v0.9.0） | `d2`の図。システムに`d2`があれば、それを使う | 約13 MB（取得）、展開後 約40.8 MB | GitHub Releases（`d2lang/d2`） |
| `mermaid.min.js` | `mermaid`の図 | 約3.4 MB | jsDelivr（npm `mermaid@11.16.1`） |
| Noto Sans JP | **PDF専用**（Viewerは、HTML出力で、使わない） | 約8.8 MB | GitHub Releases（`notofonts/noto-cjk`） |

サイズは、`build.py`の記載と、実際にキャッシュされたファイルの実測による。PlantUMLとD2は、初回の描画で、取得のために、数秒〜数十秒かかる（回線による）。

### Mermaidについて（この配布物の制限）

Mermaidの描画は、Pythonの`playwright`で、システムのChromeまたはEdgeを起動して行う。この配布物は、`playwright`を同梱しないため、**Mermaidの図は、この配布物では、エラーになる**（帯に、変換エラーとして出る）。

- 代わりに、**Electron自身のChromiumで描画する**ことを、検討した。非表示のウィンドウで`mermaid.render()`を呼ぶと、準備に約0.3秒（1回だけ）、描画に16〜51 msで、構文エラーも、例外で返る。描画できることと、速いことを、確認した。
- 実装は、別のissue（[#207](https://github.com/tokudiro/text-compositor/issues/207)）で行う。それまでの、Mermaidの利用は、開発環境（Python + `playwright` + Chrome・Edge）に限られる。

## ライセンス表記

- 配布物の`licenses/`に、`THIRD-PARTY-NOTICES.md`（一覧）と、各ライセンスの全文を入れる。ビルドが、パッケージのメタデータ（`*.dist-info`）から、自動で作る。
- 内訳: 本体（MIT）、Python（PSF）、OpenSSL（Apache-2.0。全文を同梱）、`markdown-it-py`・`mdit-py-plugins`・`mdurl`・`platformdirs`・`PyYAML`（MIT）。ElectronとChromiumは、`LICENSE`と`LICENSES.chromium.html`（Electronの配布物に含まれるもの）。
- **未完の点**: 組込版Pythonに含まれる`libffi`・`expat`・`SQLite`・Microsoftの実行時ライブラリは、名前・ライセンス・参照先の記載に留め、全文は付けていない（python.orgの配布物と、同じ扱い）。厳密に全文を付ける必要があるかは、未確認。

## 作り方

前提: Windows、Node.js 22.12以上、インターネット接続、pipが使えるPython（ビルド用。どの版でもよい。組込版Pythonの版と、配布物のパッケージは、`--platform`の指定で、決まる）。

```bash
cd viewer
npm ci
npm run build-dist
```

- `dist/Obunzu-<バージョン>-win-x64.zip`と、展開済みの`dist/stage/Obunzu-<バージョン>-win-x64/`ができる。ビルドの終わりに、同梱物のサイズの内訳を表示する。
- ビルド用のPythonは、環境変数`PYTHON_FOR_BUILD`、なければ`TEXT_COMPOSITOR_PYTHON`、なければ`PATH`の`python`。
- 取得するもの（組込版Python・Apache-2.0の全文）は、SHA256を確認し、`dist/.cache/`に置く。Electronは、`@electron/packager`が取得する（ユーザーのキャッシュに置く）。
- バージョンは、`viewer/package.json`の`version`（text-compositorと同じ。[#194](https://github.com/tokudiro/text-compositor/issues/194)）。

### 検証

```bash
cd viewer
node scripts/check-dist.js
```

展開した配布物を、**Pythonへの手がかり（`PATH`・`TEXT_COMPOSITOR_*`・`PYTHON*`）を、すべて外した環境**で起動して、確認する。

- 文書が表示される。
- ワーカーが、同梱の`python-embed/python.exe`で動いている。
- 日本語のフォルダ名・ファイル名の原稿が、表示できる。
- Mermaidの図は、エラーとして、帯に出る（落ちない）。

実測（2026-09-19、開発機）: すべて成功。起動（プロセスの開始から、文書の表示まで）は、5回で、0.82〜0.90秒。開発時（`npm start`）の0.86秒と、同じ範囲である。

**クリーンなWindowsでの確認は、未実施**（開発機は、Pythonがインストール済みで、上の検証は、環境変数を外したのみ。Windows Sandboxは、管理者権限と、機能の有効化が要るため、使っていない）。Pythonのない別のPCで、ZIPを展開して起動する確認を、お願いする。

## 更新の方法

- **新しいZIPを取得して、展開し直す**（フォルダごと置き換える）。自動更新は、行わない（署名と、配布の基盤が要るため。必要になったら、別に検討する）。
- 設定・ウィンドウの状態は、`%APPDATA%\Obunzu\settings.json`に、図のキャッシュ等は、`%LOCALAPPDATA%\text-compositor\`にあり、アプリのフォルダの外のため、置き換えても、残る。
- **Chromium（Electron）の更新**は、Electronの版を上げて、Obunzuの新版を出すことで、行う。組込版Pythonと、パッケージも、同様（版は、`build-dist.js`と`dist-requirements.txt`で固定している）。セキュリティ更新が出たときは、新版を出す。

## 関連

- [#165](https://github.com/tokudiro/text-compositor/issues/165) Viewer（親）、[#172](https://github.com/tokudiro/text-compositor/issues/172) CI（配布物のビルドと添付）、[#171](https://github.com/tokudiro/text-compositor/issues/171) 配布環境での図の描画の実機検証、[#207](https://github.com/tokudiro/text-compositor/issues/207) Mermaidの描画をElectronで行う
- [gui-viewer-spike.md](gui-viewer-spike.md) 組込版Pythonの同梱方式のスパイク（#99・#102）
