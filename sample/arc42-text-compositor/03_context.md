# 3 コンテキストとスコープ

text-compositorの外側にいる人と、外部のシステムとの関係を示す。業務上の関係と、技術的な関係に分けて書く。

## 3.1 業務上のコンテキスト

```plantuml
@startuml
!include <C4/C4_Context>
!include c4-defs.iuml
LAYOUT_LEFT_RIGHT()

Person(author, $author_name, $author_desc)
Person(reader, $reader_name, $reader_desc)
Person(maint, $maint_name, $maint_desc)
System(tc, $tc_name, $tc_desc)
System_Ext(gh, $gh_name, $gh_desc)
System_Ext(pypi, $pypi_name, $pypi_desc)
System_Ext(jsd, $jsd_name, $jsd_desc)
System_Ext(tpkg, $tpkg_name, $tpkg_desc)
System_Ext(browser, $browser_name, $browser_desc)

Rel(author, tc, "原稿と設定を渡し、PDF・HTMLを得る")
Rel(tc, reader, "PDFを作る。ObunzuでHTMLを表示する")
Rel(maint, gh, "タグをpushし、Releaseを作る")
Rel(gh, pypi, "Trusted Publishingで公開する")
Rel(author, pypi, "pip installで入手する")
Rel(author, gh, "ObunzuのZIPを入手する")
Rel(tc, gh, "フォント・JRE・jar・D2を取得する")
Rel(tc, jsd, "MermaidなどのJSを取得する")
Rel(tc, tpkg, "Typstのパッケージを取得する")
Rel(tc, browser, "Mermaidを描画させる")
@enduml
```

<!-- pagebreak -->

| 相手 | やり取りする内容 | 備考 |
| --- | --- | --- |
| [[書き手]] | 原稿（Markdown・図表のソース・CSV）と、`config.yaml`を渡す。PDF・HTMLと、診断（警告・エラー）を受け取る（F1〜F5） | AIが書いた草稿を、人が直す使い方も含む（`README.md`）。エラーは、原稿の行つきで返す（8.3） |
| 読み手 | PDFを読む。ObunzuでHTMLを読む（F7） | Obunzuは、閲覧専用で、編集はしない（1.2） |
| 開発者 | 保守とリリース。週次の部品更新の確認（8.6） | 完了の判断の前に、確認を取る（OC4） |
| GitHub | Releaseの置き場（ZIP・ガイドのPDF）。CI（Actions）。フォント（Noto）・JRE（Temurin）・PlantUML・D2・Structurizr CLIの配布元 | 取得するURLと、SHA256は、`deps.py`に固定している（8.2） |
| PyPI | pip版の配布先。依存の`typst`などの配布元 | 公開は、タグのpushで自動。取り消せない（OC3） |
| jsDelivr | Mermaid・Vega・Vega-Lite・WaveDrom・Bytefield-svgのJSの配布元 | pip版とCIが取得する。Obunzuは、ZIPに同梱するため、取得しない（7.4） |
| Typstパッケージの配布元 | `diagraph`・`cetz`・`fletcher`などのパッケージ | 初回のコンパイルで、Typstが取得する。再試行は、できない（R6） |
| Chrome / Edge | pip版・CLIのMermaid描画 | PCにあるものを再利用する。無いときは、Fail-fast。`plugins.mermaid_auto_download: true`のときだけ、Chromium（約700 MB）を取得する（ADR-3） |

<!-- pagebreak -->

## 3.2 技術的なコンテキスト

| やり取り | 向き | チャネル | 形式・決まり |
| --- | --- | --- | --- |
| 原稿・設定の読み込み | ローカルのファイル → エンジン | ファイル | Markdown・YAML・JSON・CSV・図表ソース。パスは、設定ファイルの置き場所が基準（`doc/spec.md`5章） |
| PDF・HTMLの書き出し | エンジン → ローカルのファイル | ファイル | PDFは、一時ファイルへ書いてから置き換える（原子的。Python API）。Windowsでは、開いたままのPDFへは置き換えられない（0.1秒間隔で10回再試行してから、エラーにする） |
| 部品の取得 | エンジン → GitHub・jsDelivr | HTTPS | 取得中は`.part`へ書き、SHA256が一致したときだけ置き換える。一時的な失敗は、1秒・3秒の間隔で、合計3回まで再試行する（[#189](https://github.com/tokudiro/text-compositor/issues/189)）。404・書き込みの失敗・SHA256の不一致は、再試行しない |
| Typstパッケージの取得 | Typst → 配布元 | HTTPS | Typstコンパイラの内部で行う。キャッシュ（`~/.cache/typst`）に保存する |
| 図表ツールの呼び出し | エンジン → Java・D2・Structurizr CLI | 子プロセス | PlantUMLは、`java -jar plantuml.jar -tsvg -pipe -Playout=smetana`に、図のソースを標準入力で渡し、SVGを標準出力で受ける。文字コードは、UTF-8を明示する（[#306](https://github.com/tokudiro/text-compositor/issues/306)） |
| Mermaidの描画 | エンジン → ブラウザ | CDP（pip版）／JSON行（Obunzu） | pip版は、PlaywrightでChrome・EdgeにCDPで接続し、`mermaid.render()`を呼ぶ。Obunzuは、ワーカーが描画をElectronに依頼する（6.3） |
| Viewerとワーカーのやりとり | Obunzu ↔ ワーカー | 標準入出力 | 1行に1つのJSONオブジェクト（UTF-8）。プロトコルの版は1（`doc/spec.md`14章）。ローカルのポートは開かない |

- 原稿の内容を、外へ送る通信はない（OC2・TC5）。取得のための通信は、ツール・フォント・JS・パッケージの取得だけである。
- ネットワークが無くても、pip版は、取得済みのキャッシュがあれば、ビルドできる。ObunzuのZIPは、取得が要らない（Q2）。
