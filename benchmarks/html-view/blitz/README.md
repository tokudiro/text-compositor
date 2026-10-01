# Blitz試作（#382）

JavaScriptを使わないネイティブ描画で、ObunzuのHTML出力を表示できるかを確かめる試作である。Rust製のHTML/CSSエンジン[Blitz](https://github.com/DioxusLabs/blitz)（MIT OR Apache-2.0）を使う。Electron・WebView2の代替になるかは、未判断である。

## 使い方

```
cargo build --release
target\release\native-blitz.exe <HTMLファイル>
```

入力は、`render_html`が出力したHTMLである（例: `..\fixture\index.html`）。ツールバー・検索・再読み込みは、まだ無い。`--dark`は、OSの設定を変えずに、ダークモードで表示する（`prefers-color-scheme: dark`の確認用）。

## 試作でわかったこと

- **機能フラグ**: `blitz`は、`blitz-dom`の既定の機能を切っている。`Cargo.toml`で、`system-fonts`（無いと文字が1つも出ない）・`svg`・`woff`・`floats`を有効にしている。
- **`file://`の画像**: Blitz 0.3.0-beta.2は、Windowsで`/C:/...`というパスをそのまま開くため、ファイル参照の画像を読めない。回避として、`src/main.rs`が、`<img src="相対パス">`をデータURIに置き換えてから渡す。
- **SVGの日本語**: Mermaidの図は、`font-family`に日本語のフォントが無い。そのままだと、PCに入っている丸ゴシックなど、字形を持つ最初のフォントが選ばれる。回避として、SVGの`sans-serif`の前に`'Noto Sans JP'`を足している。
- **キー操作のスクロール**: Blitzは、文書に対するキー操作（PageDown・矢印・Space・Home・End）を持たない（キーは、フォーカスのある入力欄にだけ届く）。`src/main.rs`が、文書を包んで、キーを先に受け取り、ビューポートをスクロールする（PageDown・PageUp・矢印・Space・Shift+Space・Home・End）。`scroll_viewport_by`のyは、正の値で上へ動く（Blitzの規約）。
- **ダークモード**: 起動後にテーマを切り替えると、Blitzの再スタイルが一部の要素に及ばず、暗い背景に暗い文字が残る（OSのテーマを、実行中に切り替えたときも、同じ症状が出る可能性がある。未確認）。`--dark`は、ウィンドウの作成時にテーマを指定して、最初から暗いスタイルで描画する。
- **`filter`・`mix-blend-mode`**: Blitzは、どちらも描かない。生成HTMLは、ダークモードで画像に`filter: invert(1) hue-rotate(180deg)`を使うため、そのままだと、図の暗い文字・矢印が、暗い背景に載って読めない。回避として、`--dark`のとき、`src/main.rs`が、同じ計算（反転して、色相を180度回す）を、SVGの色の値（`#rgb`・`#rrggbb`・`rgb()`・`rgba()`・`white`・`black`）に、読み込み前に適用する。`mix-blend-mode: lighten`が背景を溶かす効果は、純白の色を、ページの背景色（`#0d1117`）にして、まねている。白い背景を足す案は、見栄えが悪いため、採らなかった。ラスター画像（PNG等）は、変換しない。ダークモードかどうかは、`--dark`で決める（OSのダークモードの自動検出は、まだ無い）。
- **ネットワーク**: `data:`のURLだけを読む（`DataUriNetProvider`）。外部のURLは、読まない（文書を開くだけで通信が起きない、という方針に合う）。
- **図**: Mermaid等を、JavaScriptで描く方式は使えない。Python側で事前にSVGへ変換したもの（`<img src="*.svg">`）は、表示できる。

## 表示の確認（2026-10-01）

使い方ガイドなどの実際の文書を、`render_html`でHTMLにして、表示を目で確認した（`shot.ps1`で撮ったスクリーンショット）。

| 確認した文書 | 結果 |
| --- | --- |
| `doc/usage/06_markdown_basics.md`（表・コード・入れ子のリスト・日本語） | 崩れなし。表の罫線・コードの背景・等幅フォントも、期待どおり |
| `doc/usage/08_diagrams.md`（バッジ・リンク・長い表） | 崩れなし。バッジの色・リンクの色も描ける |
| `doc/usage/14_gallery_mermaid.md`（Mermaidの図が16枚） | 図は描ける。シーケンス図・クラス図・フローチャートの日本語も、読める |
| `doc/usage/23_gallery_vega.md`（Vega-Liteの図） | 描ける（回転した軸ラベル・凡例も） |

- **スクロール**: マウスホイールは動く。キー操作は、上の「キー操作のスクロール」のとおり、自前で足した（`shot.ps1 -PageDowns N`で確認）。
- **ダークモード**: `--dark`で、本文・表・コードは、期待どおりに描ける。図は、SVGの色を変換して、暗い背景になじむ（上の「`filter`・`mix-blend-mode`」）。`shot.ps1 -Dark`で撮れる。
- **`shot.ps1 -Wheel N`**: N目盛り、ホイールで下へスクロールしてから撮る。

## 計測

`measure.ps1`は、「ウィンドウが出るまで」と「本文の文字が見えるまで」を、画面のキャプチャで測る。

```
pwsh -File measure.ps1 -Html <HTMLファイル> -IdleSeconds 180 -Label idle-3min
```

`shot.ps1`は、ウィンドウのスクリーンショットを撮る。結果は、`measure-results.csv`に追記される（追跡しない）。

| 条件 | ウィンドウ | 文字が見える |
| --- | --- | --- |
| 温まった状態（3回） | 393〜437 ms | 405〜483 ms |
| 3分放置後（1回） | 466 ms | 514 ms |

- 1台のPCでの、少数回の計測である。傾向の目安として読む。
- 同じ条件のElectron・WebView2は、3分放置後にウィンドウが447〜861 msだった（#372のコメントの計測と同じ手順）。
- 「放置で大きく遅くなる」傾向は、この試作では、見えていない。ただし、試作の実行ファイルは、ビルドしたままの未署名で、書き換えていない。
