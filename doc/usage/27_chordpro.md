# コード譜（ChordPro）

ChordProは、歌詞の途中に`[C]`のようにコードを書く、テキスト形式のコード譜です。Markdownの` ```chordpro `フェンスと、単体ファイル（`.cho`・`.chordpro`・`.pro`）の両方で使えます。外部ツールは要りません。

## 書き方

コードは、歌詞の中の、鳴らす位置に`[コード]`と書きます。表示では、コードが、直後の歌詞の真上に出ます。

```chordpro
{title: Amazing Grace}
{subtitle: Traditional}
{start_of_verse: 1番}
[G]Amazing [G7]grace, how [C]sweet the [G]sound
That saved a [Em]wretch like [D]me
{end_of_verse}
```

日本語の歌詞も、同じ書き方です。

```chordpro
{title: 蛍の光}
{sov: 1番}
[C]ほたるの[F]ひかり[C]まどの[G]ゆき
[C]ふみよむ[F]つきひ[C]かさねつ[G]つ
{eov}
{soc: サビ}
[Am]いつしか[Dm]としも[G7]すぎのとを
{eoc}
```

## 対応する指令

| 指令（別名） | 働き |
|---|---|
| `title`（`t`）・`subtitle`（`st`）・`artist` | 題名・副題・アーティスト名 |
| `comment`（`c`）・`comment_italic`（`ci`）・`comment_box`（`cb`） | 注記の行（通常・斜体・枠つき） |
| `start_of_verse`（`sov`）・`end_of_verse`（`eov`） | 歌詞の区間。`{sov: 1番}`のように、名前を付けられます |
| `start_of_chorus`（`soc`）・`end_of_chorus`（`eoc`） | コーラスの区間。左に線が付きます |
| `start_of_bridge`（`sob`）・`end_of_bridge`（`eob`） | ブリッジの区間 |
| `start_of_tab`（`sot`）・`end_of_tab`（`eot`） | タブ譜の区間。中身は、コードとして読まず、等幅のまま出します |

- 行頭が`#`の行は、コメントとして捨てます。
- `[*Coda]`のように、先頭に`*`を付けると、コードではなく注記として、斜体で出ます。
- 対応していない指令（`transpose`・`define`など）は、表示から外し、警告を出します。書いたものが、黙って消えたことに気づけるようにするためです。

## 単体ファイルとして使う

`.cho`・`.chordpro`・`.pro`は、`chapters`に直接指定できます（1ファイル＝1章）。Viewerでも、そのまま開けます。`title`は、Viewerではページの題名にもなります。

```yaml
chapters:
  - file: "song.cho"
    header: "蛍の光"
```

## 無効にする

`plugins`で`chordpro: false`にすると、フェンスと単体ファイルを、素のコードのまま表示します（既定は`true`）。

## 見た目について

コードと歌詞は、「コード＋直後の歌詞の断片」を1組にして、縦に積んでいます。等幅フォントの桁揃えには頼りません。そのため、日本語の歌詞でも、フォントが何であっても、コードは歌詞の真上に揃います。コードが歌詞の断片より長いときは、断片の幅をコードに合わせて広げます。行が長いときは、組の境目で折り返します。
