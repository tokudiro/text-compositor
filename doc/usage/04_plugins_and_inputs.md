# plugins: 図表プラグインの有効・無効

```yaml
plugins:
  graphviz: true               # 既定 true
  mermaid: true                # 既定 true
  mermaid_auto_download: false # 既定 false
  plantuml: true                # 既定 true
  plantuml_auto_download: true  # 既定 true
  d2: true                      # 既定 true
  d2_auto_download: true        # 既定 true
```

`graphviz`/`mermaid`/`plantuml`/`d2`を`false`にすると、該当する図表フェンス（`dot`/`graphviz`/`mermaid`/`plantuml`/`d2`言語のコードブロック）は描画せず、素のコード表示にフォールバックします。`mermaid: true`の場合は`playwright`パッケージが、`plantuml: true`の場合はローカルのJava（11以上）が、`d2: true`の場合はD2 CLI本体が必要です。

`*_auto_download`は、これらの実行に必要なツール（ブラウザ／Java／D2）がシステムに見つからない場合の振る舞いを別軸で制御します。

| 設定 | trueの時 | falseの時 |
| --- | --- | --- |
| `mermaid_auto_download` | Playwright自身のChromiumをダウンロード（**約700MB**） | エラーで終了（システムのChrome/Edgeを自分でインストールする） |
| `plantuml_auto_download` | Eclipse Temurin JREをダウンロード（約50MB） | エラーで終了（Java 11以上を自分でインストールする） |
| `d2_auto_download` | D2公式CLIバイナリをダウンロード（約13MB） | エラーで終了（D2を自分でインストールする） |

既定値が非対称（mermaidはfalse、plantuml・d2はtrue）なのは、ダウンロードされる実体のサイズが一桁以上違うためです。Mermaidの描画に失敗して`mermaid_auto_download: true`にしたくなった場合は、約700MBのダウンロードが実行されることを理解した上で設定してください（詳細は「図表（Mermaid / Graphviz / PlantUML / D2）」の章、README）。

# inputs: 原稿ファイルの基準ディレクトリ

```yaml
inputs:
  dir: "."
```

`chapters` に列挙するファイル名は、この `dir`（`config.yaml` からの相対パス）を基準に解決されます。
