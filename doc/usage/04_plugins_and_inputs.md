# plugins: 図表プラグインの有効・無効

```yaml
plugins:
  graphviz: true               # 既定 true
  pikchr: true                 # 既定 true
  cetz: true                   # 既定 true
  fletcher: true               # 既定 true
  mermaid: true                # 既定 true
  mermaid_auto_download: false # 既定 false
  plantuml: true                # 既定 true
  plantuml_auto_download: true  # 既定 true
  d2: true                      # 既定 true
  d2_auto_download: true        # 既定 true
  structurizr: false                    # 既定 false
  structurizr_auto_download: true       # 既定 true
```

`graphviz`/`pikchr`/`cetz`/`fletcher`/`mermaid`/`plantuml`/`d2`/`structurizr`を`false`にすると、該当する図表フェンス（`dot`/`graphviz`/`pikchr`/`cetz`/`fletcher`/`mermaid`/`plantuml`/`d2`/`structurizr`言語のコードブロック）は描画せず、素のコード表示にフォールバックします。`mermaid: true`の場合は`playwright`パッケージが、`plantuml: true`/`structurizr: true`の場合はローカルのJava（11以上）が、`d2: true`の場合はD2 CLI本体が必要です。

**`structurizr`だけ既定`false`です。** 内部で使う`structurizr-cli`一式（公式配布物）が約99MBあり、他のプラグイン（PlantUML約17.6MB・D2約13MB）と一桁違うため、使う場合は明示的に`true`にする必要があります。

`*_auto_download`は、これらの実行に必要なツール（ブラウザ／Java／D2／structurizr-cli）がシステムに見つからない場合の振る舞いを別軸で制御します。

| 設定 | trueの時 | falseの時 |
| --- | --- | --- |
| `mermaid_auto_download` | Playwright自身のChromiumをダウンロード（**約700MB**） | エラーで終了（システムのChrome/Edgeを自分でインストールする） |
| `plantuml_auto_download` | Eclipse Temurin JREをダウンロード（約50MB） | エラーで終了（Java 11以上を自分でインストールする） |
| `d2_auto_download` | D2公式CLIバイナリをダウンロード（約13MB） | エラーで終了（D2を自分でインストールする） |
| `structurizr_auto_download` | Java（未検出時、約50MB）とstructurizr-cli一式（約99MB）をダウンロード | エラーで終了（Java 11以上を自分でインストールする） |

既定値が非対称（mermaidはfalse、plantuml・d2はtrue）なのは、ダウンロードされる実体のサイズが一桁以上違うためです。Mermaidの描画に失敗して`mermaid_auto_download: true`にしたくなった場合は、約700MBのダウンロードが実行されることを理解した上で設定してください（詳細は「図表（Mermaid / Graphviz / PlantUML / D2 / Structurizr / Pikchr / CeTZ / Fletcher / SVG）」の章、README）。

# inputs: 原稿ファイルの基準ディレクトリ

```yaml
inputs:
  dir: "."
```

`chapters` に列挙するファイル名は、この `dir`（`config.yaml` からの相対パス）を基準に解決されます。

# variables: 本文へ値を差し込む

Markdown本文中の `{{KEY}}` を、ビルド時に `config.yaml` の値へ置換します。バージョン番号やビルド番号を、前処理スクリプトなしで差し込めます。

```yaml
variables:
  VERSION: "1.2.0"                              # 文字列で直接指定
  BUILD: {env: CI_BUILD_NUMBER, default: local} # 環境変数から取得。未設定なら default
  RELEASE: {env: RELEASE_NAME}                  # default が無く、未設定ならエラー
```

```markdown
本書はバージョン {{VERSION}}（ビルド {{BUILD}}）です。
```

- 対象は `.md`/`.markdown` の章です。見出し・表・コードフェンス・図の中、front-matterの値にも効きます。`config.yaml` 自身の値（`document.title` 等）と、Markdown以外の章（コード・CSV等）は対象外です。
- キーは英数字とアンダースコアで、先頭は数字にできません。値は1行です。
- `1.10` のような値は、YAMLで数値 `1.1` として読まれます。バージョン番号は引用符で囲んでください。
- `{{ message }}` のように空白を含む形は置換の対象外で、そのまま書けます。`{{KEY}}` の形の文字列をそのまま出したいときは、`\{{KEY}}` と書きます。
- 定義していないキーを使うと、綴りミスに気づけるよう、ファイル名と行番号を表示してエラー終了します。
- `variables:` を書かない場合、`{{...}}` には一切触れません。
- コマンドの実行結果を使いたいときは、環境変数に入れて `env` で渡します（例: `CI_BUILD_NUMBER=$(git rev-parse --short HEAD) text-compositor`）。
