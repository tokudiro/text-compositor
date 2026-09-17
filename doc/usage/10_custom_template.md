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

## conf() の必須引数

`config.yaml`の指定有無に関わらず、`build.py`は常に以下を`conf()`へ渡す。テンプレートがこれらを受け取れないと、そのテンプレートは常にビルドエラーになる。

```
conf(title:, subtitle:, author:, date:, paper_size:, landscape:,
     graphviz:, header:, footer:, paginate:, background:, logo:, doc)
```

## conf() の任意引数

以下は`config.yaml`側で明示指定したときだけ`conf()`へ渡される。未指定なら引数自体を渡さないため、テンプレートが持たなくても即座には壊れない（そのテンプレートを使う人が該当のconfig.yamlキーを使わない限り安全）。

```
conf(cover:, cover_page_number:, toc:, ...)
```

ただし、これらは「`config.yaml`があればどのテンプレートでも上書きできる」という設計原則（`doc/spec.md` 1章）の対象でもある。独自テンプレートでも、可能な限り全て受け取れるようにしておくことを推奨する。テンプレートの見た目として意味を持たない引数（例: スライド用テンプレートにとっての`toc`）は、受け取った上で何もしない（no-op）実装でよい。

同梱テンプレート間でも、これらの既定値は必ずしも揃っていない。例えば`cover_page_number`は`template.typ`（文書）が`false`、`slide.typ`（スライド）も`false`だが、これは「スライドの表紙にはページ番号を付けないのが通例」という各テンプレートのView上の判断であり、揃えるべき値と揃えなくてよい値の線引きは個別に検討する。
