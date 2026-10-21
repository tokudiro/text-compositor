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

`code_block`（コードブロックの背景・枠線・大きさ）も、章ごとに上書きできます。`document.code_block`に対して、キー単位で重ねます（`table_header`と同じ。書き方は、「document: 文書全体の設定」の章の「code_block」を参照）。`code_block: false`で、その章だけ、装飾をやめます。

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

### 列を設定する（`columns`）

`columns` を書くと、表の列を自由に決められます。省略すると、上の5列（ID・Title・Priority・Steps・Expected）になります。

```yaml
chapters:
  - aggregate: "results"
    title: "テスト結果"
    columns:
      - key: id
        title: ID            # 見出し。省略時は key
        width: auto          # auto / 1fr / 2fr … 省略時は 1fr
        align: center        # left / center / right。省略時は left
      - key: tested_by
        title: 実施者
      - key: actual_result
        title: 実際の結果
        width: 2fr
        markdown: true       # true のとき Markdown として描画。省略時は false
      - key: status
        title: 合否
        align: center
```

- **値の取り出し**: 各ファイルのトップレベルの `key` を、そのセルに出します。キーが無いファイルは、空欄になります。
- **`markdown: false`（既定）**: 文字をそのまま出します（Typst の特殊文字はエスケープ）。値がリストなら、読点（、）で連結します。`auto` 以外の幅の列には、長い識別子を折り返すための改行点を入れます。
- **`markdown: true`**: Markdown として描画します。値がリストなら、各要素を改行で連結します。
- **エラー**: `key` が無い、`width`・`align` が不正、`key` が重複、未知のキーがある場合は、ビルドの最初にエラーで止まります。`columns` は `aggregate:` の章だけに書けます。

### 表の文字を小さくする（`font_size`）

テストケースが多くてページ数が増えるときは、`font_size` で表の文字を小さくできます。

```yaml
chapters:
  - aggregate: "testcases"
    title: "テストケース一覧"
    font_size: 8pt        # 表と集計の文字の大きさ。省略時は本文と同じ
```

章の見出しは変わりません。書式は `8pt`・`7.5pt` のように、数値と `pt` です。それ以外の書き方は、ビルドの最初にエラーで止まります。

### テスト仕様と結果を、1つの表にする（`join`）

仕様（1テスト＝1ファイル）と結果（1回の実施＝1ファイル）を、`id` で突き合わせて、1つの表にできます。結果を実施者ごとのファイルに分ければ、並行して実施しても、Git でコンフリクトしません。

```yaml
chapters:
  - aggregate: "testcases"
    title: "テスト結果"
    columns:                       # 仕様の列
      - { key: id, title: ID, width: auto, align: center }
      - { key: title, title: 項目 }
    join:
      aggregate: "testresults"     # 結果のディレクトリ（inputs.dir 基準）
      key: id                      # 突き合わせるキー。省略時は id
      runs: latest                 # latest（既定）/ all
      missing: "未実施"             # 結果が無いテストに入れる文字列。省略時は空欄
      columns:                     # 結果の列（必須）
        - { key: tested_at, title: 実施日, width: auto }
        - { key: tested_by, title: 実施者, width: auto }
        - { key: status, title: 合否, width: auto, align: center }
```

結果のファイルは、2通りの書き方を、どちらも使えます。同じディレクトリに混ぜてもかまいません。

```yaml
# 書き方1: 1回の実施 = 1ファイル
id: T-01
tested_at: 2026-10-20
tested_by: 田中
status: NG
```

```yaml
# 書き方2: 1テスト = 1ファイル（runs に実施を並べる）
id: T-01
tested_by: 田中            # runs の外側のキーは、全回の共通値
runs:
  - { tested_at: 2026-10-20, status: NG }
  - { tested_at: 2026-10-25, status: OK }
```

書き方2は、2人が同時に追記するとコンフリクトし得ます。複数人で実施するときは、書き方1を勧めます。

- **並び順と最新**: 同じ `id` の記録は、`tested_at` の昇順に並びます。`tested_at` が無い、または同じときは、ファイル名順、`runs` 内の並び順です。最後の1件が「最新」です。
- **`runs: latest`（既定）**: テストごとに、最新の1件だけを1行で出します。
- **`runs: all`**: 実施の数だけ行を出します。仕様の列は最初の行にだけ出し、残りの行は空欄です。実施の回を区別する列（`tested_at` など）を、結果の列に入れてください。
- **結果が無いテスト**: エラーにせず、結果の列を `missing` で埋めて出します。
- **仕様が無い結果**: 警告を出し、仕様の列を空欄にして、表の最後に足します。
- **警告になるもの**: `id` が無い結果ファイル（飛ばします）、`id` と `tested_at` が同じ結果記録（重複記録の疑い）、`id` が重複する仕様。
- **エラー**: `join` に `aggregate` か `columns` が無い、`runs` が不正、未知のキーがある、結果のディレクトリが無い場合は、止まります。`join` は `aggregate:` の章だけに書けます。

`sample/` に、仕様と結果の例があります（`testcases/`・`testresults/`）。

### 集計を出す（`summary`）と、再実施の予定（`skip_missing`）

`join` の中に `summary` を書くと、表の下に、OK・NG・未実施などの件数と合格率を出します。

```yaml
    join:
      aggregate: "testresults"
      skip_missing: true            # 「未実施」と書いた記録を、最新の判定から除く（省略時 false）
      summary:                      # true だけでも書ける（全て既定値）。書かなければ集計は出ない
        position: bottom            # top（表の上）/ bottom（表の下、既定）
        title: "集計"                # 見出し。空文字にすると見出しなし
        by: status                  # 集計に使う結果側のキー。省略時 status
        order: [OK, NG, 保留]        # 列の並び順。省略時は出てきた順
        missing_label: 未実施        # 結果が無いテストの表示名
        rate: true                  # 合格率を出す（classes.pass が必要）
        classes:
          pass: [OK]
          fail: [NG]
          pending: [保留, ブロック]
          excluded: [N/A]
        group_by: priority          # 任意。仕様側のキーごとに、行を分ける
```

- **数え方**: 単位はテスト（`id`）の数です。テストごとに、最新の1件だけで数えます。再実施しても、合計は増えません。
- **結果が無いテスト**: `missing_label`（既定「未実施」）に数えます。`status: 未実施` と書いた記録も、同じ列にまとまります。`by` の値が無い結果は「（未記入）」です。仕様が無い結果は、含めません。
- **区分**: `pass`・`fail` は、合計と合格率の分母に含めます。`pending` と未実施は、合計に含め、分母には含めません。`excluded` は、合計に含めず、「対象外」の列に件数だけ出します。
- **合格率**: pass ÷ （pass＋fail）です。`75%（12/16）` のように出し、分母が0なら「-」です。
- **`skip_missing`**: 1回目が `OK`、2回目が「未実施」（再テストの予定）のとき、`false` では「未実施」になります。`true` では、2回目を除いて、`OK` のままです。表（`runs: latest`）と集計の両方に効きます。`runs: all` の表には効きません（履歴は消しません）。

### 廃止したテスト（`retired`）と、仕様の版の確認（`rev`）

```yaml
    join:
      aggregate: "testresults"
      retired: { key: status, values: [廃止], show: false }
      rev: { spec: rev, result: spec_rev, label: 要再実施 }
```

```yaml
# 仕様 T-01.yaml           # 結果 T-01_run2.yaml
id: T-01                   id: T-01
rev: 3                     spec_rev: 3    # 実施したときの、仕様の版
status: OK
```

- **`retired`**: 仕様の `status`（`key`）が `values` のどれかであるテストを、廃止とみなします。`show: false`（既定）では、表からも集計からも除きます。`true` にすると、表には行を出し、集計には含めません。廃止したテストの結果が残っていても、警告しません。
- **`rev`**: 仕様が変わったのに、結果が古いテストを見つけます。最新の結果の `spec_rev` が、仕様の `rev` と違うと、合否の欄が「要再実施」（`label`）になります。結果に `spec_rev` が無い場合も、同じです（古い結果を見逃さないため）。ビルド時に、`spec_rev` が無い結果を警告で一覧にします。仕様に `rev` が無いテストは、確認しません。
- **集計との関係**: 「要再実施」は、`classes` に書かなければ、`pending` と同じ扱い（合計に含め、合格率の分母に含めない）です。`runs: all` の表では、履歴なので、置き換えません。
- **適用の順番**: 廃止の除外 → 最新の選択（`skip_missing`）→ 版の確認（`rev`）→ 区分（`classes`）です。

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
- **設定の継承**: section には `header`/`footer`/`paginate`/`landscape`/`paper_size`/`background`/`logo`/`table_header`/`code_block` を指定でき、配下の全章に適用されます。優先順位は「章（`file:`）の指定 ＞ front-matter ＞ section ＞ `document:`」です。section の設定はその section の中だけに効き、次の section や、section の外の章には引き継がれません。
- **`heading_offset` は章にも指定できます**: `- file: "a.md"` に `heading_offset: 1` を書くと、section なしでも、その章の見出しだけを下げられます。section 配下の章に書くと、section の値より優先されます。
- **制約**: section の入れ子はできません（目次は2階層までです）。`section:` と `file:`/`aggregate:` を同じ要素には書けません。設定に誤りがあると、ビルドの最初にエラーで止まります。
- **`document.cover: replace`/`none` との関係**: 先頭の章のタイトルを表紙に置き換える（または落とす）動作は、先頭の要素が section の場合は行いません。section の見出しが先頭に出力され、配下の最初の章のタイトルもそのまま残ります。
