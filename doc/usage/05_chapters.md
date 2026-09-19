# chapters: 章の並び

`chapters` はリストで、上から順にPDFへ結合されます。各要素は4つの書き方があります。

## 1. 文字列（Markdownファイルをそのまま追加）

```yaml
chapters:
  - "01_intro.md"
```

## 2. file: （章ごとの用紙設定・ヘッダー/フッター・テーブルヘッダの上書き）

```yaml
chapters:
  - file: "03_architecture.md"
    paper_size: "a3"
    landscape: true
    header: "【第3章】設計"
    footer: "社外秘"
    paginate: false
    table_header:
      background: "#ffcccc"  # この章だけ document.table_header を上書き
```

`paper_size`/`landscape`/`header`/`footer`/`paginate` を省略すると、そのMarkdownファイルのfront-matter（次章）の値、それも無ければ `document:` のグローバル設定が使われます。`table_header` はキー単位（`bold`/`background`/`color`）で `document.table_header` を上書きします。指定しなかったキーはグローバル設定を引き継ぎます（front-matterでの上書きは非対応。「document: 文書全体の設定」の章を参照）。

`.csv`の章では、`csv_header: false`で、1行目をヘッダー行にせず、すべての行をデータ行にできます（`document.csv_header`を、この章だけ上書きします。「Markdownファイルの書き方」の章の「CSVファイル」を参照）。

`header`/`footer`/`paginate`は**その章だけ**に効き、`landscape`/`paper_size`と同様に次の章には持続しません。章を並べ替えても、設定は`chapters:`のエントリごとついてくるため、意図しないヘッダーが別の章に混入することはありません（Marpディレクティブのような「以降のページに持続する」仕組みは採用していません。[#41](https://github.com/tokudiro/text-compositor/issues/41)/[#42](https://github.com/tokudiro/text-compositor/issues/42)を参照）。

## 3. aggregate: （YAML/JSONファイル群をテーブルとして集約）

「1テストケース＝1ファイル」のようにディレクトリ内の大量のYAML/JSONファイルを、1枚のテーブルとして出力します。

```yaml
chapters:
  - aggregate: "testcases"       # inputs.dir 基準のディレクトリ名
    title: "テストケース一覧"     # 章の見出し（省略時 "Test Cases"）
    landscape: true
```

対象ディレクトリ配下の `.yaml`/`.yml`/`.json` ファイルをファイル名順に読み込み、各ファイルの `id`/`title`/`priority`/`steps`/`expected` キーをテーブルの列にします。

## 4. section: （複数の章をまとめて、目次を2階層にする）

3編構成のマニュアルのように、「編の見出し → その配下の章」という構造を作りたいときに使います。`section:` に見出しを書き、入れ子の `chapters:` に配下の章を並べます。

```yaml
chapters:
  - "00_preface.md"                # section の外に、通常の章も置ける
  - section: "保守編"               # この見出しがH1として自動で出力される
    header: "保守マニュアル"         # 配下の全章のヘッダーになる
    footer: "社外秘"
    chapters:
      - "mainte_01.md"              # Markdown内のH1は、H2として出力される
      - file: "mainte_02.md"
        header: "個別に上書き"       # 章側の指定が優先される
  - section: "点検編"
    heading_offset: 0              # 見出しをずらしたくない場合
    chapters:
      - "inspection_01.md"
```

- **見出し**: section の見出しはH1、配下の章の見出しは既定で1段下がります（Markdown内のH1がH2、H2がH3）。`heading_offset` で段数を変えられます（0〜5の整数）。目次（`document.toc: true`）は、見出しレベルに応じて「section → 章 → 節」と階層化されます。
- **設定の継承**: section には `header`/`footer`/`paginate`/`landscape`/`paper_size`/`background`/`logo`/`table_header` を指定でき、配下の全章に適用されます。優先順位は「章（`file:`）の指定 ＞ front-matter ＞ section ＞ `document:`」です。section の設定はその section の中だけに効き、次の section や、section の外の章には引き継がれません。
- **`heading_offset` は章にも指定できます**: `- file: "a.md"` に `heading_offset: 1` を書くと、section なしでも、その章の見出しだけを下げられます。section 配下の章に書くと、section の値より優先されます。
- **制約**: section の入れ子はできません（目次は2階層までです）。`section:` と `file:`/`aggregate:` を同じ要素には書けません。設定に誤りがあると、ビルドの最初にエラーで止まります。
- **`document.cover: replace`/`none` との関係**: 先頭の章のタイトルを表紙に置き換える（または落とす）動作は、先頭の要素が section の場合は行いません。section の見出しが先頭に出力され、配下の最初の章のタイトルもそのまま残ります。
