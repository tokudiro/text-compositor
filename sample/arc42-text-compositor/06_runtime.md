# 6 実行時の見方

text-compositorの主な流れを、6つのシナリオで示す。数値は、リポジトリの文書にある計測値で、条件（Windows 11・開発機など）は、出典の文書にある。値は、実行のたびに10〜30%ばらつく（`doc/gui-viewer-design.md`）。

**書かなかったシナリオと理由**: CLIの`--watch`（原稿の変更で、PDFを作り直す）は、6.1を、6.2と同じ変更検知（`changes.py`）で繰り返すだけで、構造が同じである。HTMLを1ファイルに出す`render_html`は、6.2のワーカーの変換と同じ経路である。

## 6.1 CLIでPDFを作る

```plantuml
@startuml
!include <C4/C4_Dynamic>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(author, $author_name, "")
Container(engine, $engine_name, $engine_tech, "")
Container(tools, $tools_name, $tools_tech, "")
Container(typst, $typst_name, $typst_tech, "")
ContainerDb(cache, $cache_name, $cache_tech, "")

Rel(author, engine, "text-compositor --config を実行する")
Rel(engine, cache, "図のSVGを探す")
Rel(engine, tools, "見つからない図を描かせる")
Rel(tools, engine, "SVGを返す")
Rel(engine, cache, "SVGを保存する")
Rel(engine, typst, "Typstのコードを渡す")
Rel(typst, engine, "PDFを返す")
Rel(engine, author, "PDFと診断を出す")
@enduml
```

| 手順 | 処理 | 入力・出力・失敗したときの動作 |
| --- | --- | --- |
| 1 | `--if-changed`のとき、出力のPDFが、configと入力・テンプレート・ツール自身より新しければ、何もせず終わる | 更新時刻だけで判断する。Typstの版やプロジェクトの外のファイルの変更は、見ない（`README.md`）。付けなければ、必ず作り直す |
| 2 | configを読み、許可キー・変数・`lint`・`plugins`を検証する | 誤りは、描画を始める前に、Fail-fastで報告する。変数が未設定のときも、ここで止まる |
| 3 | `chapters`を展開し、章ごとに、Markdownを、ASTからTypstへ変換する | 行頭の`=`・`-`・`+`などは、エスケープする。変換できない記法の警告は、原稿の行つきで出す |
| 4 | 図のフェンスごとに、キャッシュを探す。無ければ、ツールで描く | キーは、`(図の種類, ツールの版, 入力)`のハッシュ。PlantUMLは、1回のビルドで、まとめて描く（Javaの起動は、約1.5秒かかる。`doc/gui-viewer-design.md`） |
| 5 | Typstのコードを、中間ファイルに書き、テンプレートと一緒にコンパイルする | フォントは、`font_paths`で、Noto Sans JPなどを指定する。初回のコンパイルで、Typstのパッケージを取得する（6.5） |
| 6 | PDFを書き出し、中間ファイルを削除する | Typstのエラーは、位置を元のMarkdownの行に直して、診断にする。終了コードは、0以外になり、既存のPDFは、壊さない |

実測（Windows 11。`doc/gui-viewer-design.md`・`doc/spec.md`14章）: 図が無い文書のコンパイルは、約30〜60 ms。Mermaidの図を含むCLIのビルドは、ビルドごとにブラウザを起動するため、約1.8秒（図1つあたり、約1.3秒）かかる。

<!-- pagebreak -->

## 6.2 Obunzuで、保存してから表示が更新されるまで

```plantuml
@startuml
!include <C4/C4_Dynamic>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(author, $author_name, "")
Container(viewer, $viewer_name, $viewer_tech, "")
Container(worker, $worker_name, $worker_tech, "")
ContainerDb(cache, $cache_name, $cache_tech, "")

Rel(author, worker, "原稿を保存する（エディタで）")
Rel(worker, worker, "更新時刻とサイズの変化を検知する")
Rel(worker, cache, "図のSVGを読む")
Rel(worker, viewer, "renderedイベント（HTMLと診断）")
Rel(viewer, author, "表示を更新する。スクロール位置を保つ")
@enduml
```

| 手順 | 処理 | 入力・出力・失敗したときの動作 |
| --- | --- | --- |
| 1 | タブを開くと、Electronが`open`を送る。ワーカーは、変換して、HTMLを返す。以後、原稿と、画像などの参照ファイル（`dependencies`）を監視する | 変換に失敗した文書も、原稿は監視し続ける（直して保存したときに、自動で更新するため） |
| 2 | 書き手が保存する。ワーカーの監視が、更新時刻とサイズの変化を検知する（`changes.py`の`_watch_snapshot`） | 原子的な保存（一時ファイルへ書いて、名前を付け替える）も、検知できる。原稿が一時的に無いときは、現れるまで、再変換を保留する |
| 3 | ワーカーが、再変換する。図は、キャッシュが命中すれば、描かない | 変換は、1件ずつ直列に処理する（`Lock`）。同じ文書の待ちは、最新の1件だけ残す |
| 4 | ワーカーが、`rendered`イベント（HTML・診断・所要時間・依存ファイル）を出す | `ok`が偽でも、`diagnostics`に内容が入る。Electronは、エラーの帯を出す |
| 5 | Electronが、同じ文書の再読み込みとして、スクロール位置を保って表示する | 履歴・見出しへの移動は、`open`を呼んだ側の事情で、`rendered`には関わらない |

実測と目標: ワーカー側の通常の編集は、35〜62 msで決まる（`doc/gui-viewer-design.md`）。GUI側の描画は、数msである。目標は、図のキャッシュが命中する通常の文書で、保存から表示の更新まで300 ms以内（デバウンス込み。同文書の案。#170）。実際のElectron上で、この目標を測り直した記録は、未確認である。

<!-- pagebreak -->

## 6.3 ObunzuでMermaidを描く

```plantuml
@startuml
!include <C4/C4_Dynamic>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Container(worker, $worker_name, $worker_tech, "")
Container(viewer, $viewer_name, $viewer_tech, "")
ContainerDb(cache, $cache_name, $cache_tech, "")

Rel(worker, cache, "SVGのキャッシュを探す")
Rel(worker, viewer, "render_mermaidを頼む（JSON行）")
Rel(viewer, viewer, "非表示のウィンドウで、mermaid.render()を呼ぶ")
Rel(viewer, worker, "SVGを返す")
Rel(worker, cache, "SVGを保存する")
@enduml
```

| 手順 | 処理 | 入力・出力・失敗したときの動作 |
| --- | --- | --- |
| 1 | ワーカーが、Mermaidのフェンスに出会い、キャッシュを探す | キーは、`mermaid.min.js`のSHA256を含む。版を上げると、古いSVGは、使われない |
| 2 | 無ければ、`render_mermaid`を、標準出力で、Electronに頼む | 環境変数`TEXT_COMPOSITOR_MERMAID_HOST=1`で起動したときだけ。無ければ、ワーカーが、Playwrightで描く |
| 3 | Electronが、非表示のウィンドウに、同梱の`mermaid.min.js`を読み込み、描く | 設定は、`htmlLabels: false`。ラベルを`<text>`で出す（Typstが`<foreignObject>`を描けないため） |
| 4 | SVGを、標準入力で返す。ワーカーが、キャッシュに保存する | 構文エラーは、原稿の行つきで、診断にする |

実測（`doc/viewer-distribution.md`）: 図を1つ変えた最初の変換が、約0.47秒（従来の1.6〜1.8秒）。配布物で、図を2つ含む文書の初回は、約0.31〜0.35秒。2回目以降は、約0.2秒。

## 6.4 図の描画が失敗したとき

PlantUMLの構文エラーを例にする。

| 手順 | 処理 | 結果 |
| --- | --- | --- |
| 1 | `java -jar plantuml.jar`が、0以外の終了コードで終わる | テキストへ静かに戻さない（ADR-7） |
| 2 | [[診断]]を作る。`message`は短い要約（`plantuml diagram failed to render`など）、ツールの出力は`detail` | `file`・`line`は、原稿でのフェンスの開始行。図の中の行は、原稿の行に直す |
| 3 | CLIは、`[Error]`を出して、終了コード0以外で終わる。Obunzuは、エラーの帯と、診断の一覧に出す | 既存のPDFは、壊さない（6.1の手順6）。Mermaidの出力からは、ブラウザ内部のスタックの行を省く |

## 6.5 初回の取得

| 手順 | 処理 | 入力・出力・失敗したときの動作 |
| --- | --- | --- |
| 1 | 初回のビルドで、キャッシュに、フォント・`plantuml.jar`・JREなどが無いと、取得する。`[Info] Downloading ... (one-time; cached under ...)`と出す | 取得物は、`.part`へ書き、SHA256が一致したときだけ置き換える |
| 2 | 一時的な失敗（HTTPの5xx・408・429、接続エラー、時間切れ、途中で切れた転送）は、1秒・3秒の間隔で、合計3回まで再試行する | 404・書き込みの失敗・SHA256の不一致は、再試行せず、エラー終了する |
| 3 | 初回のコンパイルで、Typstが、`@preview/...`のパッケージを取得する | Typstの内部で行うため、再試行できない。CIでは、`~/.cache/typst`を保存して、軽減する（R6） |

Obunzuは、取得が要らない（Q2）。ただし、`mermaid.min.js`などを、HTTPSで取得できることは、配布物の確認の項目になっている（`doc/viewer-distribution.md`）。

<!-- pagebreak -->

## 6.6 リリース

```plantuml
@startuml
!include <C4/C4_Dynamic>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(maint, $maint_name, "")
System_Ext(gh, $gh_name, "")
System_Ext(pypi, $pypi_name, "")

Rel(maint, maint, "pytestと、wheelの確認を行う")
Rel(maint, gh, "タグ v<バージョン> をpushする")
Rel(gh, gh, "release.yml: ガイドのPDFとReleaseを作る")
Rel(gh, pypi, "publish-pypi: 公開する（取り消せない）")
Rel(gh, gh, "build-viewer → attach-viewer: ZIPを添付する")
@enduml
```

| 手順 | 処理 | 入力・出力・失敗したときの動作 |
| --- | --- | --- |
| 1 | 版を上げる。次の8か所を、同じ値にする: `pyproject.toml`、`viewer/package.json`、`viewer/package-lock.json`（2か所）、`text_compositor/worker.py`、`doc/spec.md`、`doc/usage/13_python_api.md`、`doc/viewer-distribution.md`、`doc/obunzu-guide/01_about.md` | `pyproject.toml`と`viewer/package.json`の一致は、`tests/test_viewer_version.py`が確かめる。版上げだけのPRでは、`test.yml`は動かない（C5） |
| 2 | Actionsの「Viewer release」を、手動で実行する | テストと配布物のビルドが通り、ZIPが成果物になる。Releaseは、作られない |
| 3 | `pytest`・`pyproject-build --wheel`（`python -m build`は使わない。リポジトリ直下の`build.py`と、名前が衝突する）・新しいvenvで、wheelを使った文書のHTMLとPDFの確認 | PyPIは、同じ版を再アップロードできない（OC3）。必ず、タグの前に行う |
| 4 | 公開の前に、確認を取る | タグのpushで、PyPIへ自動で公開される。`pypi`環境に、承認の保護は付いていない（OC3・OC4） |
| 5 | タグ`v<バージョン>`を、`master`に打って、pushする | `release.yml`が、ガイドのPDF・PyPI・ObunzuのZIPを、同じReleaseに集める。PDFとPyPIは、`build-viewer`を待たない（Obunzuのビルドが失敗しても、公開は止まらない） |
| 6 | Releaseの本文を、英語と日本語で書き直す。セキュリティ更新があれば、更新した部品と版を書く | 自動生成の本文は、たたき台である |

Obunzuだけを出す例外の道として、タグ`obunzu-markdown-viewer-v<バージョン>`がある。このときも、版は、そろえる決まりである。
