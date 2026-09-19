# document: 文書全体の設定

| キー | 説明 | 既定値 |
| --- | --- | --- |
| `title` | 文書タイトル。表紙と本文ページのヘッダーに使われる | `"Untitled"` |
| `subtitle` | サブタイトル。表紙のみ | `""` |
| `author` | 著者名。表紙のみ | `""` |
| `date` | 日付。`"auto"` を指定すると実行日（`YYYY-MM-DD`）が自動で入る | `""` |
| `paper_size` | 用紙サイズ（`a4`, `a3`, `presentation-16-9` 等、Typstが認識する値） | `"a4"` |
| `landscape` | 横向きにするか | `false` |
| `cover` | 表紙の扱い（下記） | `"none"` |
| `cover_page_number` | 表紙にページ番号を出すか | `false` |
| `toc` | 目次を出すか | `false` |
| `revision_history` | 改版履歴のページ（表紙と目次の間）に載せる一覧（下記） | なし（ページを出さない） |
| `abstract` | 概要（`paper`テンプレートのタイトルブロックに出す。下記） | なし |
| `header` | 本文ページのヘッダーに表示する文字列（下記） | `title`と同じ |
| `logo` | 本文ページのヘッダー左に表示するロゴ画像（下記） | なし |
| `footer` | 本文ページのフッターに表示する文字列（下記） | なし（ページ番号のみ） |
| `paginate` | 本文ページにページ番号を表示するか（下記） | `true` |
| `background` | 本文ページの背景画像（下記） | なし |
| `table_header` | 通常のMarkdownテーブルのヘッダ行スタイル（下記） | 無装飾 |
| `glossary` | `[[用語]]`による巻末用語索引を生成するか（「Markdownファイルの書き方」の章を参照） | `false` |
| `marp_compat` | `---`/`***`/`___`をMarp互換で改ページとして扱うか（「Markdownファイルの書き方」の章を参照） | `false` |
| `csv_header` | `.csv`の章の1行目を、ヘッダー行にするか。`false`なら、すべての行がデータ行（「Markdownファイルの書き方」の章の「CSVファイル」を参照）。`chapters[]`ごとに上書きできます | `true` |
| `diagnostics.line_mapping` | Typstコンパイルエラーの行番号をMarkdownの行番号へ対応付ける精度（下記） | `"block"` |

## 用途別の設定早見表

`templates/template.typ`は、ほぼ万能テンプレートです（[独自テンプレートを使う](10_custom_template.md)「いつ新しいテンプレートが要るか」を参照）。文書の種類ごとに、`document:`側の設定だけで大抵まかなえます。

| 用途 | 設定 |
| --- | --- |
| 仕様書（表紙・目次あり） | `cover: template` / `toc: true` |
| 軽量メモ（表紙・目次なし、要点だけ） | 何も指定しない（既定のまま） |
| テストケースの集約表 | `chapters`に`aggregate:`を指定（「chapters: 章の並び」の章を参照） |
| 論文・査読レポート（2段組み） | `template.path: paper` / `cover: template` / `abstract`（下記「paper: 2段組みの論文形式」） |
| マニュアル（注意書きを目立たせたい） | 本文中で`> [!NOTE]`等のalert記法を使う（「Markdownファイルの書き方」の章を参照）。`document:`側の追加設定は不要 |

### 軽量メモの例

`cover`/`toc`とも既定が「出さない」なので、何も指定しなければ表紙・目次なしの軽量メモになります。

```yaml
document:
  title: "週次ミーティングメモ"
  date: "auto"
```

```yaml
chapters:
  - "memo.md"
```

これだけで、1ページ目から本文がそのまま始まる短い文書が生成されます。表紙・目次が要らない用途（メモ・議事録・簡単な報告書等）に向いています。

## header / footer / paginate: 本文ページのヘッダー・フッター

```yaml
document:
  header: "システム仕様書"   # 省略時はdocument.titleが使われる
  footer: "社外秘"           # 省略時はページ番号のみ
  paginate: true             # falseにするとページ番号を出さない
```

`chapters`側で章ごとに上書きできます（`landscape`/`paper_size`と同じ優先順位パターン。「chapters: 章の並び」の章を参照）。フッターにカスタム文字列とページ番号を両方指定した場合は、左にフッター文字列・右にページ番号が並びます。この設定はMarpの`header`/`footer`/`paginate`ディレクティブとは無関係です（[#42](https://github.com/tokudiro/text-compositor/issues/42)。ディレクティブは「Markdownの書き方」の章を参照）。

## logo: ヘッダーのロゴ画像

本文ページのヘッダー左側にロゴ画像を出せます（右側の`header`文字列と併記されます）。

```yaml
document:
  logo: "logo.png"   # config.yamlからの相対パス
```

`chapters`側で章ごとに上書き・解除（`logo: null`）できます（`header`/`footer`/`background`と同じ優先順位パターン）。表紙・目次には出ません（本文ページのみ）。

コピーライト表記（`© 2026 Your Company`のような文言）に画像は不要です。既存の`footer`にそのまま書けます。

**推奨サイズ**: 表示高さは約1.2em（本文10.5ptに対して約12〜13pt相当）に固定され、元画像の解像度は表示サイズに影響しません（2000px四方の画像でも同じ高さに縮小されます）。ただし**縦横比**はそのまま反映されるため、正方形に近いアイコン風のロゴを推奨します。横長のワードマーク（会社名だけの横長画像等）は、ヘッダー幅を大きく占有する帯状の表示になるため避けてください。

```yaml
document:
  footer: "© 2026 Your Company"
```

## background: 背景画像

本文ページ全体に、透かしや地紋のような背景画像を敷けます。

```yaml
document:
  background: "watermark.png"   # config.yamlからの相対パス
```

`chapters`側で章ごとに上書きできます（`header`/`footer`/`paginate`と同じ優先順位パターン。`background: null`を指定すると、その章だけ背景を外せます）。front-matter経由での上書きは非対応です（パス値のため、`table_header`と同じ理由）。

画像はページ全面に敷かれ、本文はその上に通常どおりレイアウトされます。透明度の自動調整は行わないため、本文が読みにくくならないよう、あらかじめ薄い・低コントラストな画像を用意してください。ファイルサイズが大きいとPDFの出力サイズにも影響します。

## table_header: テーブルヘッダのスタイル

通常のMarkdownテーブル（` | a | b | `構文）のヘッダ行に、太字・背景色・文字色を指定できます（`chapters`側で章ごとに上書きも可能。「chapters: 章の並び」の章を参照）。未指定のキーは装飾なし（従来どおり）です。

```yaml
document:
  table_header:
    bold: true            # 既定 false
    background: "#eeeeee" # 既定 none（Typstのrgb()に渡せる形式。#rrggbb等）
    color: "#333333"      # 既定 none
```

なお、aggregate（YAML/JSONテストケース集約）テーブルのヘッダは対象外です（別途固定スタイルが適用されます）。

## toc: 目次の表示/非表示

既定では目次を出しません。出したい場合は明示的に指定します。

```yaml
document:
  toc: true   # 目次を出す
```

指定すると目次のページ（見出し・ローマ数字のページ番号）が追加されます。本文のページ番号は目次の有無に関わらず1から始まります。

## revision_history: 改版履歴のページ

版数・日付・改版内容の一覧を、表紙と目次の間に独立した1ページとして挿入します。

```yaml
document:
  cover: template
  toc: true
  revision_history:
    - version: "1.0"
      date: "2026-08-01"
      description: "初版"
      author: "田中"          # 担当。どの行にも書かなければ、担当の列は出ません
    - version: "1.1"
      date: "2026-09-10"
      description: |          # 複数行も書けます
        第3章を追加
        誤記の修正
```

- `revision_history` を書いたときだけ、ページが挿入されます。書かない（または空のリスト）場合は、従来どおり何も出ません。
- 各行に書けるキーは `version`/`date`/`description`/`author` です。すべて省略可能で、その列は空欄になります。1行に少なくとも1つは値が必要です。綴りミスなど、これ以外のキーはエラーになります。
- 値は文字列として表示され、`#` や `*` などのMarkdown・Typstの記法として解釈されません。`1.10` のような版数は、YAMLで数値 `1.1` として読まれるため、引用符で囲んでください。`date: 2026-08-01` のようにYAMLの日付として書いても、そのまま表示されます。
- 行は書いた順に並びます。新しい版を先頭に置くか末尾に置くかは、運用に合わせて決めてください。
- ページ番号は目次と同じローマ数字（i, ii, …）で、目次へ続きます（改版履歴が i、目次が ii）。本文は、これまでどおり1から始まります。
- 同梱の `slide.typ`（スライド用テンプレート）では、この設定は何も出力しません（エラーにもなりません）。独自テンプレートで使う場合は、「独自テンプレートを使う」の章を参照してください。
- 版数の値を本文の `{{VERSION}}` と揃えたい場合は、現状は両方に同じ値を書いてください（`variables:` は `document:` の値には適用されません）。

## paper: 2段組みの論文形式

`template.path: paper` を指定すると、論文・査読レポート向けの2段組みで出力します（[#64](https://github.com/tokudiro/text-compositor/issues/64)）。完全な例は、リポジトリの `sample/paper/` です。

```yaml
document:
  title: "Markdownから2段組みPDFを作る"
  subtitle: ""       # 未指定だと、既定値の「自動生成ドキュメント」が出る。空文字で消す
  author: "text-compositor"
  date: "2026-09-19"
  cover: template    # paperでは、1ページ目上部のタイトルブロックを出す（下記）
  abstract: |
    Markdownの原稿を、2段組みのPDFへ変換するテンプレートを示す。
template:
  path: "paper"
```

- **タイトルブロック**: `cover` は、表紙ページではなく、1ページ目の上部にある全幅のブロック（タイトル・副題・著者・日付・概要）の有無を指します。論文には独立した表紙ページを設けません。`cover` の既定は `none` で、このときはタイトルブロックが出ず、先頭章のH1も落ちます。`cover: template` を指定してください。
- **`abstract`**: タイトルブロックの下に「概要」として出す文字列です。複数行も書けます。値は文字列として表示され、`#` や `*` などのMarkdown・Typstの記法として解釈されません。文字列以外を書くとエラーになります。`paper` 以外の同梱テンプレートは、この設定を何も出力しません（エラーにもなりません）。
- **見出し**: `1`、`1.1` の形式で自動的に番号が付きます。
- **章ごとの改ページはしません**: 本文は、章をまたいで段を続けて流れます。ただし、`<!-- pagebreak -->` による明示の改ページも効きません。
- **`toc`・`cover_page_number`・`revision_history`**: 論文には目次・表紙ページ・改版履歴がないため、受け取って何も出力しません。
- **段幅の制約**: 段幅より広い表やコードは、折り返されるか、はみ出します。画像と図（Graphviz・Mermaid等）は、段幅に収まるよう自動的に縮小されます。
- **範囲外**: 参考文献・引用（Typstの `bibliography()` との連携）は、現状は対応していません。

## diagnostics.line_mapping: エラー行のMarkdownへの対応付け

Typstのコンパイルに失敗すると、既定では`temp_build.typ:42:3`のようにビルド用の中間ファイル（生成されたTypstコード）の行番号でエラーが表示され、元のMarkdownの何行目が原因か分かりにくい問題があります。この設定で、失敗時のメッセージに元のMarkdownファイル・行番号のヒントを追加できます（[#27](https://github.com/tokudiro/text-compositor/issues/27)）。

```yaml
document:
  diagnostics:
    line_mapping: "block"   # 既定
```

- `"block"`（既定）: 見出し・段落・リスト全体・テーブル全体・区切り線・コードフェンス単位で対応付けます。リスト項目やテーブルのセル単位までは特定できません。
- `"off"`: 対応付けを行わず、従来どおりTypst側の生の行番号のみを表示します。

`"block"`は生成コードに目印となる行コメントを挿し込むため、コンパイル失敗時に温存される中間ファイル（`temp_build.typ`）を直接デバッグする際にも、どのコメント行がどのMarkdown行に対応するか目視で追えます。

## cover の4つのモード

Marp形式（先頭に `# タイトル` `## サブタイトル` のスライド）で書かれた原稿と共用する場合に関係します。既定では表紙を出しません。

- `template`: テンプレートの表紙だけを出す。Markdown側はそのまま。
- `replace`: テンプレートの表紙を出し、Markdown先頭のタイトルスライド（H1+H2）を取り除く。Marpと共用の原稿で二重表紙を避けたいときに推奨。
- `markdown`: テンプレートの表紙を出さず、Markdown先頭のスライドをそのまま表紙にする。
- `none`（既定）: どちらの表紙も出さない。
