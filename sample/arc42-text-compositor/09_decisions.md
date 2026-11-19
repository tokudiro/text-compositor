# 9 アーキテクチャ上の決定

構成を決めた主な判断を、1件ずつ記録する。各決定は、状況・検討した代替案・決定・結果の4つと、関連するASR（品質目標・シナリオ・制約）で書く。**検討の記録がリポジトリに残っていない部分は、「記録なし」と書き、制約から導ける理由は、「推測」と書く。**

| 番号 | 決定 | 関連 |
| --- | --- | --- |
| ADR-1 | 組版エンジンは、Typstにする。入力は、markdown-it-pyのASTから、Typstへ変換する | Q1・Q2、TC2・TC6 |
| ADR-2 | 図表は、外部ツールに委譲し、取得・版の固定・キャッシュまで、ツールが引き受ける | Q1・Q2、TC3・TC5 |
| ADR-3 | MermaidはブラウザMermaid、PlantUMLはJavaで描く。自動取得の既定は、非対称にする | Q2、TC3 |
| ADR-4 | Viewerの表示エンジンは、Electron（調整）にする | Q3、TC4 |
| ADR-5 | ViewerとPythonは、常駐サブプロセスと、標準入出力のJSON行でつなぐ。状態は、ワーカーが持つ | Q3 |
| ADR-6 | Obunzuは、全部入りのポータブルなZIPで配る | Q2、TC4、OC6 |
| ADR-7 | 描画の失敗は、Fail-fastで報告する | F5、Q1 |
| ADR-8 | PlantUMLは、`ALLOWLIST`で起動する | Q5 |
| ADR-9 | text-compositorとObunzuは、同じ版・同じタグで、同時にリリースする | OC3、Q2 |

## ADR-1 組版エンジンは、Typstにする

**状況**: [[原稿]]を、人が見た目を調整せずに、PDFにする（1.2）。コアは、Pythonだけで完結させ、重い実行環境を要求しない（TC1）。

**検討した代替案**: 記録なし。リポジトリの文書に、他の組版エンジンとの比較は、残っていない（未確認）。制約から導ける理由は、次のとおり（推測）。TeXなどの大きな配布物を、利用者に入れさせると、TC1・方針3に反する。

**決定**: Typstにする。Markdownは、文字列置換ではなく、markdown-it-pyのASTから、Typstへ、[[決定論的出力]]になるように対応づける。

**結果**
- 良い点: コンパイラが、PyPIの`typst`（wheel）に入っていて、`pip install`だけで済む（TC2）。WASMのTypstパッケージ（`diagraph`・`kip`・`cetz`・`fletcher`など）で、Graphviz・Pikchr・CeTZなどを、外部のバイナリなしで描ける（[#264](https://github.com/tokudiro/text-compositor/issues/264)）。`typst.Compiler`を使い回せる（6.2）。
- 悪い点: Typstの記法と衝突する文字（`#`・`$`・`@`など）の、エスケープが要る。行頭の`=`・`-`は、見出しやリストになるため、実害が出た（`doc/spec.md`9章）。`diagraph`は、Graphvizの一部の記法を描けない（R7）。
- 見直す条件: 記録なし。

**関連するASR**: Q1・Q2、TC2・TC6

## ADR-2 図表は、外部ツールに委譲し、取得・固定・キャッシュまで引き受ける

**状況**: 図の種類が多い（Mermaid・PlantUML・D2・Graphvizなど）。「ツールごとに、環境を入れる」ことを、利用者に求めたくない（方針3）。

**検討した代替案**
- A: Asciidoctor Diagramのように、各ツールの実行環境を、利用者が事前に入れる前提にする（純粋なディスパッチ層）。（[#308](https://github.com/tokudiro/text-compositor/issues/308)）
- B: 実行環境が無いとき、取得・版の固定・キャッシュまで、ツール自身が引き受ける。

**決定**: Bを採る。取得物は、URLとSHA256を固定し、`.part`を経て置き換える。図のSVGは、`(図の種類, ツールの版, 入力)`のハッシュでキャッシュする。外部のAPI・SaaSは、使わない（TC5）。

**結果**
- 良い点: 利用者は、図ごとの環境を整えなくてよい。同じ入力は、同じ図になる（Q1）。
- 悪い点: 同梱・取得した部品の更新は、こちらの責任になる。脆弱性の修正は、新しい版を出すまで、利用者に届かない（R3）。ツールを足すたびに、手で同期する場所が増える（R9）。
- 見直す条件: 描画を、Java・ブラウザに依存しない自作の変換器に置き換える設計がある（[#474](https://github.com/tokudiro/text-compositor/issues/474)）。

**関連するASR**: Q1・Q2・Q4、TC3・TC5

<!-- pagebreak -->

## ADR-3 MermaidはブラウザMermaid、PlantUMLはJavaで描く

**状況**: Mermaidは、ブラウザ内でしか動かない。PlantUMLは、Java（11以上）が要る。

**検討した代替案**
- A: どちらも、既定で、必要な実行環境を自動取得する。
- B: PlantUMLのJREは自動取得し、Mermaidのブラウザは、システムのChrome・Edgeを使い、既定では取得しない。

**決定**: Bを採る。`plugins.plantuml_auto_download`は、既定`true`（JRE 約49.7 MB）。`plugins.mermaid_auto_download`は、既定`false`（Chromium 約700 MB）。JavaのバージョンやChromeの有無は、システムのものを検出して再利用する。Mermaidの`htmlLabels`は、`false`にする（Typstが`<foreignObject>`を描けないため）。PlantUMLは、純JavaのレイアウトエンジンSmetanaを使い、Graphvizのバイナリを要らなくする。

**結果**
- 良い点: ダウンロードの量が、利用者の想定を超えない。
- 悪い点: ブラウザが無い環境で、Mermaidは、Fail-fastで止まる（既定）。ダーク配色の文書で、Mermaidの線が、背景に溶ける（[#209](https://github.com/tokudiro/text-compositor/issues/209)。D3）。
- 見直す条件: Mermaidをブラウザ以外で描ける変換器ができたとき（[#474](https://github.com/tokudiro/text-compositor/issues/474)）。

**関連するASR**: Q2、TC3

## ADR-4 Viewerの表示エンジンは、Electron（調整）にする

**状況**: Viewerは、HTMLを表示する。起動から表示まで1秒以内を基準にし、何も描かれない時間を、長く見せない（Q3）。

**検討した代替案**: 最小のアプリで、同じ12 KBのHTMLを、10回ずつ測った（Windows 11、`doc/html-viewer-benchmark.md`）。

| 候補 | 画面が落ち着く | メモリ | 体感 |
| --- | --- | --- | --- |
| Electron（調整） | 0.52秒 | 約67 MB | 表示の遅れを、最も感じない |
| Tauri（wry。調整） | 0.70秒 | 約75 MB | 白い画面が出て、遅く感じる |
| WebView2（.NET。調整） | 0.83秒 | 約80 MB | 白い画面が出る |

**決定**: Electron（`--disable-gpu --in-process-gpu`の調整）にする（2026-09-19。[#180](https://github.com/tokudiro/text-compositor/issues/180)）。体感の遅さは、「何も描かれない時間」で決まる。

**結果**
- 良い点: 白い画面の時間が、最も短い。Mermaidなどを、自分のChromiumで描ける（6.3）。
- 悪い点: Chromiumを同梱するため、配布物が大きい（R5）。体感は、1人の所感である。
- 見直す条件: 表示エンジンの差し替えを、`doc/viewer-engine-architecture.md`の設計で、可能にしてある（WebView2の殻は、[#285](https://github.com/tokudiro/text-compositor/issues/285)）。
- **前の決定を置き換えた**: 先に、C#とAvaloniaで、PDFを表示する案が決まっていた（[#166](https://github.com/tokudiro/text-compositor/issues/166)）。Viewerを、「閲覧専用・軽量・Diagrams as Code」に組み直した（[#165](https://github.com/tokudiro/text-compositor/issues/165)）ため、表示方法は、見直し対象になった。連携方式（ADR-5）は、引き継いだ。

**関連するASR**: Q3、TC4

## ADR-5 ViewerとPythonは、常駐サブプロセスと、JSON行でつなぐ

**状況**: PythonのMarkdown変換を、GUIから、何度も呼ぶ。

**検討した代替案**: 埋め込み（pythonnet・PyO3）。埋め込みで、実際に問題が起きた: PyO3のビルドで、組込版Pythonに無い`.lib`が要る。pythonnetの終了時にハングする。手作業の`site-packages`が、`requirements.txt`に追従しない。（`doc/gui-viewer-design.md`）

**決定**: Pythonを、常駐サブプロセスとして起動し、標準入出力のJSON行で依頼する。通信は、約0.035 msで、無視できる。ローカルのポートは、開かない。のちに、変更の検知・変換のキュー・自動更新の状態を、Electronから、ワーカーへ移した（[#187](https://github.com/tokudiro/text-compositor/issues/187)・[#284](https://github.com/tokudiro/text-compositor/issues/284)）。

**結果**
- 良い点: Pythonが落ちても、画面に波及せず、起動し直せる。新しい殻（WebView2など）は、プロセスの起動と標準入出力だけで、つなげる。
- 悪い点: ワーカーが、依頼を1件ずつ順に処理する。タブが多いと、変換が待つ（`worker.py`は、標準入力の読み手を1スレッドにし、書き込みと変換を`Lock`で直列にする）。
- 見直す条件: 記録なし。

**関連するASR**: Q3

<!-- pagebreak -->

## ADR-6 Obunzuは、全部入りのポータブルなZIPで配る

**状況**: 方針3は、「ZIPを展開して起動するだけで、別のインストールなしに、対応する図を描けること」。

**検討した代替案**: インストーラー（アンインストール対応）。署名と、配布の基盤が要る。wingetでの配布も、準備中（[#334](https://github.com/tokudiro/text-compositor/issues/334)）。

**決定**: ポータブルなZIPで配る。展開して、`obunzu-markdown-viewer.exe`を起動する。レジストリには書かない。Python・Java・PlantUML・D2・Mermaidなどを、すべて[[同梱]]する。大きさ（約297.8 MB、展開後約698.3 MB）は、許容する（削減は、行わない）。

**結果**
- 良い点: 初回起動時の、追加のダウンロードが、ゼロになった。削除は、フォルダごと消すだけ。
- 悪い点: 大きい（R5）。コード署名がないため、SmartScreenが警告を出す場合がある（推測。R2）。更新は、手で、新しいZIPに置き換える。
- 見直す条件: 署名が必要になったとき。更新の確認（[#341](https://github.com/tokudiro/text-compositor/issues/341)）を入れるときは、既定で無効にする（OC2）。

**関連するASR**: Q2、TC4、OC6

## ADR-7 描画の失敗は、Fail-fastで報告する

**状況**: 図が描けなかったとき、テキストへ戻すと、見た目が静かに崩れ、気づかない文書が公開される。

**決定**: 描画に失敗したら、診断（原稿の行つき）を出して、終了する。configの誤りは、描画の前に報告する。例外は、Typstの版の不一致（警告だけで続ける。[#49](https://github.com/tokudiro/text-compositor/issues/49)）。

**結果**
- 良い点: 失敗が、見落とされない。既存のPDFは、壊れない。
- 悪い点: 1つの図の失敗で、全体が止まる。ブラウザが無い環境で、Mermaidが、使えない（ADR-3）。

**関連するASR**: F5、Q1

## ADR-8 PlantUMLは、`ALLOWLIST`で起動する

**状況**: 既定（LEGACY）のままだと、図の`!include`が、プロジェクトの外のファイルや公開URLを読めた（実機で確認。[#622](https://github.com/tokudiro/text-compositor/issues/622)）。

**決定**: 環境変数`PLANTUML_SECURITY_PROFILE=ALLOWLIST`で、`plantuml.jar`を起動する。標準ライブラリ（`!include <C4/C4_Container>`・`!theme`）は、使えるまま、ファイルとURLの取り込みを拒否する。自作の`!include`は、原稿のフォルダの中だけ許す（`PLANTUML_INCLUDE_PATH`）。

**結果**: 原稿の書き手も、実行する人も、設定で緩められない。`include.path`は、JVM全体の設定で、複数のフォルダを並べると、同名のファイルを取り違えるため、ファイルを取り込む図だけ、原稿のフォルダごとに、起動を分ける。

**関連するASR**: Q5

## ADR-9 text-compositorとObunzuは、同時にリリースする

**状況**: Obunzuは、同じ版のtext-compositorを同梱する。

**決定**: バージョンを、そろえる（`tests/test_viewer_version.py`）。タグ`v<バージョン>`を1つだけpushして、両方を、同時にリリースする。Obunzuだけの修正も、原則は、両方のパッチ版を上げる。例外の道は、タグ`obunzu-markdown-viewer-v<バージョン>`。

**結果**: 版上げの書き換えが、8か所になる（6.6）。PyPIの公開は、`pypi`環境と`release.yml`に紐づけ、`id-token`は、`publish-pypi`だけが持つ。Obunzuのビルドの失敗は、PyPIの公開を止めない。

**関連するASR**: OC3、Q2
