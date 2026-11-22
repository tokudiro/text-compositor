# 7 配置の見方

text-compositorは、サーバーを持たない。利用者のPCと、CI（GitHub Actions）の、2種類の場所で動く。利用者のPCは、さらに、pip版を使うPCと、ObunzuのZIPを使うWindows PCに分かれる。

## 7.1 配置図

```plantuml
@startuml
!include <C4/C4_Deployment>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Deployment_Node(pc, "書き手のPC（pip版）", "Windows / Linux / macOS。Python 3.10以上") {
    Container(engine1, $engine_name, $engine_tech, "pip install text-compositor")
    Container(typst1, $typst_name, "typst（wheel）", "")
    Container(tools1, "図表ツール", "システムのJava・Chrome/Edge、取得したJRE・jar・D2", "")
    ContainerDb(cache1, $cache_name, "~/.cache/text-compositor ほか", "")
}
Deployment_Node(win, "Windows PC（ObunzuのZIP）", "Windows 10以降。Pythonは不要") {
    Deployment_Node(app, "Obunzuのフォルダ", "ZIPを展開したもの。約698 MB") {
        Container(viewer2, $viewer_name, $viewer_tech, "")
        Container(worker2, $worker_name, "python-embed（組込版Python 3.14.10）", "")
        Container(tools2, "同梱の図表ツール", "jre/・plantuml/・d2/・structurizr-cli/・mermaid/", "")
    }
    ContainerDb(cache2, $cache_name, "%LOCALAPPDATA%\\text-compositor", "")
}
Deployment_Node(ci, "GitHub Actions", "ubuntu-latest・windows-latest") {
    Container(wf, "ワークフロー", "test.yml・viewer.yml・release.yml・check-pins.yml", "テスト・ビルド・公開・週次の確認")
}

Rel(worker2, viewer2, "JSON行")
Rel(wf, pc, "PyPIへ公開する（pip版の入手元）")
Rel(wf, win, "ReleaseのZIPを置く")
@enduml
```

<!-- pagebreak -->

## 7.2 利用者のPC（pip版）

| 項目 | 内容 |
| --- | --- |
| 入れるもの | `pip install text-compositor`。Python 3.10以上。依存は、`typst`・`markdown-it-py`・`mdit-py-plugins`・`PyYAML`・`platformdirs`（`requirements.txt`で固定） |
| 初回に取得するもの | 日本語のフォント（Noto Sans JP 約9.2 MB、等幅のNoto Sans Mono CJK JP 約32 MB）。PlantUMLを使うとき: `plantuml.jar`（約17.6 MB）と、システムにJavaが無ければ、JRE（約49.7 MB）。D2を使うとき: D2のバイナリ（約13 MB）。Structurizrは、既定でオフ（約99 MB）。Mermaidは、システムのChrome・Edgeを使う（取得は、`plugins.mermaid_auto_download`が`true`のときだけ。約700 MB） |
| 置き場所 | OS標準のユーザーキャッシュ領域（`platformdirs`）。Linux `~/.cache/text-compositor`、macOS `~/Library/Caches/text-compositor`、Windows `%LOCALAPPDATA%\text-compositor\Cache`。Typstのパッケージは、`~/.cache/typst` |
| 確認 | `text-compositor --check-env`で、依存・Typstの版・キャッシュ・Mermaid/PlantUML/D2の前提を、ビルドせずに確認できる |

ツールの本体のディレクトリ（`tool_dir`）に、キャッシュを置かない。クローンして直接叩く場合も、pipインストールした場合も、同じ場所にキャッシュするためである（[#50](https://github.com/tokudiro/text-compositor/issues/50)・[#110](https://github.com/tokudiro/text-compositor/issues/110)）。

## 7.3 CI（GitHub Actions）

| ワークフロー | 起動 | 内容 |
| --- | --- | --- |
| `test.yml` | `text_compositor/`・`tests/`・`requirements*.txt`などの変更を含むPR・`master`へのpush | ubuntu-latestで、`pytest`。実ブラウザで描くテストも、標準搭載のChromeで動かす。フォントとTypstのパッケージを、`actions/cache`に保存する |
| `viewer.yml` | `viewer/`・`text_compositor/`・`pyproject.toml`の変更を含むPR・`master`へのpush | windows-latestで、`npm test`と、実際のPythonワーカーとの結合テスト。権限は、読み取りだけ |
| `viewer-release.yml` | `release.yml`からの呼び出し、`obunzu-markdown-viewer-v*`のタグ、手動 | テスト→ZIPのビルド。例外の道のタグのときだけ、Releaseの作成まで行う |
| `release.yml` | `v*`のタグ | ガイドのPDF・Release、PyPIへの公開、ObunzuのZIPの添付。`id-token`の権限は、`publish-pypi`だけが持つ |
| `check-pins.yml` | 週次（火曜） | コードに固定した版を、上流の最新版と比べる。差があるときだけ、issue「[週次チェック] 同梱した部品の更新確認」を作る |
| Dependabot | 週次（月曜） | Electron・npm・PyPI・GitHub Actionsの更新を、PRにする。PyPIは、`pyproject.toml`・`requirements*.txt`・`viewer/dist-requirements.txt`を、1つのPRにまとめる |

CIで確認しないもの: ElectronのGUIの起動と、展開した配布物の起動（`check-dist.js`）。画面が要り、不安定になりやすいため、手元で行う。Mermaid・PlantUML・D2・Structurizrの、配布物での実際の描画も、手元で確認する（R8）。

<!-- pagebreak -->

## 7.4 ObunzuのZIPの中身

ZIP（`Obunzu-Markdown-Viewer-<バージョン>-win-x64.zip`）は、約297.8 MB、展開後は約698.3 MBである。インストーラーは、作らない。レジストリにも書かない。削除は、フォルダごと消すだけである。

| [[同梱]]するもの | 展開後の大きさ | 用途・ライセンス |
| --- | --- | --- |
| Electron（Chromium） | 約367.5 MB | 画面。Mermaidなどの描画。ライセンスは、`LICENSES.chromium.html` |
| 組込版Python 3.14.10（`python-embed/`）と、依存パッケージ | 約23.5 MB＋約2.3 MB | ワーカー。`Pygments`（BSD-2-Clause）は、約8.6 MBで、シンタックスハイライトに使う |
| `typst`（Pythonのパッケージ） | 約59.6 MB | Typstのコンパイル（Apache-2.0） |
| Eclipse Temurin JRE 21（`jre/`） | 約144.5 MB | PlantUML・Structurizr（GPLv2＋Classpath Exception） |
| D2のCLI v0.9.0（`d2/`） | 約40.8 MB | D2 |
| フォント（`fonts/`） | 8.8 MB＋約32 MB | Noto Sans JPと、Noto Sans Mono CJK JP（OFL-1.1） |
| `plantuml-mit-1.2026.10.jar`（`plantuml/`） | 約17.4 MB | PlantUML（MIT版） |
| Structurizr CLI（絞り込み版。`structurizr-cli/`） | 約13.5 MB | DSLの解析とPlantUMLへの書き出しに要るjarだけに絞った（公式配布は約99 MB） |
| Typstのパッケージ（`typst-packages/`） | 約7 MB | 実際に使う版だけ（`diagraph` 0.3.8・`kip`・`cetz`・`fletcher`・`timeliney`・`finite`など） |
| `mermaid.min.js` 12.2.0、Vega・Vega-Lite・WaveDrom・Bytefield-svgのJS | 約5.5 MB＋約2.0 MB | Electronで描画する。Bytefield-svgは、EPL-2.0で、全文とソースの入手先を添える。改変しない |
| ライセンス表記（`licenses/`） | 0.1 MB未満 | `THIRD-PARTY-NOTICES.md`が一覧にする |

`playwright`（約106 MB）は、同梱しない。Mermaidは、Electronで描くためである（6.3）。`trove4j`（LGPL-2.1以降。Structurizr CLIが使う）は、改造せず、別のjarのまま入れる。

ワーカーへは、起動のときに、環境変数（`TEXT_COMPOSITOR_FONT_DIR`・`TEXT_COMPOSITOR_TYPST_PACKAGES`・`TEXT_COMPOSITOR_JAVA_BIN`・`TEXT_COMPOSITOR_PLANTUML_JAR`・`TEXT_COMPOSITOR_D2_BIN`・`TEXT_COMPOSITOR_STRUCTURIZR_CLI_LIB`・`TEXT_COMPOSITOR_MERMAID_JS`）で、同梱の場所を教える（`viewer/src/python.js`）。Obunzuは、Structurizrを、常に有効にする（pip版は、既定でオフ）。

## 7.5 利用者のデータの場所

| データ | 場所 | 更新で消えるか |
| --- | --- | --- |
| 設定・ウィンドウの状態 | `%APPDATA%\Obunzu\settings.json` | 消えない（アプリのフォルダの外） |
| 図のキャッシュ | `%LOCALAPPDATA%\text-compositor\` | 消えない |
| アプリ本体 | 展開したフォルダ | 新しいZIPで、フォルダごと置き換える |

更新は、新しいZIPを取得して、展開し直す。自動更新は、行わない（8.6）。
