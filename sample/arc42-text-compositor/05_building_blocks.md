# 5 構成要素の見方

text-compositorの構造を、2つのレベルで示す。レベル1は全体（コンテナ）、レベル2は変換エンジンの内部（コンポーネント）である。

## 5.1 レベル1: text-compositor

```plantuml
@startuml
!include <C4/C4_Container>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(author, $author_name, $author_desc)
Person(reader, $reader_name, "")

System_Boundary(tc, $tc_name) {
    Container(engine, $engine_name, $engine_tech, $engine_desc)
    Container(worker, $worker_name, $worker_tech, $worker_desc)
    Container(viewer, $viewer_name, $viewer_tech, $viewer_desc)
    Container(typst, $typst_name, $typst_tech, $typst_desc)
    Container(tools, $tools_name, $tools_tech, $tools_desc)
    ContainerDb(cache, $cache_name, $cache_tech, $cache_desc)
}
System_Ext(net, "取得元", "GitHub・jsDelivr・Typstパッケージの配布元")

Rel(author, engine, "text-compositorコマンドを実行する", "CLI / Python API")
Rel(reader, viewer, "文書を開いて読む")
Rel(viewer, worker, "依頼を送り、結果を受ける", "標準入出力（JSON行）")
Rel(worker, engine, "同じコードを呼ぶ", "Python")
Rel(engine, typst, "Typstのコードを渡す", "関数呼び出し")
Rel(engine, tools, "図のソースを渡す", "子プロセス・CDP")
Rel(worker, viewer, "Mermaidなどの描画を頼む", "JSON行（逆方向）")
Rel(engine, cache, "SVGと部品を読み書きする", "ファイル")
Rel(engine, net, "部品を取得する", "HTTPS")
Rel(typst, net, "パッケージを取得する", "HTTPS")
@enduml
```

<!-- pagebreak -->

| 構成要素 | 責務 | 技術 |
| --- | --- | --- |
| 変換エンジン | 原稿を読み、Typstのコードへ変換し、図を描き、PDF（とHTML）を出す。CLI（`text-compositor`）とPython API（`Session`）の入口を持つ | Python 3.10以上。`markdown-it-py`・`mdit-py-plugins`・`PyYAML`・`platformdirs`・`typst`に依存（`requirements.txt`） |
| [[常駐ワーカー]] | Viewerのような呼び出し元のために、変換エンジンを常駐させる。文書ごとに、監視と再変換をする | `python -m text_compositor.worker`。コードは、変換エンジンと同じパッケージ |
| Obunzu | 文書を開き、HTMLで表示する。タブ・フォルダの木・検索・設定・自動更新。ワーカーを子プロセスとして起動する | Electron 45・Node.js（`viewer/`）。画面は、HTML・CSS・JS（`viewer/src/chrome/`） |
| Typstコンパイラ | Typstのコードを、PDFまたはSVGにする。Typstのパッケージ（`diagraph`など）を使う | PyPIの`typst==0.15.2`。プロセス内で動く。`typst.Compiler`は、常駐中、使い回す |
| 図表ツール | 図のソースをSVGにする。PlantUML・Structurizr（Java）、D2、Mermaid（ブラウザ） | Eclipse Temurin JRE 21、`plantuml-mit-1.2026.10.jar`、D2 v0.9.0、Structurizr CLI、`mermaid.min.js` 12.3.0 |
| キャッシュ | 図のSVGと、取得した部品を保存する | ファイル。SVGは、原稿の隣の`.text-compositor/cache/`（Viewerは、アプリの領域の`cache/`。[#258](https://github.com/tokudiro/text-compositor/issues/258)）。部品は、ユーザーのキャッシュ領域（Linuxは`~/.cache/text-compositor`、Windowsは`%LOCALAPPDATA%\text-compositor\Cache`） |

- Graphviz・Pikchr・CeTZ・Fletcher・timeliney・finiteは、図表ツールを使わない。Typstのパッケージ（`diagraph`・`kip`・`cetz`・`fletcher`・`timeliney`・`finite`）が、Typstコンパイラの中で描く（[#264](https://github.com/tokudiro/text-compositor/issues/264)・[#213](https://github.com/tokudiro/text-compositor/issues/213)・[#236](https://github.com/tokudiro/text-compositor/issues/236)・[#294](https://github.com/tokudiro/text-compositor/issues/294)）。
- Vega-Lite・Vega・WaveDrom・Bytefieldは、ブラウザ（pip版）またはElectron（Obunzu）で、JSを動かして描く。

<!-- pagebreak -->

## 5.2 レベル2: 変換エンジン

```plantuml
@startuml
!include <C4/C4_Component>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Container_Boundary(engine, $engine_name) {
    Component(entry, $entry_name, $entry_tech, $entry_desc)
    Component(project, $project_name, $project_tech, $project_desc)
    Component(cfg, $cfg_name, $cfg_tech, $cfg_desc)
    Component(rend, $rend_name, $rend_tech, $rend_desc)
    Component(html, $html_name, $html_tech, $html_desc)
    Component(diag, $diag_name, $diag_tech, $diag_desc)
    Component(deps, $deps_name, $deps_tech, $deps_desc)
    Component(comp, $comp_name, $comp_tech, $comp_desc)
    Component(diagn, $diagn_name, $diagn_tech, $diagn_desc)
    Component(tmpl, $tmpl_name, $tmpl_tech, $tmpl_desc)
}
Container(typst, $typst_name, $typst_tech, "")
Container(tools, $tools_name, $tools_tech, "")
ContainerDb(cache, $cache_name, $cache_tech, "")

Rel(entry, project, "ビルドを依頼する")
Rel(project, cfg, "設定と章を読む")
Rel(project, rend, "章をTypstに変換させる")
Rel(project, comp, "コンパイルを依頼する")
Rel(html, rend, "継承する")
Rel(rend, diag, "図のフェンスを渡す")
Rel(diag, deps, "部品を探す・取得する")
Rel(diag, tools, "描かせる")
Rel(diag, cache, "SVGを読み書きする")
Rel(deps, cache, "部品を保存する")
Rel(comp, typst, "コンパイルする")
Rel(cfg, tmpl, "テンプレートを選ぶ")
Rel(rend, diagn, "警告を出す")
Rel(comp, diagn, "エラーを出す")
@enduml
```

<!-- pagebreak -->

## 5.3 構成要素の詳細

| コンポーネント | 責務の詳細 | 守る決まり |
| --- | --- | --- |
| 入口（`build.py`・`api.py`） | `build.py`は、CLI（引数の解析・`--clean`・`--watch`・`--if-changed`・`--check-env`）。`api.py`は、`Session.build()`と`Session.render_html()`。リポジトリ直下の`build.py`は、後方互換のラッパー | `import text_compositor`は軽く、`markdown-it`と`typst`を、使うまで読み込まない（`doc/spec.md`14章） |
| ビルド本体（`project.py`） | `_build_one`（CLI）と`_build_project`（CLIとPython APIが共有）。所要時間（`render`・`compile`）を、ミリ秒で返す | 副作用（作業ディレクトリ・図の描画）より前に、`--if-changed`と、設定の誤りを判定する（Fail-fast） |
| 設定・章の展開 | `config.yaml`の許可キーの検証、変数（`{{KEY}}`）の展開、`chapters`の展開（拡張子で、Markdown・CSV・図表ソース・コードに分ける）、表紙・目次・用語索引・改訂履歴 | 見た目の既定値は、テンプレートが持つ。`config.yaml`は、既定と違うときだけ、上書きする（`doc/spec.md`1章） |
| Markdown→Typst変換（`renderer.py`と、5つのミックスイン） | `TokenMixin`（ブロックの走査・行番号）、`InlineMixin`、`TableMixin`、`LayoutMixin`（`:::`のブロック）、`DiagramMixin`（図）。全ミックスインの状態は、`TypstRenderer`が持つ | 依存は、ミックスインから`renderer.py`へ向かわない。特殊文字（`#`・`$`・`@`など）は、必ずエスケープする（`doc/spec.md`3章・9章） |
| HTML出力（`html_output.py`） | `HtmlRenderer`が、`TypstRenderer`を継承し、同じ変換をHTMLに出す。Typstを要する部品（数式・Graphvizなど）だけ、Typstでコンパイルして、SVGにする | 数式やGraphvizを含まないHTML出力は、`typst`を`import`しない（起動が速い） |
| 図の描画（`renderer_diagrams.py`・`*_render.py`） | 図のフェンスの言語から、描き方を振り分ける。結果のSVGを、`(図の種類, ツールの版, 入力)`のハッシュでキャッシュする。外部ツールの出力を、診断にする | 描画に失敗したら、テキストへ静かに戻さず、診断つきで終了する（ADR-7）。図の中の行を、原稿の行へ直して報告する |
| 外部部品の取得・検出（`deps.py`・`env_check.py`） | Noto・JRE・jar・D2・JSの、URLとSHA256を固定して持つ。システムのJava（11以上）・ブラウザ・D2を検出して再利用する。`--check-env`の項目を持つ | 取得物は、SHA256を確かめてから使う。ネットワーク取得の再試行は、合計3回まで |
| コンパイル・位置の対応づけ（`compiler.py`） | Typstをコンパイルし、エラーの位置を、中間ファイル（`temp_build.typ`）から、元のMarkdownの行へ直す（srcmap） | 成功したら、中間ファイルを削除する。失敗したビルドは、既存のPDFを壊さない |
| 診断（`diagnostics.py`） | `error`・`warning`・`hint`・`info`の4段階。CLIでは、標準出力に`[Error]`などの形式で出す。Python APIの中では、構造化して集める | `contextvars`で持ち、スレッドをまたぐ |
| テンプレート（`templates/`） | `template.typ`・`slide.typ`・`paper.typ`と、共通部（`_common.typ`）。フォントは`Noto Sans JP`だけを指定し、OSのフォント名は書かない | 受け取った`paper_size`・`landscape`を、表紙と本文の`set page`の両方に反映する（[#636](https://github.com/tokudiro/text-compositor/issues/636)） |

## 5.4 プラグインの登録

図表のプラグインの有効・無効は、`renderer_options.py`の表（`PLUGIN_FLAGS`）が、1か所で持つ（[#488](https://github.com/tokudiro/text-compositor/issues/488)）。configのキー・`TypstRenderer`の引数名・既定値を、1行で足せる。PDFのビルド（`project.py`）と、Python API・HTML出力（`api.py`）が、同じ表を読む。`config.py`の許可キーとの一致は、`tests/test_renderer_options.py`が確かめる。

一方、描画の本体（`_render_xxx`・フェンス言語の振り分け・`DIAGRAM_FILE_EXTS`・`--check-env`の項目・Viewerへの描画の委譲）は、図種ごとに、複数のファイルへ散っている。これを1か所に集める設計が、`doc/plugin-architecture.md`にある（[#474](https://github.com/tokudiro/text-compositor/issues/474)）。この設計書の状態表記は、「設計案（未実装）」のままで、実装済みの範囲は、未確認である（D1）。

<!-- pagebreak -->

## 5.5 レベル1の補足: Obunzuの内部

ObunzuのElectronの主プロセス（`viewer/src/main.js`）は、次の部品を持つ。変換の状態（監視・キュー・自動更新）は、ワーカーが持ち、Electronは持たない（ADR-5）。

| 部品 | 責務 |
| --- | --- |
| `main.js` | ウィンドウ・メニュー・ダイアログ・ワーカーの起動と終了。文書をタブ（`document-tab.js`）単位で持つ |
| `worker-client.js` | ワーカーとの、標準入出力のJSON行の通信。ワーカーが、終了を頼まれていないのに終わったら、起動し直す（5秒以内の2回目は、しない） |
| `chrome/`（`chrome.html`・`chrome.js`・`chrome.css`） | ツールバー・検索・設定・エラーの帯。`window.obunzuHost.*`越しに、殻を呼ぶ |
| `mermaid-host.js`・`vega-host.js`・`wavedrom-host.js`・`bytefield-host.js` | ワーカーから頼まれた図を、非表示のウィンドウで描き、SVGで返す |
| `python.js` | 同梱の組込版Pythonを探し、ワーカーを起動する。同梱の部品の場所を、環境変数（`TEXT_COMPOSITOR_*`）で教える |
| `settings.js`・`project.js`・`recent-files.js` | 設定（`%APPDATA%\Obunzu\settings.json`）・プロジェクトモード（`config.yaml`の章の一覧）・最近のファイル |

## 5.6 インターフェース: ワーカーのプロトコル

標準入出力に、1行に1つのJSONオブジェクトを書く（UTF-8）。起動すると、`{"event": "ready", "protocol": 1, "version": "0.4.7"}`を出す。

| メソッド・イベント | 向き | 内容 |
| --- | --- | --- |
| `open` | 呼び出し元 → ワーカー | 文書（`doc`）を開き、HTMLにして返す。以後、原稿と参照ファイルを監視する。同じ`doc`の変換は、最新の1件だけを残す（古い待ちには`superseded`を返す） |
| `close_doc` | 同上 | 文書を閉じ、記憶と監視を捨てる。実行中の変換は、取り消せない |
| `watch` | 同上 | 文書以外のファイル（プロジェクトモードの設定ファイル）を、名前つきで監視する。変更は`changed`で知らせ、再変換はしない |
| `set_auto_reload` | 同上 | 自動更新を、まとめて、オン・オフにする（既定はオフ） |
| `build`・`render_html`・`ping`・`shutdown` | 同上 | PDFを作る・HTMLを作る・生存確認・終了 |
| `rendered` | ワーカー → 呼び出し元 | 自動更新中に、再変換が終わるたびに出す。応答の形は、`open`と同じ。返信は要らない |
| `render_mermaid`など | ワーカー → 呼び出し元 | 図の描画を頼む。呼び出し元が、SVGで返す（任意。実装しなければ、ワーカーが、自前で描く） |

標準入力を読むスレッドは1つだけにし、標準出力への書き込みと、変換の呼び出しは、`threading.Lock`で直列にする（`doc/viewer-engine-architecture.md`4章）。
