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
| **`playwright`**（Mermaid用のブラウザ操作） | **同梱しない**。Mermaidは、Electronで描画する（下記） | 約106 MB（外した分。うち、Node.jsのドライバが約88 MB） |
| PlantUML・D2・Noto Sans JP | 同梱しない（下の表） | - |

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
| `mermaid.min.js` | `mermaid`の図（取得は、組込版Python。描画は、Electron） | 約3.4 MB | jsDelivr（npm `mermaid@11.16.1`） |
| `viz-global.js`（Viz.js） | `dot`・`graphviz`の図（取得は、組込版Python。描画は、Electron。[#181](https://github.com/tokudiro/text-compositor/issues/181)） | 約1.3 MB | jsDelivr（npm `@viz-js/viz@3.30.0`） |
| Noto Sans JP | **PDF専用**（Viewerは、HTML出力で、使わない） | 約8.8 MB | GitHub Releases（`notofonts/noto-cjk`） |

サイズは、`build.py`の記載と、実際にキャッシュされたファイルの実測による。PlantUMLとD2は、初回の描画で、取得のために、数秒〜数十秒かかる（回線による）。

### Mermaidについて（Electronで描画する。#207）

**Mermaidは、Electron自身のChromiumで描画する**。Pythonの`playwright`（約106 MB）と、システムのChrome・Edgeは、要らない。

- **仕組み**: Pythonのワーカーが、Mermaidのフェンスに出会うと、標準出力（JSON行）で、描画をElectronに依頼する。Electronは、非表示のウィンドウに、`mermaid.min.js`を読み込み、`mermaid.render()`でSVGにして、標準入力で返す（プロトコルは、仕様書14章）。`mermaid.min.js`の取得（SHA256の確認・キャッシュ）は、Pythonが行い、ファイルのパスを渡す。描画用のウィンドウは、最初の図で、1回だけ作る（起動を遅くしないため）。
- **速さ**（実測。2回目以降は、SVGが、原稿の隣の`.text-compositor/cache/`に、キャッシュされる）:

| | 従来（Python + `playwright` + Chrome・Edge） | Electronで描画 |
|---|---|---|
| 最初のMermaidの図を含む変換（`check-auto-reload.js`。図を1つ変えた場合） | 1.6〜1.8秒 | **約0.47秒**（描画用のウィンドウの準備を含む） |
| 配布物で、Mermaidの図を2つ含む文書の、初回の変換 | （配布物では、動かなかった） | 約0.31〜0.35秒 |
| 2回目以降（図を変えた場合） | 約0.2秒 | 約0.2秒（変わらない） |

- **配布物での確認**: `check-dist.js`が、`playwright`もシステムのブラウザもない配布物で、2つのMermaidの図が表示されること、構文エラーが原稿の行つきで帯・一覧に出ること、組込版Pythonが、HTTPSで`mermaid.min.js`を取得できること（SHA256が一致）を、確認する。
- **Electronの外**（CLI・Python API）は、従来どおり、`playwright`を使う（環境変数`TEXT_COMPOSITOR_MERMAID_HOST=1`でワーカーを起動したときだけ、Electronに任せる）。
- **配色**は、従来と同じ設定（`htmlLabels: false`。Mermaidの既定のテーマ）にした。そのため、ダークの文書では、図の線・矢印・ラベルが、暗い背景に溶けて、読みにくい（従来から同じ。#207の確認で気づき、[#209](https://github.com/tokudiro/text-compositor/issues/209)にした）。
### Graphvizについて（Electronで描画する。#181）

**Graphvizも、Electron自身のChromiumで描画する**。システムの`dot`は、要らない。仕組みは、Mermaidと同じ（ワーカーが、標準出力で依頼し、Electronが、非表示のウィンドウで、Viz.js（GraphvizのWebAssembly版）を動かして、SVGを返す）。

- **取得**: `viz-global.js`は、初回に、jsDelivrから取得し、SHA256で確認して、ユーザーのキャッシュ（`%LOCALAPPDATA%\text-compositor\Cache\viz\`）に置く。同梱しないため、配布物の大きさは、変わらない。
- **速さ**（実測。開発機。GPUなし）: 描画用のウィンドウの準備（`viz-global.js`の読み込みを含む）は、約0.2〜0.3秒（最初の図で、1回だけ）。Viz.jsのインスタンスの作成は、約12 ms。描画は、1〜11 ms。
- **日本語の文字幅の補正**: Graphvizは、文字の幅を、内蔵の見積もり（Times系）で計算するため、日本語の長いラベルが、箱からはみ出す（20文字で、約2割）。Electronは、描いたSVGを、実際のフォントで測り、はみ出したノードだけに`width=`を足して、1回だけ描き直す（仕様書14章）。`record`形・HTMLラベル・多重の枠は、対象外。
- **ライセンス**: Viz.jsは、MIT。中に含まれる、Graphvizは、EPL-2.0、Expatは、MIT。改変せずに、そのまま使い、同梱もしない（`THIRD-PARTY-NOTICES.md`の「初回に取得するもの」に、記載する）。
- **Electronの外**（CLI・Python API）は、Graphvizを描かず、コードブロックと警告にする（PDF出力は、従来どおり、Typst側の`diagraph`）。
- **PDFとの違い**: レイアウトエンジンが、PDF出力（`diagraph`）と、Viz.jsとで、違う。同じDOTでも、配置や線の形が、少し違う場合がある。

## ライセンス表記

- 配布物の`licenses/`に、`THIRD-PARTY-NOTICES.md`（一覧）と、各ライセンスの全文を入れる。ビルドが、パッケージのメタデータ（`*.dist-info`）から、自動で作る。
- 内訳: 本体（MIT）、Python（PSF）、OpenSSL（Apache-2.0。全文を同梱）、`markdown-it-py`・`mdit-py-plugins`・`mdurl`・`platformdirs`・`PyYAML`（MIT）。ElectronとChromiumは、`LICENSE`と`LICENSES.chromium.html`（Electronの配布物に含まれるもの）。
- **未完の点**: 組込版Pythonに含まれる`libffi`・`expat`・`SQLite`・Microsoftの実行時ライブラリは、名前・ライセンス・参照先の記載に留め、全文は付けていない（python.orgの配布物と、同じ扱い）。厳密に全文を付ける必要があるかは、未確認。

## 作り方

前提: Windows、Node.js 22.12以上、インターネット接続、pipが使えるPython（ビルド用。どの版でもよい。組込版Pythonの版と、配布物のパッケージは、`--platform`の指定で、決まる）。CIでも、同じ手順で作る（下の「CIとリリース」）。

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
- Mermaidの図が、Electronで描画され、表示される。構文エラーは、原稿の行つきで、一覧に出る。組込版Pythonが、HTTPSで、`mermaid.min.js`を取得できる。
- Graphviz（`dot`・`graphviz`）の図が、システムのGraphvizなしで、Electronで描画され、表示される。構文エラーは、原稿の行つきで、一覧に出る。組込版Pythonが、HTTPSで、`viz-global.js`を取得できる。

実測（2026-09-19、開発機）: すべて成功。起動（プロセスの開始から、文書の表示まで）は、5回で、0.82〜0.90秒。開発時（`npm start`）の0.86秒と、同じ範囲である。

### クリーンなWindowsでの確認

**実際のクリーンなWindows（Pythonが入っていない別のPC）での起動は、未実施**である（別のPCを用意するのが難しい。Windows Sandboxは、管理者権限と、機能の有効化が要るため、使っていない）。代わりに、次の2つで、確認した。

1. **環境から、Pythonへの手がかりを外して起動した**（上の`check-dist.js`）。開発機には、Pythonがインストールされているが、`PATH`・`TEXT_COMPOSITOR_*`・`PYTHON*`を外しても、ワーカーは、同梱の`python-embed/python.exe`で動く。組込版Pythonは、`python312._pth`で、`sys.path`が固定され、環境変数や、インストール済みのPythonの影響を受けない。
2. **組込版Pythonが、必要とするDLLを、すべて解析した**（`scripts/check-embed-dependencies.py`。`pefile`が要る）。`python.exe`・`python312.dll`・`*.pyd`が読み込むDLLは、**フォルダに同梱のもの**（`vcruntime140.dll`・`libcrypto-3.dll`など）か、**Windowsに標準で入っているもの**（`kernel32`・`advapi32`・`ws2_32`・`crypt32`など、と、Universal CRTを含むAPIセット）だけだった。Microsoft Visual C++の再頒布可能パッケージを、別にインストールする必要は、ない。

残る不確かさは、Electron本体（Chromium）の動作環境（Windows 10以降）と、ウイルス対策ソフトや、SmartScreenの挙動である（どちらも、この環境では、確認できない）。クリーンな環境で問題が出た場合は、報告を受けて、直す。
## CIとリリース（[#172](https://github.com/tokudiro/text-compositor/issues/172)）

### リリースの方針: text-compositor本体と、同時に出す

Obunzuは、**同じバージョンのtext_compositorを同梱**する（`build-dist.js`が、ビルドしたときのリポジトリの`text_compositor`を、ZIPに写す）。バージョンも、text-compositorと同じ値にそろえる決まりがある（`tests/test_viewer_version.py`）。そのため、**`v<バージョン>`のタグを1つだけpushして、両方を同時にリリースする**。利用者からは、「v0.3.5」が1つのReleaseにあり、使い方ガイドのPDFと、Obunzuの ZIPが、同じ版とすぐ分かる。

Obunzuだけの修正を出したいときも、原則は、**両方のパッチ版を上げる**（例: 0.3.5 → 0.3.6）。text-compositorは、中身が同じでも、新しい版がPyPIに出る（害は小さく、番号が1つで済む）。どうしても、Obunzuだけを出す場合の例外の道として、`obunzu-v<バージョン>`のタグも、残してある（下）。

### ワークフロー

text-compositor本体のテスト（`test.yml`）とは、別のワークフローにする。ツールも、成果物も違うため（[gui-viewer-design.md](gui-viewer-design.md)）。

| ファイル | 起動 | 内容 |
|---|---|---|
| `.github/workflows/viewer.yml` | `viewer/`・`text_compositor/`・`pyproject.toml`の変更を含むPR・`master`へのpush。ほかのワークフローからの呼び出し | Windowsで`npm test`（Node.jsのテスト）と、実際のPythonワーカーとの結合テストを実行する。権限は、読み取りだけ |
| `.github/workflows/viewer-release.yml` | 呼び出し（`release.yml`から）、`obunzu-v*`のタグのpush、手動実行 | テスト → 配布物（ZIP）のビルド。`obunzu-v*`のときだけ、Releaseの作成と添付まで行う（例外の道） |
| `.github/workflows/release.yml` | `v*`のタグのpush | 使い方ガイドのPDF（Releaseを作る）、PyPIへの公開、`build-viewer`（上の`viewer-release.yml`を呼び出す）、`attach-viewer`（ZIPを、同じReleaseに添付する） |

- **順序**: Releaseは、`build-usage-guide`が作る。`build-viewer`は、これを待ち（`needs`）、`attach-viewer`が、そのあとで、ZIPを添付する。同じタグに、2つのジョブが同時にReleaseを作って、競合しないため。
- **失敗したとき**: PDFとPyPIへの公開は、`build-viewer`を待たない。Obunzuのビルドが失敗しても、影響しない。失敗したジョブだけを、Actionsの「Re-run failed jobs」で、再実行できる。
- **CIで確認するもの**: Node.jsのテストと、実際のPythonワーカーとの結合（`viewer/test/worker-integration.test.js`。Markdown・CSV（`csv_header`）・存在しないファイルの`render_html`の往復と、ワーカーの常駐）。ワーカーとの結合テストは、Pythonの準備がない手元では、飛ばし、CIでは（`REQUIRE_WORKER_INTEGRATION=1`）、飛ばさず、失敗にする。
- **CIで確認しないもの**: ElectronのGUIの起動と、展開した配布物の起動（`check-dist.js`）。画面が要り、不安定になりやすいため、手元で行う。Mermaid・PlantUML・D2の実際の描画も、対象外（外部のツールや、ダウンロードが要る）。
- **バージョンの確認**: タグは、`viewer/package.json`の`version`と、そろえる（`v<バージョン>`か、`obunzu-v<バージョン>`。そろっていなければ、ビルドの前に失敗する）。
- **PyPIとの分離**: PyPIのTrusted Publishingは、`release.yml`と`pypi`環境に紐づいている。`id-token`の権限は、`publish-pypi`だけが持つ。Viewerのビルド・添付のジョブ（`build-viewer`・`attach-viewer`）にも、`viewer-release.yml`にも、与えない。
- **「Latest」・本文**: `v*`のReleaseの本文と「Latest」は、`build-usage-guide`が決めた結果のまま（`attach-viewer`は、ファイルを添付するだけ。**未検証**。初回のリリースで、確認する）。例外の道（`obunzu-v*`）は、`make_latest: false`で作り、text-compositor本体のReleaseの「Latest」表示を、奪わない。

### リリースの手順（通常）

1. `pyproject.toml`と、`viewer/package.json`・`viewer/package-lock.json`の`version`を、同じ値に上げる（`tests/test_viewer_version.py`が確認する）。
2. 事前に、Actionsの「Viewer release」を、手動で実行する。テストと、配布物のビルドが通り、成果物（`obunzu-win-x64`）として、ZIPを取得できる。Releaseは、作られない。
3. text-compositor側の事前の確認（wheelの内容など）を行う。
4. タグ`v<バージョン>`を、`master`に打って、pushする。`release.yml`が、PDFとPyPIと、Obunzuの ZIPを、順に、同じReleaseへ集める。
5. Releaseの本文は、自動生成されたたたき台になる。公開後に、`gh release edit`で、英語と日本語の両方に、書き直す。

### Obunzuだけを出す（例外）

1. Obunzuだけの修正を入れ、`pyproject.toml`と、`viewer/package.json`・`viewer/package-lock.json`の`version`を、同じ値に上げる（バージョンを、そろえる決まりは、この場合も同じ）。`pyproject.toml`の版は、上がるが、PyPIには、公開されない（次の`v`のタグのときに、公開される）。
2. タグ`obunzu-v<バージョン>`を、`master`に打って、pushする。`viewer-release.yml`が、テスト → ビルド → Releaseの作成と添付を、行う。

ビルドで使う`tar`は、Windows標準の`System32\tar.exe`を、明示する。GitHub ActionsのWindowsのランナーは、PATHの先頭に、Gitに付属のGNU tar（zipを扱えない）があることがあるため。

## 更新の方法

- **新しいZIPを取得して、展開し直す**（フォルダごと置き換える）。自動更新は、行わない（署名と、配布の基盤が要るため。必要になったら、別に検討する）。
- 設定・ウィンドウの状態は、`%APPDATA%\Obunzu\settings.json`に、図のキャッシュ等は、`%LOCALAPPDATA%\text-compositor\`にあり、アプリのフォルダの外のため、置き換えても、残る。
- **Chromium（Electron）の更新**は、Electronの版を上げて、Obunzuの新版を出すことで、行う。組込版Pythonと、パッケージも、同様（版は、`build-dist.js`と`dist-requirements.txt`で固定している）。セキュリティ更新が出たときは、新版を出す。

## 関連

- [#165](https://github.com/tokudiro/text-compositor/issues/165) Viewer（親）、[#172](https://github.com/tokudiro/text-compositor/issues/172) CI（配布物のビルドと添付）、[#171](https://github.com/tokudiro/text-compositor/issues/171) 配布環境での図の描画の実機検証、[#207](https://github.com/tokudiro/text-compositor/issues/207) Mermaidの描画をElectronで行う（実装済み）
- [gui-viewer-spike.md](gui-viewer-spike.md) 組込版Pythonの同梱方式のスパイク（#99・#102）
