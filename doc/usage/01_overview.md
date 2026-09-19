# 使い方ガイド

`text-compositor` で `config.yaml` と原稿ファイルをどう書くかをまとめた実用ガイドです。導入手順（Pythonのセットアップ等）は `README.md` を、設計の背景や決定の経緯は `spec.md` を参照してください。

このガイド自体、`text-compositor`で複数のMarkdownファイルを1冊のPDFに組み上げています（`doc/usage/` 配下）。

## config.yamlの全体像

```yaml
document:
  title: "文書タイトル"
  subtitle: "サブタイトル"
  author: "著者名"
  date: "2026-08-14"   # "auto" にすると実行日を自動で入れる
  paper_size: "a4"
  landscape: false
  cover: "template"          # template / replace / markdown / none
  cover_page_number: false   # 省略可

output:
  filename: "出力.pdf"
  dir: "."

template:
  path: "template"    # "template"・"slide"・"paper"（同梱）／独自テンプレートは .typ 拡張子で指定

plugins:
  graphviz: true
  plantuml: false
  mermaid: false

inputs:
  dir: "."

chapters:
  - "01_intro.md"
  - "02_features.md"
  - file: "03_architecture.md"
    paper_size: "a4"     # この章だけ用紙設定を上書き
  - aggregate: "testcases"
    title: "テストケース一覧"
    landscape: true
```

すべての相対パス（`chapters` のファイル、`inputs.dir`、`output.dir`、`aggregate`）は、**`config.yaml` が置かれたディレクトリ**が基準になります。`config.yaml` の置き場所はどこでもよく、ツール本体のディレクトリに合わせる必要はありません。
