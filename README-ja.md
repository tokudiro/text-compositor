# text-compositor

*[English version (英語版)](README.md)*

複数のテキストファイルをそれぞれ独立した断片として扱い、1つの人間可読なPDF文書へ決定論的に組み上げる（compose）ツールです。AIが生成し人間が加筆・修正した原稿はもちろん、既存の手作成ドキュメントを持ち込んで整理・統合する用途にも使えます。

このREADMEは最短で使い始めるための要点のみを記載します。`config.yaml`や原稿の書き方を一通り知りたい場合は[使い方ガイド](doc/usage/)（`cd doc/usage && python ../../build.py` でPDF化もできます）を、詳細な設計方針・実装状況は [doc/spec.md](doc/spec.md) を参照してください。Quarto等の汎用ツールとの違いは [doc/diff.md](doc/diff.md) にまとめています。

## 特徴

- 複数のテキストファイル（章）を1冊のPDFに結合
- Markdown → [markdown-it-py](https://github.com/executablebooks/markdown-it-py) でAST化 → [Typst](https://typst.app/) 構文へ決定論的に変換 → PDF出力
- その他のテキストファイル → そのままPDF出力
- ツール本体とドキュメント（原稿）を分離し、原稿はリポジトリ外の任意の場所に置ける
- Python中心・最小限のダウンロードで完結し、外部サーバーやSaaSに依存しない（GitHub Actions上でも、Windows/Linux/macOSのローカルでも同じ手順で動く）

`chapters`に列挙するファイルは拡張子で扱いが分かれます。`.md`/`.markdown`はMarkdownとして変換し、`.yaml`/`.yml`/`.json`はシンタックスハイライト付きの等幅表示、`.dot`/`.gv`・`.mmd`・`.puml`/`.plantuml`/`.pu`・`.d2`はそれぞれGraphviz/Mermaid/PlantUML/D2の図として1章分描画し、`.csv`はTypstのテーブルとして構造化して描画し、それ以外（プレーンテキスト・コードファイル等）は素の等幅表示にします。詳細は[使い方ガイド](doc/usage/)を参照してください。

## 必要なもの

- Python 3.10以上

> **Windowsをお使いの方へ（重要）**: Microsoft Store版Pythonでは、このツールを使えません。`pipx`や`venv`を経由しても回避できません。原因は、Store版Pythonが`%LOCALAPPDATA%`への書き込みをパッケージ専用の隔離フォルダへ透過的にリダイレクトすることにあります。このリダイレクトは、Store版Pythonから作った`venv`/`pipx`環境にも引き継がれます（実機で検証済み）。その結果、ファイルがPython自身には存在するように見えても、サブプロセス経由の機能（PlantUML、Mermaid、D2）が失敗します。このツールを使う前に、[python.org](https://www.python.org/downloads/)配布版など非Store版のPythonを別途インストールしてください（`winget install Python.Python.3.12`でも入手できます）。以降の手順は、そちらのPythonで実行してください。インストール後は`text-compositor --check-env`を実行すると、環境が正しく設定されているか確認できます。

インストール・実行方法は2通りあります。

### 方法A: `pip install`（推奨）

```bash
pipx install text-compositor
```

`pipx` はツールを隔離された環境にインストールし、`text-compositor` コマンドを使えるようにします（多くのユーザーにお勧めの方法）。このツール自体を開発する場合は、コードの変更を即座に反映できる `venv` + editable install（`pip install -e .`）を使ってください。

```bash
python -m venv .venv
.venv/bin/pip install -e .        # Windowsの場合: .venv\Scripts\pip install -e .
```

### 方法B: クローンして直接実行（インストール不要）

```bash
pip install -r requirements.txt
```

Typstコンパイラ本体はバイナリを同梱せず、上記の `pip install` で入る `typst` パッケージ（PyPIのホイール）から取得します。追加のダウンロードやインストールは不要です。

### Mermaid図を使う場合（任意）

原稿の中で ` ```mermaid ` フェンスを使う場合（または`.mmd`ファイルを`chapters`に直接指定する場合）のみ必要です。方法Aの場合は`mermaid`エクストラを追加でインストールします。

```bash
pipx install "text-compositor[mermaid]"
# 既にインストール済みの場合: pipx inject text-compositor playwright==1.62.0
```

方法B（クローンして直接実行）の場合:

```bash
pip install playwright==1.62.0
```

- **システムにインストール済みのGoogle ChromeまたはMicrosoft Edge**（既定では新規ダウンロードしない。ビルド時に自動検出して再利用する）
- 上記の `playwright` パッケージ（既存ブラウザへCDP接続するために使うだけで、既定ではPlaywright自身のブラウザダウンロード機能は使わない）

Node.js/npmは不要です。ビルド時にMermaid公式配布の単一バンドルJS（`mermaid.min.js`、約3.4MB）を取得してヘッドレスブラウザに読み込ませ、SVGに変換します（バンドルJS自体はOS標準のユーザーキャッシュディレクトリ、例えばWindowsなら`%LOCALAPPDATA%\text-compositor\Cache`、Linuxなら`~/.cache/text-compositor`にキャッシュし、変換結果は `.text-compositor/cache/` にキャッシュされ、次回以降は再取得しません）。Mermaidを使わない原稿ではこれらは一切不要です。

システムにChrome/Edgeが無い場合は既定でエラー終了します。`plugins: { mermaid_auto_download: true }` にすると代わりにPlaywright自身のChromiumを自動取得しますが、**このダウンロードは約700MBあります**（プレインストールされたブラウザを使わない場合の最後の手段として用意した設定で、既定でこの量をダウンロードしてしまうことは意図的に避けています）。

### PlantUML図を使う場合（任意）

原稿の中で ` ```plantuml ` フェンスを使う場合（または`.puml`ファイルを`chapters`に直接指定する場合）、`config.yaml`側の追加設定は不要です（`plugins.plantuml`は既定`true`。追加の`pip install`も不要）。

- ローカルにJava（11以上）があればそのまま再利用します
- 無ければ既定でEclipse Temurin JRE（Adoptium配布、約49.7MB）を上記と同じユーザーキャッシュディレクトリへ自動取得・キャッシュします。`plugins: { plantuml_auto_download: false }` にすると、自動取得せずエラー終了に変えられます
- GitHub Actionsの`ubuntu-latest`にはJavaが標準搭載されているため、CI上では追加ダウンロードは発生しません

レイアウトエンジンには純Java実装の Smetana を使うため、Graphviz（`dot`）等の外部バイナリは不要です。PlantUML本体（MIT版、約17.6MB）は同じユーザーキャッシュディレクトリに、変換結果はMermaidと同じく `.text-compositor/cache/` にキャッシュされます。

### D2図を使う場合（任意）

原稿の中で ` ```d2 ` フェンスを使う場合（または`.d2`ファイルを`chapters`に直接指定する場合）、`config.yaml`側の追加設定は不要です（`plugins.d2`は既定`true`。追加の`pip install`も不要）。

- ローカルに`d2`コマンドがあればそのまま再利用します
- 無ければ既定でD2公式CLIバイナリ（Go製の単一実行ファイル、約13MB）を上記と同じユーザーキャッシュディレクトリへ自動取得・キャッシュします。`plugins: { d2_auto_download: false }` にすると、自動取得せずエラー終了に変えられます

Java（PlantUMLが使う）やブラウザ（Mermaidが使う）と異なり、GitHub Actionsの`ubuntu-latest`にはD2が標準搭載されていないため、`d2`図を使うとCI実行のたびにこの約13MBのダウンロードが発生します（このプロジェクトのワークフローは、実行間でキャッシュディレクトリを永続化していません）。

## 使い方

`pip`/`pipx`でインストールした場合（方法A）:

```bash
text-compositor --config <path/to/text-compositor.config.yaml>
```

クローンして直接実行する場合（方法B）:

```bash
python build.py --config <path/to/text-compositor.config.yaml>
```

`--config` を省略した場合は、カレントディレクトリ直下の `text-compositor.config.yaml`（または `.json`）を自動的に探します。

```bash
cd my-project/
python /path/to/text-compositor/build.py
```

`text-compositor --check-env`（または `python build.py --check-env`）を実行すると、ビルドを実行せずに環境（依存関係・Typstのバージョン・キャッシュ済みアセット・Mermaid/PlantUML/D2の前提条件）を確認できます。

設定ファイルの書き方は [sample/text-compositor.config.yaml](sample/text-compositor.config.yaml) を、`document:`/`plugins:`/front-matter/Marpディレクティブ等の詳しい説明は[使い方ガイド](doc/usage/)を参照してください。`chapters` に列挙したMarkdownファイルを順に結合してPDFを生成します。

## サンプルを試す

```bash
cd sample/
python ../build.py
```

`sample/System_Specification.pdf` が生成されます。

## 実装状況

現在実装されているのは「`--config` で指定した（または自動検出した）設定ファイルに従い、複数のファイルを1つのPDFへ結合する」というコア機能です。CLIオプションの拡張（出力先の上書きなど）は構想段階です。既知の課題・今後の予定は [GitHub Issues](https://github.com/tokudiro/text-compositor/issues) を参照してください。

## ライセンス

[MIT License](LICENSE)
