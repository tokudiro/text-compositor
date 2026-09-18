# output: 出力先

```yaml
output:
  filename: "System_Specification.pdf"
  dir: "."
```

`dir` は `config.yaml` からの相対パス（または絶対パス）。存在しなければ自動作成されます。

# template: テンプレートの指定

```yaml
template:
  path: "template"   # 同梱テンプレート「名前」で指定
```

- **`.typ` を付けない値**（例: `template`, `slide`）は同梱テンプレートの「名前」として扱われる。
  - `template`: 通常の文書向け（縦書きレポート・仕様書等）。
  - `slide`: スライド向け（横長、Marp風のH2区切り）。
- **`.typ` で終わる値**は「パス」として扱われ、`config.yaml` からの相対パス（他のパスと同じ基準）で独自テンプレートを読み込む。例:
  ```yaml
  template:
    path: "my_template.typ"          # config.yamlと同じディレクトリ
  # または
  template:
    path: "templates/custom.typ"     # サブディレクトリ配下
  ```

独自テンプレートの書き方は「独自テンプレートを使う」の章を参照してください。

# 複数PDFをまとめて出力する

`text-compositor` は「1 `config.yaml` = 1 PDF」が基本の単位です。複数のPDFが必要な場合は、`--config-list` にconfigファイルのパスを1行1件で列挙したテキストファイルを渡します。

```
# configs.txt
# 空行と「#」で始まる行は無視される
docs/manual_mainte.config.yaml
docs/manual_hidden.config.yaml
docs/manual_inspection.config.yaml
```

```bash
python build.py --config-list configs.txt
```

pipインストール方式（導入手順は`README.md`参照）の場合は、`text-compositor --config-list configs.txt`と読み替えてください。

各行の相対パスは、`configs.txt` 自身の置き場所が基準になります（他の設定ファイルの相対パス基準と同じルール）。`--config` と `--config-list` は同時に指定できません。

いずれかのPDFのビルドが失敗すると、その時点で処理を止めます（残りのconfigは実行されません）。どのconfigの処理中に失敗したかは、標準出力の `[Build] <config path>` 行で確認できます。

# 保存のたびに自動で再ビルドする

レイアウトの調整など、編集と確認を何度も繰り返すときは `--watch` を付けます。初回ビルドの後も終了せず、保存を検知して自動で再ビルドします。

```bash
python build.py --watch
```

監視するのは、configファイル、プロジェクトディレクトリ配下、`inputs.dir` 配下、`.typ` で指定した独自テンプレートです。出力先（`output.dir`）と、`.` で始まるディレクトリ・ファイルは無視します。プロジェクトディレクトリの外にある画像などを参照している場合、その変更は検知しません。

ビルドが失敗しても終了しません。エラーを表示して次の保存を待つので、修正して保存し直してください。終了は `Ctrl+C` です。`--config-list` と併用すると、変更があったconfigだけを再ビルドします。`--check-env` とは同時に指定できません。
