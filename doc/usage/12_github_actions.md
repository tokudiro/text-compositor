# GitHub Actionsでの利用

GitHub-hosted runner（`ubuntu-latest`等）には標準でGoogle Chromeが導入されている。`plugins.mermaid: true`を使うプロジェクトでも、ビルド時に既存のChromeを自動検出して再利用するため、追加のブラウザダウンロード（設定を誤ると発生しうる約699MB）は発生しない。

本ツールの使い方は2通りあり（[README](../../README.md)参照）、どちらもGitHub Actions上で使える。

- **クローンして直接叩く**（`actions/checkout`で2回チェックアウト）: `build.py`本体をそのまま呼び出す。以下の「ワークフロー例」を参照。
- **pipインストールする**（#111）: `pip install text-compositor`（またはリリース前の最新masterを試すなら`pip install git+https://github.com/tokudiro/text-compositor.git@master`）した上で`text-compositor`コマンドを呼び出す。

```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Install text-compositor
        run: pip install text-compositor

      - name: Build PDF
        run: text-compositor --config path/to/text-compositor.config.yaml
```

GitHub-hosted runnerはMicrosoft Store版Pythonの制約（[README](../../README.md)の注意書き参照）とは無関係なので、この方式でも`pip install`だけで問題なく動く（`pipx`/`venv`によるインストール先の分離はローカルWindows環境向けの注意で、CI環境では必須ではない）。

## ワークフロー例: ツールとドキュメントを別リポジトリのまま使う（クローン方式）

3章・8章の「ツール本体とドキュメントの分離」はGitHub Actions上でも成立する。`build.py`をドキュメント側リポジトリへコピー・同梱する必要はなく、`actions/checkout@v4`を2回使い、自分のリポジトリとtext-compositorをそれぞれ別のディレクトリへチェックアウトすればよい（2回目は`repository:`パラメータでtext-compositorを指定し、`path:`で別の場所に展開する。[#24](https://github.com/tokudiro/text-compositor/issues/24)で実証済み）。これがこのツールの通常の使い方であり、ドキュメント側リポジトリには原稿と`text-compositor.config.yaml`だけを置けばよい。

```yaml
name: Build Docs

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout this repo (docs/config)
        uses: actions/checkout@v4
        with:
          path: this-repo

      - name: Checkout text-compositor (tool)
        uses: actions/checkout@v4
        with:
          repository: tokudiro/text-compositor
          path: text-compositor

      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Install dependencies
        run: pip install -r text-compositor/requirements.txt

      - name: Build PDF
        run: python text-compositor/build.py --config this-repo/path/to/text-compositor.config.yaml

      - uses: actions/upload-artifact@v4
        with:
          name: pdf
          path: this-repo/path/to/output.pdf
```

`build.py`本体やそのライセンス・バージョン管理を各ドキュメントリポジトリ側で意識する必要がない。text-compositorは公開リポジトリなので、`repository: tokudiro/text-compositor`と指定するだけで追加の認証設定（トークン等）なしにチェックアウトできる。

`plugins.graphviz`のみを使うプロジェクトは、この構成だけで完結する（Node.js/JRE等の追加インストール不要）。

## 増分ビルド（`--if-changed`）をCIで使う場合の注意

`--if-changed` は、出力PDFの更新日時を、入力・config・テンプレートと比較して、生成をスキップします。`actions/checkout` は、全ファイルの更新日時を取得した時刻にするため、`--if-changed` を付けるだけでは、CIでは常に再生成されます。出力先を `actions/cache` で復元する運用が必要です。ただし、復元したPDFの更新日時も復元した時刻になるため、`checkout` より後に復元しないと、スキップされません。実際にスキップされるかは、運用する環境での確認が必要です（本ツールでは未検証）。

## Mermaidを使う場合の注意

`plugins.mermaid: true`のプロジェクトでは、クローン方式なら`pip install playwright==1.62.0`を追加で実行する（`requirements.txt`には含まれない。任意依存のため）。pipインストール方式なら`pip install "text-compositor[mermaid]"`でまとめて入る。ブラウザは前述のとおりランナー標準搭載のChromeを再利用するため、Node.jsのインストールは不要。

```yaml
      - name: Install dependencies
        run: |
          pip install -r text-compositor/requirements.txt
          pip install playwright==1.62.0
```

Mermaid公式配布の単一バンドルJS（`mermaid.min.js`、約3.4MB）は初回ビルド時にOS標準のユーザーキャッシュディレクトリ（Linuxランナーでは`~/.cache/text-compositor/`）へダウンロードされる。`actions/checkout`は毎回新規チェックアウトのため、このキャッシュは引き継がれない。ただし、サイズが小さいため実用上は都度取得でも問題にならない。

## D2を使う場合の注意

`plugins.d2: true`（既定）のプロジェクトでは、追加の`pip install`は不要です（PlantUMLと同じくコア機能の一部）。ただしMermaid用のブラウザ・PlantUML用のJavaと異なり、GitHub-hosted runner（`ubuntu-latest`）にはD2 CLIが標準搭載されていないため、`d2`フェンス（または`.d2`直接指定）を使うプロジェクトは、ビルドのたびにD2公式CLIバイナリ（約13MB）をダウンロードします。`actions/checkout`は毎回新規チェックアウトのためキャッシュは引き継がれません。ただし、サイズが小さいため実用上は都度取得でも問題にならない点はMermaidの`mermaid.min.js`と同様です。

## リリース時にPDFをアセットとして添付する

このツール自身の使い方ガイド（本書）は、`v*`タグのpushをトリガーに、クローン方式・pipインストール方式の両方でビルドしている。クローン方式の成果物はGitHub Releaseへアセットとして添付し（上記と同じ2回チェックアウトの構成）、pipインストール方式は継続検証のみを行う（ビルドが成功することの確認、アセット添付はしない）。これによりリリースの度に、どちらの使い方も壊れていないかを継続的に検証している。設定例は `.github/workflows/release.yml` を参照。
