# text-compositor: 複数のテキストから文書を組み上げるツール 仕様書

## 1. 目的
テキストファイルを、1つ1つ独立した断片として扱うツールである。複数の断片を、人間の手作業によるレイアウト調整なしに、1つの人間可読なPDF文書へ決定論的に組み上げる（compose）。AIが生成し人間が加筆・修正した原稿はもちろん、既存の手作成ドキュメントを持ち込んで整理・統合する用途にも使える。これにより「Docs as Code」の概念と「書き手からのデザイン権限の剥奪」を実証する。

このツールの核となる考え方は、Text（Model）とPDF（View）の分離である。原稿ファイル（Markdown等）は文書の内容そのもの、すなわちModelである。テンプレート（Typst）とレイアウト規則は見た目、すなわちViewである。原稿の書き手は、見た目のためのレイアウト調整を一切行わない。

Viewの既定値はテンプレートが持つ。個々の文書で既定値と異なる見た目にしたいときだけ、`config.yaml`側で明示的に上書きする。この「テンプレートの既定値を基本とし、`config.yaml`で上書きできる」という優先順位は、`cover`/`toc`/`header`/`footer`等、`document:`配下の各設定に共通する設計方針である。設定の優先順位全体は6章を参照。

入力となるテキストファイルはMarkdownに限らない。プレーンテキスト、コードコメント、YAML、JSON、CSVなど、あらゆるテキストファイルが対象になり得る。`chapters`のファイルは拡張子で扱いが分かれる： `.md`/`.markdown`はMarkdownとして変換し（7章）、`.yaml`/`.yml`/`.json`はシンタックスハイライト付きの等幅表示、`.dot`/`.gv`/`.mmd`/`.puml`/`.plantuml`/`.pu`は図表ソースファイルとして1章分描画し（11章、[#53](https://github.com/tokudiro/text-compositor/issues/53)）、`.csv`はTypstのテーブルとして構造化して描画し（後述、[#36](https://github.com/tokudiro/text-compositor/issues/36)）、それ以外（プレーンテキスト・コードファイル等）は素の等幅表示にする。いずれもMarkdown以外の拡張子ではmarkdown-itを一切通さないため、行頭の`#`や`-`等がMarkdown構文として誤解釈されることはない（[#15](https://github.com/tokudiro/text-compositor/issues/15)）。HTMLを入力フォーマットとして本格対応することは検討のうえ見送った（8章）。

もう1つの要件は「書いている場所で、そのままPDFにできること」。ドキュメントの置き場所をツールの都合に合わせさせない。

## 2. 実行環境の要件
実行環境に関する要件は本章に一本化する。他章で個別の依存関係（Typst、Mermaid等）に触れる際も、方針はここを参照する。

* **Python中心・最小限のダウンロード**: コアはPython（`build.py`）のみで完結する。追加が必要なものも、その場でのダウンロードで完結させ、常駐サーバーやコンテナは要求しない。
  * Typstコンパイラ: バイナリを同梱せず、PyPIのホイール経由で取得する（3章）。
  * オプトインの図表プラグイン: Mermaidは`pip install playwright`とシステムにインストール済みのChrome/Edge（新規ダウンロードはしない）、PlantUMLはJREを、D2はD2公式CLIバイナリをその場取得する（11章、[#35](https://github.com/tokudiro/text-compositor/issues/35)、[#90](https://github.com/tokudiro/text-compositor/issues/90)）。
  * 日本語CJKフォント: リポジトリに同梱せず取得（ダウンロード）する方式とする。Noto Sans JP（Regular/Bold）を初回ビルド時にOS標準のユーザーキャッシュ領域（`platformdirs`経由。Windows: `%LOCALAPPDATA%\text-compositor\Cache`、Linux: `~/.cache/text-compositor`、macOS: `~/Library/Caches/text-compositor`）へダウンロード・キャッシュし、以降はキャッシュを使う（9章）。`tool_dir`（ツール本体のインストール場所）を使わないのは、「クローンして直接叩く」「pipインストール」いずれの実行方式でも同じ場所にキャッシュを置くため（[#50](https://github.com/tokudiro/text-compositor/issues/50)、[#110](https://github.com/tokudiro/text-compositor/issues/110)）。
* **外部サーバー・SaaS非依存**: どこかの外部サーバーやSaaSに依存しない。図表描画を含め、外部APIへの通信によるコンテンツ生成は一切行わず、常に完全ローカルで完結させる。これは絶対要件であり、11章のプラグインにも適用される。
* **GitHub Actions上での完結**: 上記2点の帰結として、GitHub Actions（`ubuntu-latest` などのGitHub-hosted runner）上だけで、セルフホストサーバーなしに完結してビルドできる。
* **ローカル環境（Windows/Linux/macOS）**: 同じ理由で、Python（および必要に応じてJRE等の軽量ランタイム）さえ用意すれば、Windows/Linux/macOSいずれでも同一の手順でビルドできる。

## 3. ツールとドキュメントの分離
ツール本体とドキュメントは役割を分離する。原稿は通常、章ごとに分割された複数のテキストファイル（それぞれが1つの独立した断片。1章）として、ツール外の任意の場所に存在する。原稿をツール側へコピーする運用は行わない。

* **ツール本体（このリポジトリ）**: 変換エンジン（`build.py`）とテンプレート。書き換えずに使えるものだけを置く（フォントは同梱せず取得する方式。2章・9章）。
* **ドキュメント（任意の場所）**: テキストファイル群（現状はMarkdownのみ。1章）、画像、設定ファイル。ツールのディレクトリ構成に従う必要はない。
  * 設定ファイルの推奨名は `text-compositor.config.yaml`。
  * `--config` で明示するか、省略時はカレントディレクトリ（ドキュメント側）直下のこのファイルを自動的に探す。ツール本体のディレクトリ（`tool_dir`）は探索しない。

クローンして直接叩く場合のディレクトリ構成は以下のとおり（pipインストールした場合は、これらのファイルの代わりに`text-compositor`コマンドが使える。4章）。

```text
<ツール本体>                                <ドキュメント（任意の場所・複数可）>
text-compositor/                         my-project/
 ├── build.py            # 後方互換ラッパー  ├── 01_intro.md
 ├── text_compositor/                     ├── 02_features.md
 │   ├── build.py        # 実装本体          ├── 03_architecture.md          # 複数ファイルを1冊に結合
 │   └── templates/      # 既定テンプレート  ├── text-compositor.config.yaml # --config で指定（既定推奨名）
 └── doc/spec.md                             ├── images/
                                              └── manual.pdf                  # 既定の出力先
```

* **Typstコンパイラの入手方法**: バイナリを同梱しない（2章）。PyPIの `typst` パッケージ（[typst-py](https://github.com/messense/typst-py/)、`requirements.txt` で版固定）がOSごとのホイールにコンパイラ本体を含むため、`pip install -r requirements.txt` だけで済む。`build.py` は `typst.compile(input, output=, root=)` というPython APIを直接呼び出すだけで、バイナリの配置やOS判定コードを持たない。

## 4. 使い方（CLI 仕様）
実行方法は2通りある（[#111](https://github.com/tokudiro/text-compositor/issues/111)、2章・3章参照）。どちらも同じ`build.py`のロジック（実体は`text_compositor/build.py`）を呼び出す。

* **pipインストール方式**: `pipx install text-compositor`（推奨）または`pip install text-compositor`でインストールし、`text-compositor`コマンドを使う。
* **クローンして直接叩く方式**: リポジトリをクローンし、トップレベルの`build.py`（`text_compositor/build.py`への薄いラッパー）を直接実行する。

```bash
text-compositor --config <path/to/text-compositor.config.yaml>
# または（クローンして直接叩く場合）
python build.py --config <path/to/text-compositor.config.yaml>
```

* **`--config <path>`**: 設定ファイル（yaml/json）へのパス。省略した場合はカレントディレクトリ直下の `text-compositor.config.yaml`/`text-compositor.config.json` を探す（5章）。どちらも指定・発見できなければエラー終了する。
* **`--config-list <path>`**: ビルド対象のconfigファイルパスを1行1件で列挙したテキストファイルを渡し、1回の実行で複数PDFをビルドする（[#73](https://github.com/tokudiro/text-compositor/issues/73)）。`--config`とは同時指定できない。
* **`--check-env`**: 実行環境の前提（隔離環境（venv/pipx）の使用有無、依存パッケージ、Typstバージョン、キャッシュ済みアセット、Mermaid/PlantUML/D2の前提条件）を、ビルドを実行せずに確認する（[#37](https://github.com/tokudiro/text-compositor/issues/37)、[#113](https://github.com/tokudiro/text-compositor/issues/113)）。
* **`-q`/`--quiet`・`-v`/`--verbose`**（[#52](https://github.com/tokudiro/text-compositor/issues/52)）: 実行時のログの詳細度を制御する。既定は`[Info]`まで表示、`[Warning]`/`[Error]`/`[Success]`は常に表示する。`-q`は`[Info]`を抑制し、`-v`は処理中の章・キャッシュ再利用状況などの`[Verbose]`ログも追加表示する。同時指定は不可。
* **`--keep-temp`**（[#52](https://github.com/tokudiro/text-compositor/issues/52)）: ビルド成功時も中間ファイル（`temp_build.typ`等、12章）を削除せずに残す。既定では失敗時のみ残る。
* **`--watch`**（[#30](https://github.com/tokudiro/text-compositor/issues/30)）: 初回ビルド後も終了せず、保存を検知して自動で再ビルドする。`--check-env`とは同時指定できない。`--config-list`と併用した場合は、config単位で監視し、変更があったconfigだけを再ビルドする。
  * **監視対象**: config自身、`project_dir`配下、`inputs.dir`配下、`.typ`パス指定のテンプレート。ツール同梱テンプレート（名前指定）は対象外。`.`で始まるディレクトリ・ファイル（`.git`・`.text-compositor`・エディタのスワップファイル等）、末尾`~`のファイル、出力先（`output.dir`配下）は無視する。`project_dir`の外にある画像などを`--root`経由で参照している場合、その変更は検知しない。
  * **検知方式**: 標準ライブラリのみで、0.5秒間隔にファイルの更新日時・サイズを走査する（2章の依存最小化方針に沿い、`watchdog`等は導入しない）。変更を検知したら、変化が止まる（0.3秒間隔の再走査で一致する）のを待ってからビルドする。エディタの「一時ファイルへ書いてリネーム」等の複数回の更新で、途中状態をビルドしないため。
  * **失敗時の挙動**: 初回を含め、ビルドが失敗しても終了せずエラーを表示して次の保存を待つ（編集→保存→確認の繰り返しが用途のため）。修正して保存すれば再ビルドされる。`Ctrl+C`で終了する。
  * **再ビルドのたびに監視対象を解決し直す**: configの編集で`inputs.dir`やテンプレートが変わっても追従するため。configが壊れている間は、configと`project_dir`のみを監視する。
* **`--if-changed`**（[#151](https://github.com/tokudiro/text-compositor/issues/151)）: makeのように、出力PDFが依存物より新しければビルドをスキップする（`[Info] Skipped (up to date): <PDF>`を出力して正常終了）。`--config-list`と併用した場合は、config単位で判定する。`--clean`・`--watch`とは同時指定できない。以下の決定事項に沿う。
  * **既定はオプトイン**: `--if-changed`を付けない限り、従来どおり毎回全章を再生成する。既定を変えると「入力は変えたのにPDFが古いまま」という事故を既存の利用者に起こし得るため。
  * **判定方法は更新日時のみ**（make方式。内容ハッシュは採用しない）: 出力PDFの更新日時が、依存物の最新の更新日時より**厳密に新しい**ときだけスキップする。出力PDFが無ければ再生成する。ハッシュ方式は、判定のたびに全入力を読む必要がある。しかも図表SVGのキャッシュキー（[#26](https://github.com/tokudiro/text-compositor/issues/26)）と違い、出力PDFに対応するハッシュの保存先という状態を新たに持つことになり、得られる利点に見合わないと判断した。
  * **依存物**: `--watch`と同じ解決処理（`_watch_targets`/`_watch_snapshot`）を共有する。config自身、`project_dir`配下（`inputs.dir`が外にあればそれも）、`.typ`パス指定のテンプレートに加え、ツール自身（`build.py`）と同梱テンプレートを含める。text-compositor本体の更新（`pip upgrade`等）で、入力が同じでも出力が変わり得るため。`.`で始まるディレクトリ・ファイル（`.text-compositor`等）と、出力先（`output.dir`配下）は含めない。`.pdf`ファイルは（`.typ`テンプレート等として個別に指定されたものを除き）依存物から除外する。`project_dir`を共有する別configの出力PDFを入力とみなすと、`--config-list`で互いに常に再生成となるため。
  * **判定に含まれないもの**: (1)Typstのバージョン（更新日時では検出できない。Typstを更新した後に再生成したいときは`--if-changed`を外して実行する）。(2)`project_dir`の外にある画像等（`--watch`と同じ制約）。(3)`variables`の`env`参照先の環境変数の値（環境変数を変えても、ファイルが変わらなければスキップされる）。
  * **CIでの扱い**: `actions/checkout`は全ファイルの更新日時を取得時刻にするため、`--if-changed`を付けるだけではCIでは常に再生成になる（PDFが無いか、入力より古いため）。CIで効果を出すには、出力先を`actions/cache`等で復元する必要がある。ただし復元されたPDFも復元時刻の更新日時になるので、`checkout`より後に復元した場合に限りスキップされる。実運用での有効性は未検証。CIでは、更新日時の代わりに`actions/cache`のキー（入力ファイルのハッシュ）でキャッシュの命中を判断する運用のほうが確実な可能性がある（推測）。
* **`--clean`・`--clean-cache`**（[#151](https://github.com/tokudiro/text-compositor/issues/151)）: ビルドせず、生成物を削除して終了する（`make clean`相当）。Typstやフォントの取得は行わないため、環境不備があっても実行できる。`--config-list`と併用した場合は、全configを対象にする。`--check-env`・`--watch`・`--if-changed`とは同時指定できない。
  * **`--clean`の削除対象**: 出力PDF（`output.dir`/`output.filename`）と、`.text-compositor/`直下の中間ファイル（`temp_build.typ`・`_template.typ`・`_common.typ`。ビルド失敗時やデバッグ用の`--keep-temp`で残ったもの）。`.text-compositor/`が空になれば、そのディレクトリも削除する。入力ファイル・configは削除しない。
  * **`--clean-cache`**: 上記に加えて、図表SVGのキャッシュ（`.text-compositor/cache/`）も削除する。再生成コストが高い（Mermaid・PlantUML・D2の描画）ため、`--clean`とは別オプションにした。単独で指定しても`--clean`を含む。キャッシュキーの仕様変更（#26）で残った古いキーのファイルの掃除にも使える。
  * ユーザーキャッシュ（フォント・`mermaid.min.js`・PlantUML・JRE・D2。2章）は対象外。ツール全体で共有される資産で、プロジェクト単位の生成物ではないため。
* 上記以外のオプション（出力先の上書き、テンプレート指定、用紙設定等の文書内容に関わる上書き）は存在しない。`config.yamlが単一の正`という方針との相性を優先し、実行時の振る舞いに関するオプションのみをCLI引数として持つ（#52での検討）。
* **終了コード**: 成功 `0` / 失敗 `1`。入力欠損・画像欠損・コンパイルエラーは即時失敗する（Fail-fast、10章）。`--check-env`はNGが1件でもあれば`1`。引数の指定誤り（`-q`と`-v`の同時指定等）は`argparse`標準の`2`。

複数ファイル/ディレクトリの直接指定、追加オプション等のさらなる拡張は構想段階であり、実装するかどうかも含めて未定（[#25](https://github.com/tokudiro/text-compositor/issues/25)）。

## 5. パス解決規則
パスの基準点は次のとおり一意に定める。

| 対象 | 基準ディレクトリ |
| --- | --- |
| `config.yaml` 内のすべての相対パス（`chapters`, `inputs.dir`, `output.*`, `aggregate`） | その `config.yaml` が置かれたディレクトリ（`project_dir`） |
| Markdown 内の画像・リンク先ファイル | その Markdown ファイルのディレクトリ |
| `template.path` | 値が`.typ`で終わらない「名前」（例: `template`, `slide`）はツール同梱`tool_dir/templates/<名前>.typ`基準。`.typ`で終わる「パス」（例: `my_template.typ`, `custom/my_template.typ`）は他の相対パスと同じ`project_dir`基準（プロジェクト独自テンプレート、[#23](https://github.com/tokudiro/text-compositor/issues/23)）。 |

* **ドキュメントルート（`--root`）**: `project_dir`・実際の `inputs_dir`/`outputs_dir`・`work_dir`（`project_dir/.text-compositor`）の共通の親ディレクトリを動的に計算する。`tool_dir`（ツール本体のディレクトリ）は含めない。テンプレートは`tool_dir`配下・`project_dir`配下いずれの場合も、`build.py`がビルドのたびに`work_dir`へコピーしてからそのコピーを参照するため、`--root`を元のテンプレートの置き場所まで広げる必要がない（8章のサンドボックス要件）。この結果、Markdown内の画像等が`project_dir`の外を参照している場合はビルドエラーになる（テンプレート自体はPythonのファイルコピーで読むため、`project_dir`の外に置いても構わない）。
* **設定ファイルの指定**: `--config` で明示するか、省略時はカレントディレクトリ直下の `text-compositor.config.yaml`/`text-compositor.config.json` を探す（`tool_dir` は探索しない）。どちらもなければエラーで終了する。
* **出力先**: `config.yaml` の `output.dir`/`output.filename` に従い `project_dir` 基準で決まる。入力パスからの出力先自動判定やCLIオプションでの上書きは未実装で、構想段階（[#25](https://github.com/tokudiro/text-compositor/issues/25)）。

## 6. 設定ファイル (Configuration as Code)
* `config.yaml` / `config.json` のどちらでも書ける。内部では単一のスキーマ（正規化された辞書構造やPydantic等）に統合して扱い、パース処理の破綻を防ぐ。パスの基準は5章に従う。
* ファイル順序、ページ設定、出力メタデータ、データ集約ディレクトリ（aggregate）を一元管理する。
  * `plugins:`（Graphviz/PlantUML/Mermaid/D2の有効・無効切り替え）。`graphviz`/`mermaid`/`plantuml`/`d2`はいずれも既定`true`（未指定時は常時有効）。`false`にすると該当フェンス（```` ```dot ````/```` ```graphviz ````/```` ```mermaid ````/```` ```plantuml ````/```` ```d2 ````）は描画せず、未対応言語と同じ素のコード表示にフォールバックする（[#21](https://github.com/tokudiro/text-compositor/issues/21)、[#22](https://github.com/tokudiro/text-compositor/issues/22)、[#90](https://github.com/tokudiro/text-compositor/issues/90)）。
  * `plugins.mermaid_auto_download`（既定`false`）/`plugins.plantuml_auto_download`（既定`true`）: 描画に必要なツール（ブラウザ/Java）がシステムに見つからない場合の振る舞いを別軸で制御する。`true`なら自動取得、`false`ならFail-fast。既定値が非対称なのは、Playwright自身のChromium（約700MB）とEclipse Temurin JRE（約49.7MB）でダウンロード量が一桁違うため（11章、#22の設計議論）。
* **`variables:`（テキストの置換機構、[#72](https://github.com/tokudiro/text-compositor/issues/72)）**: Markdown本文中の`{{KEY}}`をビルド時に実値へ置換する。バージョン番号やビルド番号を、前処理スクリプトなしで差し込むための機構。
  * **定義**: `variables:`にキーと値を書く。値はスカラー（文字列・数値・真偽値。文字列化して使う）か、`{env: 環境変数名, default: 既定値}`（ビルド時の環境変数から取得。未設定で`default`も無ければエラー）。キーは英数字とアンダースコア（先頭は数字不可）。値は1行に限る（複数行を許すと、#27の行番号による診断が元のMarkdownの行とずれるため）。YAMLでは`1.10`が数値`1.1`になるため、バージョン番号は文字列として引用符で囲む。
  * **コマンド実行による取得は設けない**: configの記述だけで任意コマンドが動くのは安全性の面で望ましくない（8章）。コマンドの出力は環境変数に入れて渡す。
  * **適用範囲**: `.md`/`.markdown`の章のみ。パース前の文字列として置換するため、見出し・表・コードフェンス・図の中、front-matterの値にも一律に効く。`config.yaml`自身の値（`document.title`等）、Markdown以外の章（コード・CSV等）には適用しない。
  * **構文**: `{{KEY}}`（KEYは上記の形）。`{{ message }}`のように空白を含む形（Vue/Jinja等の記法）は対象外で、そのまま書ける。先頭に`\`を付けた`\{{KEY}}`は、置換せず`{{KEY}}`をそのまま出力するエスケープ。置換は1回だけで、値の中の`{{...}}`は展開しない。
  * **未定義のキー**: 9章のFail-fast方針に従い、綴りミスのまま出力されないよう、ファイル名と行番号を報告して即エラー終了する。同じファイル内の未定義キーはまとめて報告する。
  * **既定**: `variables:`キー自体が無ければ機構を無効にし、`{{...}}`に一切触れない。既存のプロジェクトの出力は変わらない。
* **設定の優先順位**: `config.yaml` の章別設定 ＞ グローバル設定 ＞ 内蔵デフォルト。CLIオプションによる文書内容の上書き（出力先・用紙設定等）は、4章で述べたとおり方針上見送っており存在しない（[#52](https://github.com/tokudiro/text-compositor/issues/52)）。`-q`/`-v`/`--keep-temp`等、既存のCLIオプションはいずれも実行時の振る舞いのみを制御し、この優先順位には関与しない。
* **設定ファイル自体は必須**: `--config`、またはカレントディレクトリからの自動検出（5章）で、いずれかの設定ファイルが必要。中身は最小限でよい。ただし、`chapters` は現状ここで指定する以外の方法がない（入力パスからの自動導出は未実装。[#25](https://github.com/tokudiro/text-compositor/issues/25)）。
* YAML パーサ（PyYAML）が未導入のまま `config.yaml` を無視して既定値でビルドを続行してはならない。サイレントに誤った成果物が出るため即エラーとする。
* **Typst Universeのテンプレート**（[#63](https://github.com/tokudiro/text-compositor/issues/63)）: `template.path`に、Universeのテンプレートを包む**アダプタ**（`.typ`）を指定して使う。専用のconfigキー（`template.package`等）は設けない。Universeのテンプレートは、それぞれ独自の引数を持つ（例: `ilm.with(title:, authors:, ...)`）。汎用の対応表をconfigに持たせると、テンプレートごとのアダプタより保守が重くなるためである。
  * **アダプタの責務**: (1)`build.py`が生成するコードが呼ぶ補助関数（`fit-image`・`render-graph`・`render-header`・`render-footer`・`render-background`・`callout`）をエクスポートする。(2)`conf()`の引数を、Universe側の引数へ翻訳する。(1)の実装は、下記の`_common.typ`から取り込む。
  * **`_common.typ`**: 上記の補助関数を`templates/_common.typ`に置く。`build.py`はビルドのたびに、テンプレートのコピー（`.text-compositor/_template.typ`）の隣へ`.text-compositor/_common.typ`をコピーする。アダプタは`#import "_common.typ": ...`と相対パスで読み込める。同梱の`template.typ`・`slide.typ`も同じファイルを読み込む（4つの関数が両者で同一実装だったため、重複も解消した）。`render-header`/`render-footer`はテンプレートごとに見た目が違うため、`slide.typ`は自前の実装を持つ。`_common.typ`のものは`template.typ`と同じ既定の実装である。独自テンプレートが`_common.typ`を読み込まなくても、影響はない。
  * **バージョンは`@preview/name:x.y.z`で固定する**: アダプタ内に、バージョンを含めて書く（`import "@preview/ilm:2.1.1": ilm`）。configには持たない。バージョン固定はアダプタの利用者が行い、更新はアダプタの書き換えで行う。Typstの`compiler`要件（パッケージ側の最低バージョン）が、固定した`typst`（`requirements.txt`）を超えると、コンパイルエラーになる。
  * **ライセンス**: `@preview`参照は、コードをこのリポジトリへ同梱しない（ビルド時にTypstが取得する）。Universeのテンプレートの複製は同梱しない。サンプル（`sample/universe-ilm/`）が同梱するのはアダプタだけで、`ilm`（MIT-0）のコードは含まない。
  * **表紙・目次・章送り**: 複数のMarkdownを章として結合する動作は、Universe側の単一文書向けの設計と衝突しなかった（`ilm`で確認。章のH1は`ilm`の章見出しになる）。ただし`document.cover`の既定は`none`のため、Universeの表紙を使うには`cover: template`を明示する必要がある。`none`のままだと、`conf(cover: false)`が渡されて表紙が出ず、先頭章のH1も落ちる。
  * **アダプタで吸収できないもの**: 章単位の`header`/`footer`/`logo`/`background`の上書きは、`build.py`がページ設定を出し直す形で実現している。Universe側のページ設定と衝突し得るため、対応しないテンプレートでは、アダプタで無視するのを基本とする（`ilm`では無視して、`ilm`自身のフッタが保たれた）。`ilm`以外のテンプレートでの挙動は未検証。`landscape`・`subtitle`・`revision_history`も、対応するかどうかはテンプレート次第である。`date`は、`conf()`が`"YYYY-MM-DD"`形式の文字列で渡す一方、`datetime`を要求するテンプレートがある。アダプタで変換する（`sample/universe-ilm/ilm-adapter.typ`の`to-datetime`）。
  * **ネットワーク**: パッケージは初回のビルド時にTypstが取得し、ローカルにキャッシュする（`templates/template.typ`が使う`@preview/diagraph`と同じ扱い）。オフライン環境では、事前にキャッシュしておく必要がある。
  * **検証**: `sample/universe-ilm/`（`ilm@2.1.1`、Typst 0.15.0）で、表紙・目次・章・表・Graphviz図・callout・ページ番号のビルドを確認した。
* **論文形式テンプレート（`paper`）**（[#64](https://github.com/tokudiro/text-compositor/issues/64)）: 2段組みの論文・査読レポート・特許明細書向けに、`templates/paper.typ`を同梱する。
  * **新テンプレートとした理由**: 段組みの数は、Viewの構造そのものを変える。`template.typ`に`document.columns`のような設定を足す形にすると、表紙・目次・章ごとの改ページなど、単一段組みを前提とした処理と両立させる必要が出る。媒体が違うときに新テンプレートを作るという基準（[独自テンプレートを使う](usage/10_custom_template.md)）に従い、`slide.typ`と同じく別テンプレートにした。
  * **実現方法**: Typstの標準機能（`set page(columns: 2)`と、`place(float: true, scope: "parent")`による全幅のタイトルブロック）だけで実現する。外部パッケージは使わない。補助関数は`_common.typ`から読み込む（#63）。
  * **`cover`の意味**: このテンプレートでは、`cover`は表紙ページではなく、1ページ目上部のタイトルブロック（タイトル・副題・著者・日付・概要）の有無を指す。論文には独立した表紙ページを設けないため。`document.cover`の既定が`none`である点は他のテンプレートと同じで、タイトルブロックを出すには`cover: template`を明示する必要がある。副題は、`subtitle`が空でなければ出す。未指定時は設定の既定値（`自動生成ドキュメント`）が入るため、消すには`subtitle: ""`と書く。
  * **`document.abstract`**（文字列、既定は未指定）: タイトルブロックの下に「概要」として全幅で出す。`conf()`の任意引数`abstract`として、指定されたときだけ渡す（`toc`・`revision_history`と同じ方針で、この引数を持たない既存の独自テンプレートとの互換を保つ）。値は生成するTypstコードにデータとして埋め込み、改行は`\n`で渡す（`revision_history`と共通の`_typst_multiline_literal`）。文字列以外はエラー終了する。`template.typ`・`slide.typ`は、引数を受け取るだけで何も出力しない（no-op）。
  * **章をまたいで連続して流す**: 論文は章ごとに改ページしない。`build.py`は、章の末尾ごとに弱い改ページ（`#pagebreak(weak: true)`）を出す。`paper.typ`は`show pagebreak: none`で、これを無効にする。`<!-- pagebreak -->`（#92）も同じコードを生成するため、区別できず、明示の改ページも効かなくなる。この代償を、章単位で改ページしないことの引き換えとして受け入れた。区別が要るようになれば、`build.py`側で章末の改ページを別の記法にする変更が要る。
  * **範囲外**: (1)参考文献・引用（Typstの`bibliography()`との連携。Markdown側の引用記法が未定義のため）。(2)段幅より広い表・コードを、段をまたいで全幅に置く機能（折り返されるか、はみ出す）。(3)章や図表の全幅配置。`toc`・`cover_page_number`・`revision_history`は、論文に無い要素のため受け取って何も出力しない。
  * **サンプル**: `sample/paper/`。

## 7. Markdown 方言と Marp 互換
本章は、ディレクティブ・front-matter・改ページ規則等の専用の変換規則を持つ唯一のフォーマットであるMarkdownの扱いを規定する（1章）。他フォーマット（YAML/JSON/プレーンテキスト等）は専用の変換規則を持たず、拡張子に応じて等幅表示にフォールバックするのみ（1章、[#15](https://github.com/tokudiro/text-compositor/issues/15)）。フォーマットごとに専用の変換規則を追加していく場合も、本章のMarkdown固有の扱いは維持する設計とする。

**対応するMarkdown記法のスコープ**（[#48](https://github.com/tokudiro/text-compositor/issues/48)）: CommonMark（`markdown-it-py`の`commonmark`プリセット）を土台に、GFM (GitHub Flavored Markdown) の一部とGitHub Wikiの記法を対応範囲とする。**（実装済み）**
* GFM拡張: テーブル・取り消し線（`~~text~~`、`.enable("strikethrough")`）・タスクリスト（`- [ ]`/`- [x]`、`mdit-py-plugins`の`tasklists_plugin`）に対応。山括弧付き自動リンク（`<https://example.com>`）はCommonMark標準機能で、`link_open`/`link_close`という通常のリンクと同じトークンとして出力されるため追加実装なしで動く。山括弧なしの裸URL自動リンク化（GFMの拡張自動リンク）は`linkify-it-py`という追加依存が要るため非対応とする（対応する場合は別途検討）。
* タスクリストのチェックボックスは、`tasklists_plugin`が生HTML（`<input class="task-list-item-checkbox" ...>`）として出力するため、他のHTMLタグと同じ「未対応HTML」警告で消えてしまう問題があった。このパターンだけを`render_inline`内で特別に認識し、Unicodeのチェックボックス記号（☐/☑）に変換する。それ以外のHTMLは従来どおり警告のみ（HTMLは「対応した」のではなく、狭い許可リストへの1パターン追加として扱う方針。[#46](https://github.com/tokudiro/text-compositor/issues/46)で議論・記録）。
* GitHub Wiki拡張: `[[用語]]`によるMarkdown内リンク記法。用語索引機能（[#47](https://github.com/tokudiro/text-compositor/issues/47)、**実装済み**。10章を参照）で利用する。
* このスコープに含まれないもの: Obsidian固有の拡張（コールアウト・埋め込み・`==ハイライト==`等）。文字色指定（[#46](https://github.com/tokudiro/text-compositor/issues/46)、**実装済み**、10章）はGFM/GitHub Wikiどちらにも属さない例外として個別に採用した。それ以外のPandoc記法・生HTML全般は非対応のまま。

原稿は Marp 形式（`<!-- header: ... -->` ディレクティブ、`---` によるスライド区切り）で書かれている実績があるため、同一の Markdown が Marp でもこのツールでも通ることを要件とする。

**方針の限界（意図的なスコープ）**: 「Marpでも通る」とは、Marp原稿を`chapters`にそのまま流し込んでもビルドが失敗したり不要な警告が出たりしない、という意味に限る。**インラインHTMLコメント形式のディレクティブ**（`<!-- header: X -->`等）や、`title`/`subtitle`/`author`/`date`といった一部front-matterキーの**値を実際に反映する**ことは要件にしていない（[#41](https://github.com/tokudiro/text-compositor/issues/41)）。Marpの`theme:`/`class:`/`backgroundColor:`やカスタムCSS等の見た目に関わる指定も`MARP_ONLY_KEYS`として同様に無視する。一方、front-matterの`header`/`footer`/`paginate`キー、および`config.yaml`の`chapters[].header`/`footer`/`paginate`は、ディレクティブとは別の仕組みとして値を反映する（[#42](https://github.com/tokudiro/text-compositor/issues/42)、10章）。

反映機能は`header`/`footer`/`paginate`ディレクティブ（[#16](https://github.com/tokudiro/text-compositor/issues/16)）とfront-matterの`title`/`subtitle`/`author`/`date`（[#38](https://github.com/tokudiro/text-compositor/issues/38)）について一度実装した。しかし、撤回した（[#41](https://github.com/tokudiro/text-compositor/issues/41)）。理由は2つある。1つは、Marpの見た目はCSS前提でありTypstの組版モデルとは根本的に異なるため、変換の労力に対して得られる価値が薄いこと。もう1つ（こちらがより本質的）は、Marpが「1ファイル=1デッキ」を前提に「ディレクティブは以降のページに適用され、次の同種ディレクティブまで持続する」というスコープ規則を持つのに対し、このツールは「複数ファイル=1文書」を核の設計にしており（1章）、**章の並べ替えを安全に行えることが価値の核**である、という点である。ディレクティブがチャプター（ファイル）をまたいで持続する実装は、この並べ替えの安全性と正面から衝突する（あるチャプターを並べ替えると、意図しないヘッダーが別のチャプターに混入しうる）。この経緯を踏まえた「本当はどうあるべきか」の再検討の結論が、10章の`chapters[].header`/`footer`/`paginate`（[#42](https://github.com/tokudiro/text-compositor/issues/42)）である。既存の安全なパターン（`chapters[].landscape`/`paper_size`）をそのまま流用し、「ファイル内の任意の位置から持続する」性質を持たせないことで、この経緯の反省を反映している。

* **ディレクティブコメントの解釈**: `<!-- header: X -->` `<!-- footer: X -->` `<!-- paginate: true -->` は認識する。ただし、値は反映しない（読み捨てる）。認識しているため、他の生のHTMLタグ（`<br>`等）と違って警告は出さない。未知のディレクティブ・その他の生のHTMLタグは、従来どおり行番号付きの警告にとどめ、ビルドは継続する。**この扱いは、同じキー名を使うfront-matter/`chapters[]`側の`header`/`footer`/`paginate`（10章、[#42](https://github.com/tokudiro/text-compositor/issues/42)）とは独立している**。前者はファイル内の任意位置から持続する危険な性質を持つため意図的に無視し続け、後者はファイル全体に対する1回きりの明示指定なので反映する、という区別。
  * `<!-- pagebreak -->`（[#92](https://github.com/tokudiro/text-compositor/issues/92)）は例外で、値を読み捨てずその場で`#pagebreak(weak: true)`として実際に反映する。その場1回だけ効くアクションで状態を持ち越さないため、上記の「ファイル内の任意位置から持続する危険な性質」には該当しない。`document.marp_compat`の値に関わらず常に使える。
* **front-matter**: 冒頭の `---` ブロックは水平線ではなく設定として扱う。認識済みキーは `title`/`subtitle`/`author`/`date`/`paper_size`/`landscape`/`font_size`/`header`/`footer`/`paginate`（Marp固有キーの`marp:`/`theme:`等は無視、それ以外の未知キーは警告）。
  * `paper_size`/`landscape`/`header`/`footer`/`paginate`は、`config.yaml`のチャプター個別設定（10章）より弱い優先順位で適用する。`chapters`の該当エントリに明示指定が無い場合のみ、front-matterの値を使う（`paper_size`/`landscape`は[#17](https://github.com/tokudiro/text-compositor/issues/17)、`header`/`footer`/`paginate`は[#42](https://github.com/tokudiro/text-compositor/issues/42)）。
  * `title`/`subtitle`/`author`/`date`は認識する。ただし、値は反映しない（読み捨てる）。文書全体の表紙（`document.title`等、6章）は常に`config.yaml`側のみが正であり、front-matterはここには一切影響しない。
* **`---`/`***`/`___`（水平線・hr）の扱いは`document.marp_compat`で切り替える**（既定`false`、[#92](https://github.com/tokudiro/text-compositor/issues/92)）。
  * `false`（既定、CommonMark準拠）: `---`/`***`/`___`はいずれも単なる水平線（`#line(length: 100%)`）として描画する。改ページが必要な場合は上記の`<!-- pagebreak -->`を明示的に書く。
  * `true`（Marp互換）: `---`/`***`/`___`はいずれも改ページ（`#pagebreak(weak: true)`）として扱う。実際のMarpit（[marpit/docs/markdown.md](https://github.com/marp-team/marpit/blob/main/docs/markdown.md)）も3種の記法を区別なくスライド区切りに使うため、記法による差は付けない。テンプレート側の「見出し直前で改ページ」と二重に効いて空ページが発生する既知の不具合があるため、`weak: true`を用いて連続する改ページを1つに畳む。
* **表紙の二重化を避ける**: Marp のタイトルスライド（先頭の H1 と直後の H2）とテンプレートの表紙は同じ役割のため、両方出すと 1 枚目が重複する。`document.cover` で扱いを選べる。
  * `template`（既定）: テンプレートの表紙のみを出す。Markdown 側には手を入れない。
  * `replace`: テンプレートの表紙を出し、Markdown 先頭のタイトルスライドを取り除く。Marp と共用の Markdown を書き換えずに重複を解消できる（著者・日付を持つテンプレート表紙を活かす場合の推奨）。
  * `markdown`: テンプレートの表紙を出さず、Markdown 先頭のスライドをそのまま表紙にする。
  * `none`: どちらも出さない。
  * `replace` / `none` で取り除いた見出しは、サイレントな脱落を避けるため必ずログに出力する。テンプレートには `cover` 引数を追加する。ただし、既定値のときは引数自体を渡さず、`cover` を持たない既存テンプレートとの互換を保つ。
* **表紙のページ番号表示**: `document.cover_page_number`（真偽値）で、表紙（1ページ目）にページ番号を出すかどうかを切り替えられる。未指定時はテンプレート自身の既定値に従う（`templates/slide.typ` は表示・`templates/template.typ` は非表示）。本文側のページ番号表示には影響しない。`cover` 引数と同様、未指定時は引数自体を渡さず既存テンプレートとの互換を保つ。
* **改版履歴ページ**（[#56](https://github.com/tokudiro/text-compositor/issues/56)）: `document.revision_history`に版数・日付・改版内容（任意で担当）のリストを書くと、表紙と目次の間に、改版履歴を表にした独立した1ページを挿入する。
  * **記法**: `revision_history:`は`version`/`date`/`description`/`author`のキーを持つ辞書のリスト。すべて省略可能で、省略した項目は空欄。1行に少なくとも1つの値が必要。未知のキーは、綴りミスが黙って無視されるのを避けるためエラーにする（9章のFail-fast方針）。値は文字列として扱い、YAMLの日付・数値は文字列化する。`author`の列は、いずれかの行に値があるときだけ出す。
  * **なぜconfigに直接書くか**: 表として整形して表示する構造化データであり、Markdownの章とは役割が異なる。別ファイル（Markdown等）で自由に書きたい場合は、通常の章として運用できる。今回は「表紙と目次の間」という位置を持つ専用ページを対象とし、別ファイル指定は設けない。
  * **位置とページ番号**: 位置は表紙と目次の間に固定し、`revision_history`を書いたときだけ挿入する。表示・非表示の別キーは設けない。ページ番号は目次と同じローマ数字で、目次へ続ける（改版履歴がi、目次がii。改版履歴だけがあり目次が無い場合はi）。本文のページ番号は、従来どおり1から始まる。
  * **テンプレートの契約**: `conf()`の任意引数`revision_history`（辞書`(version:, date:, description:, author:)`の配列、値はすべて文字列）として渡す。値は生成するTypstコードにデータとして埋め込むため、`#`や`*`等はMarkup記法として解釈されない。`description`内の改行は文字列中の`\n`で渡し、テンプレートが`linebreak()`へ変換する。未指定なら引数自体を渡さず、この引数を持たない既存テンプレートとの互換を保つ（`toc`等と同じ方針）。同梱の`slide.typ`は、引数を受け取るだけで何も出力しない（no-op。10章の独自テンプレートの契約どおり）。
  * **範囲外**: Gitのタグ・コミットからの版数の自動生成は行わない（ビルドの決定論、9章と衝突するため）。`variables:`（#72）は`document:`の値には適用しない。
* **ディレクティブ以外の HTML タグ**（`<br>` 等）は行番号付きで警告する（8章のフェイルファスト方針）。ディレクティブ構文に合致するもののみを解釈し、それ以外は無害化しない。

## 8. 複数の書き手による協調執筆
本システムは「複数の書き手（AIも人間も問わない）が原稿を持ち寄り、人間が直接Markdownをレビュー・加筆修正してGitにコミットする」という協調ワークフローを前提とする。レビュー担当者の介入に伴う例外処理として「Raw Typstパススルー」を許容する。ただし、書き手からのデザイン権限剥奪とセキュリティを担保するため、以下のガバナンス設計を設ける。

* **Raw Typstの専用タグとガバナンス**: 人間が高度な数式やTypst固有のレイアウト機能を使いたい場合のみ、Markdown内で ```` ```typst-exec ```` ブロックとして記述することで生のTypstコードとしてPDFに注入する（単なるコード表示用の ```` ```typst ```` とは区別する）。
  * **ホワイトリスト方式のガードレール**: 既定を禁止とし、`reviewed/` 配下に置かれたファイルでのみ許可する。ドラフトから本番への昇格は必ず人間のPR承認を必須とする。
  * **ディレクトリ非依存の運用への対応**: ドキュメントがツール外の任意の場所に置かれるため、`reviewed/` 規約に加えて `config.yaml` での明示的な許可（例 `security.allow_typst_exec: [ "appendix/*.md" ]`）を将来的な代替手段として想定する。許可の意思表示は必ずコミット対象のファイルに残ること（CLI オプション一発で許可できてはならない）を原則とする。
  * **残存リスクの明記**: 「レビュー担当者が持ち込まれた原稿（AI出力に限らない）を無検証でcommitする」ケースは、技術的な仕組みだけでは防げない残存リスクであり、チームのレビュー文化に依存することを前提とする。
* **ファイルアクセス制限 (セキュリティ)**: `typst-exec` ブロック経由で意図せぬローカルファイルがPDFに埋め込まれる事故を防ぐため、`typst compile` 実行時は常に `--root` にドキュメントルート（5章）を指定し、アクセス範囲をサンドボックス化する。ツール本体のディレクトリを `--root` にしてはならない。
* **HTMLタグのフェイルファスト**: 無意識に混入したHTMLタグ（`<br>`等）をサイレントに無視すると事故につながるため、AST解析時にHTMLタグを検出した場合は行番号付きの警告（またはエラー）を出す（7章のディレクティブを除く）。
* **HTMLを入力フォーマットとして本格対応することは見送った**（1章）: Pandocのように任意のHTMLファイルをそのまま読み込んで変換する機能を持たせたい、という発想は検討した。しかし、実装・方針の両面で見送った。
  * **実装面**: 現在の変換パイプラインは「Markdown → markdown-it-pyのAST → Typst」というMarkdownの単純な構造に特化した変換器である。HTML対応にはDOM木を作るパーサーと、そこから別のTypst変換ロジック（見出し・段落・リスト・テーブル・`<div>`/`<span>`のネスト・インラインstyle・CSSクラス等）を一から書く必要があり、既存のMarkdown変換器と同規模かそれ以上の別実装になる。
  * **方針面（より本質的）**: このツールは「HTMLは基本非対応、例外は狭い許可リストに1パターンずつ慎重に追加する」という立場を一貫して取っている（`<span style="color:...">`のみを特別扱いした[#46](https://github.com/tokudiro/text-compositor/issues/46)が代表例）。HTML入力への本格対応は、この方針を正面からひっくり返すことになる。Pandocは「あらゆる形式間の汎用コンバータ」として何年もかけて各形式のリーダー/ライターを作り込んでいる。一方、text-compositorは「レビュー可能なMarkdown→安全なPDF」に絞ったツールであり、doc/diff.mdでもその価値は機能の広さではなくガバナンスにあると位置づけている。
  * **代替案**: HTMLで持っているコンテンツを取り込みたい場合は、`html2text`やPandoc自体等の既存ツールでツールの外側でHTML→Markdownに変換してから、通常どおり`chapters`に渡すことを推奨する。
  * 「どうしても必要になったときに再検討する」という結論で、現時点でissue化はしていない。

## 9. 変換パイプラインの基本方針
* **Unixフィルタとしての設計は意図的に採用していない**: `build.py`は標準入力/標準出力で連鎖する小さなフィルタ群ではなく、`config.yaml`というマニフェストを読んで複数ファイルをオーケストレーションする単一プロセスである。これは複数の断片を1つの文書へ集約するという1章の核である目的そのものが、全入力を同時に見る必要がある（目次・章番号等）ためで、Pandocの複数ファイル結合や`make`と同様、集約系ツールでは一般的な形である。図表レンダリング（Mermaid/Graphviz、11章）やTypstコンパイル自体は専門ツールへの委譲（Playwright経由のCDP直接操作・`diagraph`・`typst`パッケージ）という形でフィルタ的な境界を保っている。
  * かつてMarpディレクティブ（7章、`<!-- header: X -->`等）がチャプター（ファイル）をまたいで持続する機能を実装したことがあったが（[#16](https://github.com/tokudiro/text-compositor/issues/16)）、これは「1つのファイルだけを見て1つのTypst断片を返す」という純粋な変換から外れるだけでなく、このツールの核である**章の並べ替えの安全性**（並べ替えると意図しないヘッダーが混入しうる）とも衝突したため撤回した（[#41](https://github.com/tokudiro/text-compositor/issues/41)）。今後同種の「チャプターをまたいで持続する状態」を持つ機能を検討する際は、この失敗を踏まえること。代わりに採用した安全な設計（`chapters[].header`/`footer`/`paginate`、状態を持続させず各章が毎回自分の値を独立に解決する）は10章、[#42](https://github.com/tokudiro/text-compositor/issues/42)を参照。
* **ASTベースの変換**: Markdownを単なる文字列置換（正規表現等）で処理するとテーブル等で破綻しやすいため、`markdown-it-py` でAST（抽象構文木）を生成し、そこからTypst構文へ決定論的にマッピングする。
* **特殊文字のエスケープ**: AI出力テキスト内のTypstマークアップと衝突する文字（`#`, `$`, `@`, `_`, `*`, `<`, `>`, `[`, `]` 等）は専用のエスケープ処理で必ず無害化する。
  * **行頭ブロック記法のエスケープ**: 行頭の `=` `-` `+` `/` `1.` は Typst の見出し・リスト等として解釈され、地の文が勝手に見出し化して目次にまで混入する。改行直後のテキストは行頭記号をエスケープする（実測で確認済みの実害）。
* **リスト構造の忠実な再現**: markdown-it はタイトなリストの段落トークンに `hidden` を立てる。これを無視すると Typst 側が loose list と解釈し、箇条書きが間延びする。リストの入れ子はスタックの深さに応じたインデントで出力し、階層を保持する。
* **決定論的出力とバージョン固定**: `requirements.txt` のパーサーライブラリに加え、Typstコンパイラ本体および利用する全プラグイン（例: `diagraph:0.3.7`）のバージョンを厳密固定する。Typstコンパイラ自体はPyPIパッケージ（3章）で版固定されているため、同梱バイナリとの食い違いは構造的に起きない。
  * **実行時のバージョン整合性チェック**（[#49](https://github.com/tokudiro/text-compositor/issues/49)）: `requirements.txt`にピン留めされたTypstのバージョンと、実際にインストールされているバージョンが一致するかを毎回のビルド時に自動確認する。不一致でも警告のみでビルドは継続する（Fail-fastにはしない）。同じチェックは`--check-env`（4章）でも実行できる。`requirements.txt`が同梱されないpipインストール環境（[#111](https://github.com/tokudiro/text-compositor/issues/111)）では、比較対象が無いため何もしない。
* **日本語フォントの指定**: OSのデフォルトフォントに依存せず、CJK対応のオープンソースフォントを`font_paths`（Typst Python APIの`typst.compile(..., font_paths=[...])`、CLIの`--font-path`に相当）で明示的に指定する。テンプレート側で`Yu Gothic`等のOSフォントを直接指定してはならない。**（実装済み）** 採用フォントは Noto Sans JP（[SIL Open Font License](https://github.com/notofonts/noto-cjk/blob/main/Sans/OFL.txt)、再配布可）。取得方法は2章、実装は`build.py`の`ensure_fonts()`を参照。`templates/template.typ`・`templates/slide.typ`とも`set text(font: "Noto Sans JP", ...)`のみを指定し、OSフォント名は書かない。Noto Sans JPに無いグリフ（絵文字等）はTypstが自動でシステムフォントにフォールバックする。

## 10. 動的ページレイアウトとデータ駆動型アグリゲーション
* **章ごとのページ設定 (Dynamic Layout)**: ドキュメント全体または特定の章（Markdownファイル単位）に、独立して用紙サイズ（例: A4, A3）と用紙の向き（Landscape/Portrait）を指定できる。設定は `config.yaml` のグローバル設定および章ごとのローカル設定（上書き）として定義する。
  * テンプレートは受け取った `paper_size` / `landscape` を必ず `set page` に反映すること。**（実装済み、[#18](https://github.com/tokudiro/text-compositor/issues/18)）** `templates/slide.typ` は当初 `landscape` を引数に取りながら `set page` に渡しておらず、グローバル指定が無視される既知のバグがあった。表紙・本文いずれの `set page` にも `flipped: landscape` を渡すよう修正済み。
* **データ駆動型アグリゲーション (Data-driven Aggregation)**: 「1テストケース＝1ファイル」の原則（Gitでのコンフリクト回避・並行作業の容易化）を守るため、指定ディレクトリ内の大量のYAML/JSONファイルを読み込み、AST変換を経由してTypstのネイティブなテーブル（マトリクス）として出力する。集約ディレクトリのパス基準は5章に従う。
* **CSVのテーブル変換**（[#36](https://github.com/tokudiro/text-compositor/issues/36)）: `chapters`に`.csv`ファイルを指定すると、1行目をヘッダー行とみなしてTypstの`#table()`へ変換する（図表ソースファイルの直接指定、本章4と同じ「1ファイル＝1章」パターン）。**（実装済み）** `aggregate`との役割分担は、`aggregate`が「YAML/JSONのテストケース専用スキーマ（id/title/priority等の固定列）」を前提にした専用機能であるのに対し、CSV対応は任意の表形式データを対象にした汎用機能という違いがある。
  * **区切り文字**: カンマ固定。タブ区切り等の自動判定（sniffing）は行わない。このツールが一貫して採る「明示性優先・魔法をしない」方針（サイズ指定・alert記法等と同じ）に合わせた設計判断。
  * **クォート処理**: RFC 4180準拠（セル内カンマ・改行、`""`によるクォート文字自体のエスケープ）は、Python標準ライブラリの`csv`モジュールにそのまま委譲する。`splitlines()`で先に行分割すると、クォートされたセル内の改行が失われる（`csv.reader`が行をまたいだクォートを復元する前に改行文字自体が消える）ため、`io.StringIO`で生テキストのまま渡す。
  * **列数不揃いの行**: 他の描画失敗（mermaid等の構文エラー）と同様、フォールバックせずFail-fastで即エラー終了する（9章の方針）。エラーメッセージにはファイル名と行番号を含める。
  * **セルの内容**: Markdownとしては解釈しない（本章冒頭の通り、`.md`以外はmarkdown-itを一切通さない方針）。Typstの特殊文字のみエスケープしたプレーンテキストとして埋め込む。既存のMarkdownテーブルと同じ`table_header`スタイル（本項目の次の箇条書き参照）を適用する。
* **テーブルヘッダのスタイル**（[#45](https://github.com/tokudiro/text-compositor/issues/45)）: 通常のMarkdownテーブル（```` | a | b | ````構文）のヘッダ行の太字・背景色・文字色を、`document.table_header`（グローバル）と`chapters[].table_header`（章ごとの上書き。landscape/paper_sizeと同じ優先順位パターン）で指定できる。**（実装済み）** 未指定のキーは装飾なし（後方互換）。front-matterでの上書きは非対応（`_render_markdown_chapter`がfront-matter解決前に`table_header`を確定させる必要があるため）。aggregate（YAML/JSONテストケース集約）テーブルは別コードパスであり対象外（既存の固定スタイルのまま）。実装は`TypstRenderer.table_header_style`（章ごとに`_render_markdown_chapter`が設定）を`render_tokens`の`table_open`/`th_open`/`th_close`が参照し、`#table(..., fill: ...)`と`#strong[]`/`#text(fill: ...)`のTypstコードを生成する。
* **本文ページのヘッダー・フッター・ページ番号**（[#42](https://github.com/tokudiro/text-compositor/issues/42)）: `document.header`/`footer`/`paginate`（グローバル）と`chapters[].header`/`footer`/`paginate`（章ごとの上書き、landscape/paper_sizeと同じ優先順位パターン。front-matterも同じ弱さで拾う）で指定できる。**（実装済み）** `header`未指定時の既定値は`document.title`（テンプレート側のフォールバック挙動を`build.py`側でも`effective_global_header`として再現し、章の解決ロジックが常に具体的な値を起点にできるようにしている）。`footer`未指定時はページ番号のみ、`paginate: false`でページ番号自体を非表示にできる。
  * `state()`は使わない（[#16](https://github.com/tokudiro/text-compositor/issues/16)の反省点）。landscape/paper_sizeと全く同じ「値が変化した章でだけ`#set page(...)`を出し直す」パターンを踏襲し、`build.py`の`_page_set_fragment()`が`paper`/`flipped`/`header`/`footer`をまとめて1つの`#set page(...)`呼び出しに統合する。各章は自分の値を`config.yaml`/front-matterから毎回独立に解決するため、章を並べ替えても他の章の値が漏れ出さない（実測で確認済み）。
  * テンプレート（`templates/template.typ`・`templates/slide.typ`）は、この機能のために`render-header(header_text)`/`render-footer(footer_text, paginate)`という2つの関数をモジュールレベルでエクスポートする。`build.py`はチャプターごとに`header: render-header("...")`のようなTypstコードを直接生成して呼び出す（`header`がNone、すなわちchapters[]/front-matterで明示的に`null`を指定した場合のみheader自体を非表示にする。テンプレートの`render-header`は常に非None文字列を受け取る前提）。
  * Marpの`<!-- header: X -->`等のインラインHTMLコメント形式のディレクティブ（7章）とはキー名が同じだが別の仕組みであり、意図的にこちらは値を反映しない（ファイル内の任意の位置から「以降に持続する」という#16と同種の危険な性質を持つため）。
* **章（section）グルーピングと見出しレベルのオフセット**（[#68](https://github.com/tokudiro/text-compositor/issues/68)、[#43](https://github.com/tokudiro/text-compositor/issues/43)を統合）: `chapters:`に`- section: 見出し`と、入れ子の`chapters:`を書くと、複数の章をひとつの章としてまとめられる。「3編構成で、目次を『編 → 章』の2階層にしたい」用途を想定する。
  * **見出し**: sectionの見出しはH1として自動生成する。配下の章の見出しは`heading_offset`段（既定1）だけ下がり、MarkdownのH1がH2になる。目次はテンプレートの`outline(indent: auto)`が見出しレベルで階層化するため、テンプレートの変更は要らない。`heading_offset`は0〜5の整数で、章側（`file:`/`aggregate:`エントリ）にも指定でき、その場合は所属sectionの値より優先する。フラットな章に指定すれば、section無しで見出しをずらせる。
  * **設定の継承（#43の要求）**: sectionには`header`/`footer`/`paginate`/`landscape`/`paper_size`/`background`/`logo`/`table_header`を指定でき、配下の全章の既定値になる。優先順位は「章の指定 ＞ front-matter ＞ section ＞ `document:`のグローバル」。`table_header`は他の階層と同じくキー単位でマージする。sectionの設定はそのsection内にだけ効き、次のsectionやフラットな章には持続しない（[#16](https://github.com/tokudiro/text-compositor/issues/16)の反省点と同じく、`state()`ではなく「値が変化した所でだけ`#set page(...)`を出し直す」方式）。
  * **実装**: `_expand_chapters()`が`chapters`をsectionの見出しを含むフラットな描画順に展開し、設定ミスは描画（重い処理）の前にFail-fastで報告する。各章には、section適用後の値をまとめた`ChapterDefaults`を渡し、従来の「グローバル」引数の位置へ差し込む。見出しのずらしは`TypstRenderer.heading_offset`が担い、`render_tokens`が`=`の数に加算する。
  * **制約**: sectionの入れ子は非対応（2階層の目次に限る）。sectionと`file:`/`aggregate:`は併記できない。`cover: replace`/`none`で先頭の章のタイトルを落とす挙動は、先頭がsectionの場合は適用しない（sectionの見出しが先頭に残り、配下の最初の章のタイトルは落とさない）。sectionが無い既存のconfigは、出力が従来と変わらない。
* **巻末用語索引**（[#47](https://github.com/tokudiro/text-compositor/issues/47)、GitHub Wiki拡張、7章）: `document.glossary: true`のとき、本文中の`[[用語]]`を検出し、巻末に用語と出現ページ番号の一覧（索引型。定義文は持たない）を自動生成する。**（実装済み）** 同一用語が複数ページに出現した場合は全ページ番号を重複除去のうえ昇順・カンマ区切りで列挙する。並び順は文字コード順（Pythonの`sorted()`）。`[[表示|用語]]`のような区切り記法は使い方が分かりにくいため不採用（[#48](https://github.com/tokudiro/text-compositor/issues/48)）。
  * **実装**: `[[用語]]`はAST上の`text`トークンの中身のみを正規表現（`WIKILINK_RE`）で走査して検出する（生テキスト全体への正規表現置換ではない）。これにより`code_inline`/フェンス内の`[[...]]`は対象トークンが異なるため巻き込まれない（実測で確認済み）。検出のたびに一意なTypstラベル（`gloss-0`, `gloss-1`, ...）を発行し、`#metadata(none)<gloss-N>`という不可視要素として用語テキストの直後に埋め込む。`TypstRenderer.glossary_terms`（用語→ラベルID一覧のdict、全チャプターを跨いで蓄積）に登録する。
  * 全チャプター処理後、`_build_glossary_section()`が`glossary_terms`から巻末ページのTypstコードを生成する。目次（`outline()`）と同じ「`context`+`query()`でレイアウト後にラベルの実際のページ番号を取得する」パターンを、`outline()`を使わず手動の`context { query(label(...)) }`ループで実装している（Typst公式ドキュメントが索引機能の実装例として案内する標準的な手法）。ページ番号の重複除去には`array.sorted().dedup()`を使う（`dedup()`単体は隣接要素のみの除去ではなく全体の重複除去であることを実機で確認済み。ただし、`sorted()`してから`dedup()`する順序の方が意図が明確なためこちらを採用）。
* **文字色指定**（[#46](https://github.com/tokudiro/text-compositor/issues/46)、7章）: `[text]{color=...}`（Pandoc由来のブラケット+属性記法）と`<span style="color:...">`（HTML特別扱いの1パターン）の2記法を、config.yamlでの切り替えなしに常に両方サポートする。**（実装済み）** どちらの記法を使うかで同じ原稿の意味がconfig次第で変わる事態を避けるための設計判断（Marpディレクティブ持続機能を撤回した理由と同種の問題）。
  * **実装**: `[text]{color=...}`は`mdit-py-plugins`の`attrs_plugin`を`spans=True, allowed=["color"]`で有効化して実現する（`spans`は既定`False`で、初回調査時にこれを見落として「対応していない」と誤判定した経緯がある。`allowed`でcolor以外の属性を解析段階で除去し、render_inline側の判定を単純化している）。`span_open`/`span_close`トークンとして出力され、`color`属性があれば`#text(fill: ...)`でラップする（無ければ何もラップしない。スタックで開閉を対応させる）。
  * `<span style="color:...">`はHTML側の開始・終了が独立した`html_inline`トークンとして出てくるため、`render_inline`内でスタック（`html_span_depth`）を使って対応させる。段落が終わるまでに閉じられなかった場合、壊れたTypstコード（閉じ角括弧の不足によるコンパイルエラー）を生成しないよう自動的に閉じたうえで警告を出す。
  * 色の値は、Typstの`rgb()`関数が`"#rrggbb"`のようなhex文字列は受け付けるが`"red"`のような色名文字列は受け付けない（コンパイルエラーになる）という仕様上の制約があり、`_color_to_typst()`（#45で新設、本機能でも再利用）が単純な英数字+ハイフンの識別子（`red`等）ならTypstの色定数名としてそのまま渡し、それ以外（hex形式や不正な値）は`rgb("...")`の文字列引数として渡す、という判定を行う。
* **本文中の一部フォントサイズ指定**（[#93](https://github.com/tokudiro/text-compositor/issues/93)、7章）: `[text]{size=10pt}`（文字色指定と同じブラケット+属性記法）で、本文中の一部テキストだけフォントサイズを変えられる。**（実装済み）** `document.font_size`/`chapters[].font_size`はページ単位の指定であり、脚注・出典のようにページ内の一部だけを小さく見せたいケースをカバーできなかったための追加。
  * **実装**: `attrs_plugin`の`allowed`に`"size"`を追加し（`allowed=["color", "size"]`）、`span_open`で`color`と同様に`size`属性を読む。`color`・`size`のどちらか一方でも両方でも、`#text(...)`呼び出し1つに`fill:`/`size:`をまとめて出力する（`[text]{color=... size=...}`のように同時指定した場合に`#text`の二重ネストを避けるため）。
  * サイズの値は front-matterの`font_size`（#41）と同じ`"10pt"`/`"10.5pt"`形式のみ許可する（`FONT_SIZE_RE`として正規表現を共通化）。不正な値は警告を出したうえでサイズ指定なし（`size`属性を無視）として扱い、ビルドは止めない（`color`が無効値の場合にコンパイルエラーで止まる仕様とは異なる。単位や書式の間違いは実務上ありふれており、フォントサイズ1箇所のミスでビルド全体を止めるほどではないという判断）。

## 11. プラグイン（図表描画アドイン）の設計方針
2章の実行環境の要件は本章のプラグインにもそのまま適用される。重い依存関係を持つ図表描画ツールは、コアパイプライン（テキスト→PDF化）とは別に「オプトイン形式のプラグイン」として分離する。外部APIへの通信による図表生成を行わない（完全ローカル完結）という2章の絶対要件は、プラグインであっても緩めない。

1. **Graphviz (dot)**: コミュニティ製Wasmプラグイン（`diagraph`）で、追加環境なしにローカル描画する。**（実装済み）** テンプレート側の `show raw.where(lang: "dot"/"graphviz")` が ```` ```dot ```` フェンスを自動的にレンダリングする。
2. **PlantUML**: ローカルJava環境を要求し、純Javaレイアウトエンジン「Smetana」（`-Playout=smetana`）を採用してGraphviz(dot)等の外部バイナリへの依存を避ける。**（実装済み）**
   * **ライセンス**: 本体は`plantuml-mit-*.jar`（MIT）を採用する。`mit-light`版（DITAA等ごく一部を除き機能同等、約7.4MB）も検討した。しかし、jarの中身を比較した結果、差分は`stdlib/`配下のクラウドアイコン素材と絵文字データのみだった。原稿（Markdown、GitHub管理）には絵文字が含まれ得るため、フル機能の`mit`版（約17.6MB）を採用する（[#22](https://github.com/tokudiro/text-compositor/issues/22)）。
   * **実行環境の前提**: `find_system_java()`（`build.py`）でシステムのJava（11以上。PlantUML最新版のクラスファイル要件）を検出して再利用する（2章）。GitHub-hosted runner（`ubuntu-latest`）にはJavaが標準搭載されているため、そのまま動く。見つからない場合の挙動は`plugins.plantuml_auto_download`（既定`true`）で制御する。`true`ならEclipse Temurin JRE（Adoptium配布、GPLv2+Classpath Exception。OpenJDK本体と同じライセンス系統）をバージョン・プラットフォーム別にURL・SHA256を固定して自動取得し（9章の決定論的出力）、`false`なら本章3のMermaid/Chrome（[#35](https://github.com/tokudiro/text-compositor/issues/35)）と同じFail-fastになる。既定を自動取得側にしたのは、Chromeと違いJavaは手元環境への標準搭載率が低く、「Java 11以上を入れて」という指示だけでは行き止まりになりやすい（配布元の選択肢が多く迷いやすい）ため、ローカル開発時の利便性を優先する設計判断による。ダウンロードされる実体が約49.7MB（Chromiumの約700MBの1桁下）に収まることも判断材料にした。
   * **実装**: `plantuml.jar`をコンテンツのSHA256込みでOS標準のユーザーキャッシュ領域（2章のフォントと同じ`platformdirs`経由の場所）へ取得・キャッシュし、`java -jar plantuml.jar -tsvg -pipe -Playout=smetana`へ図のソースを標準入力で渡し、標準出力のSVGをそのまま使う。常駐プロセスを持つMermaidのヘッドレスブラウザとは異なり、図ごとにsubprocessを都度起動する（描画コストがMermaidほど大きくないため）。図の種別・`plantuml.jar`のSHA256・入力テキストの複合ハッシュをキー名として`project_dir/.text-compositor/cache/`にSVG結果をキャッシュする点（#26）、描画失敗（構文エラー等、終了コード非0）でテキストへフォールバックせず即エラー終了する点はMermaidと同じ方針。`@startuml`/`@enduml`の自動補完は行わない（明示性を優先）。
3. **Mermaid**: ヘッドレスブラウザでの描画を要するため、別途環境構築を伴うオプトイン機能として扱う。**（実装済み）**
   * **実行環境の前提**: `find_system_browser()`（`build.py`）でシステムにインストール済みのChrome/Edgeを検出して再利用する（2章）。GitHub-hosted runner（`ubuntu-latest`）には標準搭載のChromeがあるため、そのまま動く。見つからない場合の挙動は`plugins.mermaid_auto_download`（既定`false`）で制御する。既定ではFail-fastでエラー終了する（[#35](https://github.com/tokudiro/text-compositor/issues/35)。npm/npxに依存しなくなったため、npm経由の代替ダウンロードという選択肢が無い）。`true`にした場合のみ、`playwright install chromium`相当の呼び出しでPlaywright自身のChromium（実測約700MB）を取得し、`connect_over_cdp()`ではなく`chromium.launch()`で起動する。この約700MBはまさに#34/#35で避けた規模であるため既定はfalseのままとし、PlantUML側の`plugins.plantuml_auto_download`（既定`true`、JREは約49.7MB）とは意図的に非対称にしている（#22の設計議論）。
   * **実装**: Mermaid公式配布の単一バンドルJS（`mermaid.min.js`、UMD形式、全図種込み。実測約3.4MB）をOS標準のユーザーキャッシュ領域（2章のフォントと同じ`platformdirs`経由の場所）へバージョン・SHA256を固定してダウンロード・キャッシュし（9章）、Playwright（Python版）の`connect_over_cdp()`でシステムブラウザにCDP接続してブラウザ内で`mermaid.render()`を直接呼び出す（`mermaid-cli`丸ごとの導入は不要、Node.js自体が不要になった）。1回のビルドでヘッドレスブラウザ・ページは1つだけ起動し、複数のMermaid図で使い回す。図の種別・`mermaid.min.js`のSHA256・入力テキストの複合ハッシュをキー名として `project_dir/.text-compositor/cache/` にSVG結果をキャッシュする（[#26](https://github.com/tokudiro/text-compositor/issues/26)。レンダラが変わったときに古いSVGを使い回さないため）。mermaid既定のHTMLラベル（`<foreignObject>`）はTypstのraw SVGレンダラーが描画できないため、`flowchart.htmlLabels`とトップレベルの`htmlLabels`両方を`false`に指定し通常のSVG `<text>` 要素で出力する（トップレベルのみでは効かないことを実測で確認済み）。
   * **図とテキストのレイアウト**: `::: layout-right ... :::`（テキスト左・図右の2カラム）、`::: layout-compare ... :::`（2つの図を左右に並べる）という独自のMarkdown拡張記法を用意した。ASTの通常フローに入る前の生テキスト段階で正規表現により切り出し、個別にTypstの`grid`へ変換している。横長の図をlayout-compareで並べると縮小されすぎて読めなくなることを実測で確認済み。正方形に近い図でのみ使うこと。
   * **`layout-left`と比率指定（[#81](https://github.com/tokudiro/text-compositor/issues/81)）**: `layout-right`の左右反転版として`layout-left`（図を左・テキストを右）を追加した。共通の`_render_layout_block(inner_text, flip, ratio)`に統合し、`flip`で列の並び順（`[image, text]`か`[text, image]`）と`align`の左右を切り替える。数値の合計が100である必要はなく（`fr`は相対比率のため`{left=3 right=7}`と`{left=30 right=70}`は同じ見た目）、それ以上のバリデーションは行わない（`layout-columns`の`n`が列数の妥当性チェックをしていないことと方針を揃えた）。省略時の既定比率は`layout-right`がテキスト35:図65、`layout-left`が図65:テキスト35と左右対称にしている。
     * **記法の変更（[#83](https://github.com/tokudiro/text-compositor/issues/83)）**: 当初は`layout-right-30:70`のような末尾`-左:右`サフィックス方式（`layout-columns-N`と同じパターン）だった。`:::`ブロック自体がPandocのfenced divsに似た記法であること、#82でフェンスに`{width=50%}`という中括弧属性記法を導入したことを踏まえ、`layout-right {left=30 right=70}`という中括弧属性方式に統一した（このツールはまだ利用者が限定的なため破壊的変更を許容した）。属性名を`width`/`height`ではなく`left`/`right`にしたのは、#82の「画像1枚の物理サイズ」（Typst寸法値）という意味とlayout-rightの「2カラムの相対比率」が衝突するのを避けるため。ブロック名自体は中括弧の外（`layout-right {...}`）に置き、Pandoc標準の`::: {.layout-right ...}`という書き方（ブロック名も中括弧内に`.クラス名`として書く）には寄せていない。このツールの原稿がPandocでもそのまま動くことは目標にしておらず（[#84](https://github.com/tokudiro/text-compositor/issues/84)は逆方向の話）、フェンス側の`{width=50%}`との内部一貫性を優先した。
   * **対応する図の種類**（[#77](https://github.com/tokudiro/text-compositor/issues/77)）: 当初はmermaid専用だった。mermaid/plantuml/dot/graphvizフェンスに加え、単独行のMarkdown画像（`![alt](path)`）も置けるように一般化した。**（実装済み）** フェンスの種類ごとの実際の描画方法（mermaid/plantumlはPythonが事前にSVG化、dot/graphvizはTypstテンプレート側の`show`ルールがコンパイル時に描画）は本章1〜3と共通で、layoutブロック側は新しい描画ロジックを持たず、通常のMarkdownフロー（`render_tokens`）と同じ`_render_diagram_fence()`ディスパッチャーに委譲するだけ。画像は`render_inline`の通常の画像処理（`alt|width=/height=`構文込み）にそのまま委譲する。`layout-compare`は2つの図の種類が混在してもよい（例: 片方はmermaid図、もう片方は写真）。
   * **画像サイズの自動調整**: `templates/slide.typ` の `fit-image()` が幅・高さそれぞれの縮小率を計算し、小さい方を採用する。高さの上限は固定値`MAX_IMG_HEIGHT`（現在12cm）。Typstの`layout()`が返す`size`は「ページの残りスペース」ではなく「コンテナ全体のサイズ」で、見出しや本文が使った分を考慮できないため、動的計算ではなく安全側の固定値にしている。
   * **サイズの明示指定（[#82](https://github.com/tokudiro/text-compositor/issues/82)）**: フェンスのinfo stringに`{width=50% height=8cm}`のようなPandoc風の属性を書くと、上記の自動縮小をバイパスしてそのサイズをそのまま反映できる（拡大も含む）。`DIAGRAM_OR_IMAGE_RE`と、通常のMarkdownフロー（`render_tokens`の`fence`トークン処理）双方でinfo stringから`(lang, width, height)`を切り出し、`_render_diagram_fence(lang, code, width, height)`へ渡す形に統一した。Mermaid/PlantUMLはwidth/height指定時に`fit-image()`ではなく画像トークンと同じ`#image(path, width:, height:)`を直接生成する（`_render_sized_image()`）。Graphviz/dotは元々Python側で`_render_raw_text`に素通しし、Typst側の`show raw.where(lang: "dot")`ショールールに描画を委ねていた。しかし、ショールールは`it.text`（コード文字列）しか受け取れずwidth/heightを渡す経路が無いため、`render-graph(code, width:, height:)`をconf()のローカル関数からモジュールのトップレベル定義へ移動してエクスポートし（独自テンプレートの必須関数に追加。`doc/usage/10_custom_template.md`）、明示指定時はbuild.py生成コードから`#render-graph(...)`を直接呼び出す形にした（width/height未指定時は従来どおりraw()経由でショールールに委ねる）。
   * **`layout-feature`（[#78](https://github.com/tokudiro/text-compositor/issues/78)）**: 写真（または図）をフルブリードで敷き、下部に半透明の帯とキャッチコピーを重ねる。図/画像の抽出は`layout-right`/`layout-compare`と同じ`DIAGRAM_OR_IMAGE_RE`を再利用する。ただし、表示方法は専用（Markdown側の`alt|width=`指定は無視し、`width`/`height`とも100%＋`fit: "cover"`で枠いっぱいに敷き詰める）。写真の縦横比に関わらず枠の高さを`FEATURE_IMG_HEIGHT`（現在70%）に固定しているのは、`width: 100%`のみだと縦長写真で大幅に高さがはみ出すことを実機確認で確認したため（CSSの`background-size: cover`と同じ考え方）。キャッチコピーは`gradient.linear(angle: 90deg)`（透明→黒、上から下）を背景に敷いた`block`の上に白文字で重ねることで、写真の明暗に関わらず可読性を確保する。`fit: "contain"`＋`measure()`で写真の実寸に合わせて帯を配置する（トリミングなしで全体を表示する）案も検討した。しかし、想定用途（スライド自体と同じ横長〜正方形に近い写真）では`cover`と`contain`の見た目にほぼ差が出ない一方、縦長写真は元々が想定外の使い方（異常系）であり、そのためだけに実装を複雑化する価値は無いと判断し`cover`のままとした。縦長写真は上下がトリミングされる旨を利用者向けドキュメントに明記している。
   * **`layout-columns`（[#78](https://github.com/tokudiro/text-compositor/issues/78)）**: 中身（任意のMarkdown、種類のバリデーションなし）をN列（省略時2列、`layout-columns {n=3}`のように指定可能。当初は`layout-columns-3`という末尾サフィックス方式だった。[#83](https://github.com/tokudiro/text-compositor/issues/83)でlayout-right等と同じ中括弧属性方式に統一した）に分割する。素朴に`#columns(N)[...]`と書くだけでは、Typstの`columns()`は「1列の高さを超えて初めて次列へあふれる」実装のため、スライドのように本文が短く1列に収まってしまう内容では分割されない（実機確認で判明）。`measure()`で中身の自然な高さを測り、その1/N（+わずかな余裕）をコンテナの高さとして明示的に指定することで、あふれを強制してN列に均等分割している。
   * **`align`（[#87](https://github.com/tokudiro/text-compositor/issues/87)）**: 本文（段落）を中央寄せ・右寄せにする手段が無かったため、`layout-columns`と同じ「中身は任意のMarkdown、バリデーションなし」という枠組みを流用し、`::: align {align=center}` / `::: align {align=right}` ... `:::` ブロックを追加した。`{n=N}`（layout-columns）や`{left=N right=M}`（layout-right/left）と同じ中括弧属性方式で`align=`の値を受け取り、`FENCE_ATTR_RE`をそのまま再利用する。中身全体を`#align(値)[...]`でラップするだけの薄い実装。画像の`align`属性（#75、`![alt|align=center](path)`）と同様、指定しない場合の既定の見た目（左寄せ）は変わらない。`align=`の値自体（`left`/`center`/`right`以外を弾く等）の妥当性チェックは、他の独自属性（`layout-columns`の`n`、`layout-right`/`left`の比率）と同じ方針で行わない。
   * **`layout-takahashi`（[#95](https://github.com/tokudiro/text-compositor/issues/95)）**: 高橋メソッド（1スライドに短い言葉を大きな文字だけで見せるプレゼン手法）向けに、中身（任意のMarkdown）を画面の上下左右中央・大きな文字で表示するブロックを追加した。`align`ブロックが水平方向の寄せのみ（垂直方向の中央揃えは非対応）だったのに対し、こちらは`#align(center + horizon)[#text(size: ...)[...]]`で水平・垂直の両方向を中央揃えする。文字サイズは`TAKAHASHI_DEFAULT_SIZE`（96pt。本文既定の10.5pt比で十分大きい値を実機確認のうえ採用）を既定とし、`{size=...}`（`FENCE_ATTR_RE`を再利用）で上書きできる。他の独自属性と同じ方針でサイズ値の妥当性チェックは行わない（不正値は`#text()`呼び出しがコンパイルエラーになる）。中身の種類を判別する必要が無い点は`layout-columns`/`align`と同じで、Fail-fastのバリデーションは設けていない。
4. **D2**（[#90](https://github.com/tokudiro/text-compositor/issues/90)）: PlantUMLと同じ「ローカルの外部実行ファイルへsubprocessでソースを渡し、SVGを受け取る」方式を採る。**（実装済み）**
   * **検討経緯**: 当初PythonパッケージのD2ビルダーライブラリを検討した。しかし、これは「PythonオブジェクトからD2言語のコードを組み立てる」ためのものであり、原稿の```` ```d2 ````フェンス内にすでにD2言語で書かれたテキストをSVG化する（レンダリングする）機能を持たず、目的に合わないと判明した。Graphvizの`diagraph`のようなTypstパッケージ（Wasm等でローカル完結する描画）が無いかもPreviewレジストリで確認した。該当は無かったため、D2公式CLIバイナリを直接使う方式に決めた。
   * **ライセンス**: D2本体はMPL-2.0（Terrastruct Inc.）。PlantUMLのjar同梱と異なり、ツールのPyPI配布物には一切含めず、ユーザーの実行時に公式GitHub Releasesから取得するだけ（ソースの再配布は行わない）。
   * **実行環境の前提**: `find_system_d2()`（`build.py`）でシステムの`d2`コマンドを検出して再利用する（2章）。PlantUMLのJavaと異なりバージョン下限のチェックは設けていない（D2側に相当する制約が無いため）。GitHub-hosted runner（`ubuntu-latest`）にはD2が標準搭載されていないため、CI上でも`plugins.d2_auto_download`（既定`true`）による自動取得が毎回発生する。ダウンロードされる実体は約13MB（Go製の単一実行ファイル、外部ランタイム不要）とPlantUMLのJRE（約49.7MB）よりさらに小さいため、既定を自動取得側にした（#22の設計議論と同じ判断基準）。
   * **実装**: D2公式のGitHub Releases（バージョン`v0.9.0`固定）から、プラットフォーム別のtar.gzアセットをURL・SHA256込みで取得・キャッシュする（OS標準のユーザーキャッシュ領域、Eclipse Temurin JREと同じプラットフォーム判定ロジック`_temurin_platform_key()`を共用）。`d2 - -`（D2公式のstdin/stdout規約。ステータスメッセージは標準エラーへ出るため標準出力のSVGと混ざらない）へ図のソースを渡し、標準出力のSVGをそのまま使う。PlantUMLと同様、図ごとにsubprocessを都度起動し、図の種別・d2のバージョン・入力テキストの複合ハッシュをキー名として`project_dir/.text-compositor/cache/`にSVG結果をキャッシュし（d2のバージョンは、システムのd2があれば`d2 --version`の出力、無ければ自動取得対象の`v0.9.0`を使う。キャッシュヒット時にバイナリの取得は起こさない。#26）、描画失敗（終了コード非0）でテキストへフォールバックせず即エラー終了する。
   * **width/height・レイアウトブロックへの組み込み**（[#82](https://github.com/tokudiro/text-compositor/issues/82)、[#77](https://github.com/tokudiro/text-compositor/issues/77)）: Mermaid/PlantUMLと全く同じ`_render_sized_image()`を共用するため、既存の`DIAGRAM_OR_IMAGE_RE`・`_render_diagram_fence()`ディスパッチャーに`d2`を加えるだけで、`layout-right`/`layout-left`/`layout-compare`/`layout-feature`のいずれでも他の図種と同列に使える。
5. **図表ソースファイルの直接指定**（[#53](https://github.com/tokudiro/text-compositor/issues/53)）: Graphviz・Mermaid・PlantUML・D2の図表ソースファイルそのものを`chapters`に直接指定できる（`.dot`/`.gv`→Graphviz、`.mmd`→Mermaid、`.puml`/`.plantuml`/`.pu`→PlantUML、`.d2`→D2。`.iuml`は`!include`で取り込む断片ファイル用の慣習であり単体の図として使われないため対象外）。**（実装済み）** 新しい描画ロジックは書かず、上記1〜4の既存の描画機構（Graphvizはテンプレート側の`show raw.where(lang: "dot")`、Mermaid/PlantUML/D2は`_render_mermaid()`/`_render_plantuml()`/`_render_d2()`）をそのまま呼び出すだけで実現している。1ファイル＝1章（見出しなし、図だけのページ）として扱われ、`plugins.*`の有効・無効判定もそれぞれの既存ロジックがそのまま適用される。

## 12. ビルド成果物と一時ファイル
* 中間 Typst ファイルは `project_dir` 直下の `.text-compositor/temp_build.typ` に生成する（Mermaidのキャッシュも同じ `.text-compositor/cache/` 配下）。テンプレートは同じ `.text-compositor/_template.typ` へコピーしてから参照する（5章・8章のサンドボックス要件）。共通の補助関数`templates/_common.typ`も、テンプレートの隣（`.text-compositor/_common.typ`）へコピーする（6章、[#63](https://github.com/tokudiro/text-compositor/issues/63)）。画像はコピーせず、`--root` 起点のルート絶対パス（`/...`）で参照して解決する。
* ビルド成功後、`temp_build.typ`・`_template.typ`・`_common.typ` は使い捨ての中間ファイルとして削除する。`cache/`（Mermaid等の描画結果）は次回以降のビルドで再利用するため削除しない。ビルド失敗時はデバッグに使えるよう `temp_build.typ` 等を残したまま終了する（[#20](https://github.com/tokudiro/text-compositor/issues/20)）。`.gitignore` への追加を推奨する。
* これらの生成物は`--clean`（出力PDF・中間ファイル）と`--clean-cache`（加えて`cache/`）で削除できる（4章、[#151](https://github.com/tokudiro/text-compositor/issues/151)）。
* 出力 PDF が既に開かれている等で書き込めない場合は、部分的な破損ファイルを残さず明確なエラーで終了する。
* **行番号マッピング**（[#27](https://github.com/tokudiro/text-compositor/issues/27)）: `document.diagnostics.line_mapping: "block"`（既定）のとき、Typstのコンパイルエラーが「Markdownの何行目に起因するか」をエラーメッセージに付記する。**（実装済み）**
  * **実装**: `TypstRenderer.render_tokens`がトップレベルのブロック（見出し・段落・引用・リスト全体・テーブル全体・hr・fence。リストの中は対象外）を出力する直前に、`// @srcmap {mdファイル}:{md行番号}`という行コメントを生成コードへ挿し込む（`_emit_srcmap`）。front-matter除去処理が既に「行数がずれないよう空行を残す」設計（7章）になっているため、`markdown-it-py`のトークンが持つ`t.map[0]`はそのまま元ファイルの行番号として使える。
  * 全チャプター結合後、`_compile_and_cleanup`が`temp_build.typ`書き出し前にこの目印行を1回スキャンし、`[(typstコード上の行番号, mdファイル, md行番号), ...]`という対応表（`_build_srcmap`）を作る。`typst_lib.TypstError`を捕捉した際、位置情報を含む`e.diagnostic`（`codespan_reporting`が整形する`┌─ temp_build.typ:12:5`形式の文字列。`str(e)`が返す`e.message`には位置情報が無く、実機確認で判明した）から`temp_build.typ:行:列`を対応表で逆引きし、`[Hint] temp_build.typ:N corresponds to around {mdファイル}:{md行}`という行を追記する（`_annotate_typst_error`）。
  * `"off"`を指定すると目印行を挿し込まず、従来どおりTypst側の生の行番号のみになる。リスト項目・テーブル行単位まで踏み込む`"fine"`は将来課題（Typstのリスト継続判定はリスト項目の物理的な列位置で決まり行コメントはトリビアとして無視される、という設計調査は済んでいる。ただし、実機検証はまだのため）。
  * **テスト**: `tests/test_line_mapping.py`（pytest。`pip install -r requirements-dev.txt`後に`pytest tests/`で実行）に、`_resolve_line_mapping`/`_build_srcmap`/`_resolve_srcmap`/`_annotate_typst_error`の単体テストと、`TypstRenderer.render()`が実際にマーカーを挿し込む統合テストを用意している。CIには未接続（ローカル実行のみ）。

## 13. FAQ（よくある疑問）

**Q. Typstコンパイラを直接使えばよいのでは？**

A. 両者はレイヤーが異なるため比較の対象にならない。Typstはタイプセッティングエンジンであり、text-compositorはそのTypstに依存する側のツールである。原稿をMarkdownで書けること、複数ファイルを`config.yaml`駆動で1冊に合成できること、書き手にレイアウトの決定権を渡さないことの3点が、Typst単体には無い価値である。詳細は[doc/diff.md](diff.md)「Typst自体との違い」を参照。

**Q. AIにMarkdownとTypst構文の両方を書かせて、以後はMarkdownだけ更新すればよいのでは？　それならこのツールは要らないのでは？**

A. 要らなくなるのではなく、このツールが解決している2つの問題がそのまま再発する。

* **非決定性**: markdown-it-pyによる変換は決定論的処理であり、同じMarkdownからは常に同じTypstコードが生成される（1章）。AIにTypstを書かせる（生成させる）と、同じMarkdownでも実行のたびに出力が変わり得る。レイアウトが実行のたびにブレる文書は、レビューをやり直すコストが際限なく発生する。
* **AIへのデザイン権限**: 「Markdownだけ更新する」運用にしても、そのMarkdownをTypstへ反映する処理自体をAIにやらせる限り、AIはレイアウト生成の立場から抜けられない。設計の核心は、レイアウトの決定権を「人間が書き・レビューするテンプレート」側に固定し、AIを内容執筆だけに限定することにある（1章「書き手からのデザイン権限の剥奪」）。

加えて、ビルドのたびにAI API呼び出しが必要になる点は、2章の「外部APIへの通信によるコンテンツ生成は一切行わない」という絶対要件に単純に反する。markdown-it-pyによる決定論的な変換は、実装上の都合による妥協ではなく、このツールの存在意義そのものである。

**Q. 見積書・請求書・申請書のような帳票（フォーム）にも使えるか？**

A. 対象外である。技術的な難しさが理由ではない。帳票は宛先欄・金額欄・印鑑欄のような固定位置の記入欄が主構造であり、「文章が連続して流れる」通常の文書とは構造が異なる。より本質的な理由は目的（1章）とのズレにある。帳票はデータをフィールドへ流し込む対象であり、AIと人間が協業して「書く」対象ではない。このツールの核心はテキスト（Model）とレイアウト（View）の分離にあり、帳票対応まで範囲を広げると、この核心が薄まる。
