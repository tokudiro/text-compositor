# 独自テンプレートを使う

## いつ新しいテンプレートが要るか

`templates/template.typ`は、ほぼ万能テンプレートである。仕様書・マニュアル・軽量メモ・テスト仕様書は、いずれもこの1つでカバーできる。文書の「ジャンル」が違っても、レイアウト自体は同じ「本文が連続して流れる文書」だからである。ジャンルごとの違いは、大抵は機能（`aggregate`によるテスト仕様書のテーブル化、callout記法によるマニュアルの注意書き等）か、`config.yaml`側の設定（`cover`/`toc`のオン・オフ等）で吸収できる。

新しいテンプレートが要るのは、ジャンルではなく**媒体そのものが違う**ときである。`templates/slide.typ`が別テンプレートである理由は「スライド用だから」ではなく、「本文が連続して流れる文書ではなく、1枚1枚が独立したページで、縦横比も表示規約も別物だから」である。新しいテンプレートを作る前に、「これは違う媒体か、それとも既存テンプレートに機能か設定を足せば済む話か」を先に検討すること。

`template.path` に `.typ` で終わるパスを指定すると、自分で書いたTypstテンプレートを使えます（「template: テンプレートの指定」の章）。テンプレートは以下の関数をエクスポートする必要があります。

- `conf(...)`: 文書全体の骨格（表紙・目次・本文ページの設定）。引数は「必須」と「任意」の2種類に分かれる（下記）。
- `fit-image(path)`: 画像を1枚受け取り、はみ出さないよう自動縮小して配置する。
- `render-graph(code, width: none, height: none)`: Graphviz（`dot`/`graphviz`フェンス）のソースコードを1つ受け取り描画する。`width`/`height`がいずれも`none`（未指定）ならページ幅を超えたときだけ自動縮小し、明示指定時はそのまま反映する（[図表（Mermaid / Graphviz / PlantUML / D2）](08_diagrams.md)の`{width=...}`構文、#82）。同梱テンプレートは[diagraph](https://typst.app/universe/package/diagraph)（`@preview/diagraph:0.3.7`）に委譲する実装になっている。
- `callout(kind: "note", body)`: alert記法（`> [!NOTE]`等、[Markdownファイルの書き方](06_markdown_basics.md)を参照）が生成する呼び出し先。`kind`は`"note"`/`"tip"`/`"important"`/`"warning"`/`"caution"`のいずれか。同梱テンプレートは[note-me](https://github.com/FlandiaYingman/note-me)（MIT、`@preview/note-me:0.6.0`）に委譲する実装になっている。
- `render-background(path)`: `document.background`/`chapters[].background`（下記）が渡す画像パス（または`none`）を受け取り、ページ背景として敷くコンテンツを返す。
- `render-header(header_text, logo)`: `chapters[]`単位の上書き（下記）のたびに`build.py`が呼び出す。`logo`は`document.logo`/`chapters[].logo`が渡す画像パス（または`none`）。
- `render-footer(footer_text, paginate)`: `render-header`と同様、`chapters[]`単位の上書きのたびに呼び出される。

同梱の `templates/template.typ` をコピーして書き換えるのが早道です。

## 補助関数を `_common.typ` から取り込む

上記のうち `fit-image`・`render-graph`・`callout`・`render-header`・`render-footer`・`render-background` の実装は、同梱の `templates/_common.typ` にあります。`build.py` は、テンプレートをコピーするたびに、その隣へ `_common.typ` もコピーします。独自テンプレートは、相対パスで読み込めば、これらを自前で書かずに済みます。

```typst
#import "_common.typ": fit-image, render-graph, render-header, render-footer, render-background, callout
```

`render-header`/`render-footer` は、同梱の `template.typ`（文書）と同じ既定の実装です。見た目を変えたいときは、読み込まずに自分で定義してください（同梱の `slide.typ` がそうしています）。`_common.typ` を読み込まない従来の独自テンプレートは、そのまま動きます。

## Typst Universeのテンプレートを使う

[Typst Universe](https://typst.app/universe)のテンプレートは、それぞれ独自の引数を持つため、`template.path` に直接パッケージ名は指定できません。代わりに、Universeのテンプレートを包む**アダプタ**（`.typ`）を書き、`template.path` に指定します。アダプタの仕事は次の2つです。

1. 上記の補助関数をエクスポートする。`_common.typ` から読み込めば、1行で済みます。
2. `conf()` の引数を、Universeのテンプレートの引数へ翻訳する。

```typst
#import "_common.typ": fit-image, render-graph, render-header, render-footer, render-background, callout
#import "@preview/ilm:2.1.1": ilm

#let conf(
  title: none, subtitle: none, author: none, date: none,
  paper_size: "a4", landscape: false, cover: true, cover_page_number: false,
  toc: false, revision_history: none, graphviz: true,
  header: none, footer: none, paginate: true, background: none, logo: none,
  doc,
) = {
  set text(font: "Noto Sans JP")  // 日本語のフォントは、本ツールが取得したNoto Sans JPを使う
  show: ilm.with(
    title: title,
    authors: author,
    paper-size: paper_size,
    cover-page: if cover { "use-ilm-default" } else { none },
    table-of-contents: if toc { outline() } else { none },
  )
  doc
}
```

完全な例は、リポジトリの `sample/universe-ilm/`（`ilm-adapter.typ` と設定ファイル）です。次の点に注意してください。

- **バージョンを固定する**: `@preview/ilm:2.1.1` のように、アダプタの中にバージョンまで書きます。設定ファイルには書きません。パッケージが要求するTypstのバージョンが、本ツールが固定しているTypstより新しいと、コンパイルエラーになります。
- **`document.cover: template` を指定する**: `document.cover` の既定は `none` です。`none` のままだと、テンプレートの表紙が出ず、先頭章のH1も落ちます（[document: 文書全体の設定](02_document.md)）。
- **`conf()` の必須引数は、使わなくても受け取る**: 受け取れないと、常にビルドエラーになります。Universeのテンプレートが対応しない引数（例: `header`・`logo`・`background`）は、受け取って無視します。
- **`date` は文字列で渡る**: `datetime` を要求するテンプレートには、アダプタで変換します（サンプルの `to-datetime`）。
- **ネットワークが要る**: パッケージは初回のビルド時に、Typstが取得してキャッシュします。オフライン環境では、事前にキャッシュしてください。
- **ライセンス**: `@preview` の記法で参照する限り、テンプレートのコードは本ツールにも利用者のリポジトリにも含まれません。テンプレートのコードをコピーして同梱する場合は、コピー元のライセンスを確認してください。

## conf() の必須引数

`config.yaml`の指定有無に関わらず、`build.py`は常に以下を`conf()`へ渡す。テンプレートがこれらを受け取れないと、そのテンプレートは常にビルドエラーになる。

```
conf(title:, subtitle:, author:, date:, paper_size:, landscape:,
     graphviz:, header:, footer:, paginate:, background:, logo:, doc)
```

## conf() の任意引数

以下は`config.yaml`側で明示指定したときだけ`conf()`へ渡される。未指定なら引数自体を渡さないため、テンプレートが持たなくても即座には壊れない（そのテンプレートを使う人が該当のconfig.yamlキーを使わない限り安全）。

```
conf(cover:, cover_page_number:, toc:, revision_history:, abstract:, ...)
```

`revision_history`（改版履歴、[#56](https://github.com/tokudiro/text-compositor/issues/56)）は、`(version:, date:, description:, author:)`という辞書の配列で渡される。値はいずれも文字列で、省略された項目は空文字である。`description`内の改行は、文字列中の`\n`として渡されるため、表示するテンプレートが`split("\n")`等で改行に変換する。`config.yaml`に書かれなければ引数自体が渡されないので、この引数を持たない既存の独自テンプレートは影響を受けない。

`abstract`（概要、[#64](https://github.com/tokudiro/text-compositor/issues/64)）は、`document.abstract` の文字列です。改行は、文字列中の`\n`として渡されるため、表示するテンプレートが`split("\n")`等で改行に変換します。同梱では `paper.typ` だけが表示し、`template.typ`・`slide.typ` は受け取って何も出しません。

ただし、これらは「`config.yaml`があればどのテンプレートでも上書きできる」という設計原則（`doc/spec.md` 1章）の対象でもある。独自テンプレートでも、可能な限り全て受け取れるようにしておくことを推奨する。テンプレートの見た目として意味を持たない引数（例: スライド用テンプレートにとっての`toc`）は、受け取った上で何もしない（no-op）実装でよい。

同梱テンプレート間でも、これらの既定値は必ずしも揃っていない。例えば`cover_page_number`は`template.typ`（文書）が`false`、`slide.typ`（スライド）も`false`である。これは「スライドの表紙にはページ番号を付けないのが通例」という各テンプレートのView上の判断であり、揃えるべき値と揃えなくてよい値の線引きは個別に検討する。
