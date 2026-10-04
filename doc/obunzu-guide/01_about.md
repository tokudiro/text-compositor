# Obunzuとは

Obunzu Markdown Viewer（略称はObunzu。お文図。「おぶんず」と読みます）は、Markdownと図を、すばやく表示する、閲覧専用のViewerです。名前は、Observe（観察する）と、文図（ぶんず。文章と図）を合わせた造語です。

![Obunzuで、文書を開いたところ|width=100%](images/main-light.png)

## できること

- Markdownファイル（`.md`）を開いて、見やすく表示します。表・タスクリスト・注記（`> [!NOTE]`）・画像・数式（LaTeX記法）も表示します。コードブロックは、色分けします。
- 文書の中に、コードとして書いた図を、絵にして表示します。Mermaid・PlantUML・D2・Structurizr・Graphviz・Pikchr・CeTZ・Fletcher・timeliney・finite・Vega-Lite・Vega・WaveDrom・Bytefield・SVGに対応します（「図を書く」の章）。
- 図の単体ファイル（`.mmd`・`.puml`・`.d2`・`.dot`・`.pikchr`など）・テキスト（`.txt`）・CSV（`.csv`）・SVG（`.svg`）も開けます。
- ファイルを保存すると、表示が自動で更新されます。お使いのエディタで書きながら、Obunzuで見た目を確かめる使い方ができます。
- 変換に失敗したときは、原稿の何行目で、何が起きたかを、画面に示します。
- ライトとダークの配色に対応します。

## できないこと

- 文書の編集はできません（閲覧専用です）。書くときは、お使いのエディタを使ってください。
- PDFの出力はできません。PDFにするときは、同じ仕組みの[text-compositor](https://github.com/tokudiro/text-compositor)を使います。Obunzuの図は、text-compositorが作るPDFと、同じ描き方で描くため、同じ図になります。
- 生のHTMLには、対応していません。無視して、警告を出します。
- Windows（64ビット）向けです。Mac・Linux向けの配布物は、ありません。

## この説明書について

この説明書は、Obunzuを使う人向けです。Obunzu自体を開発する人向けの情報（ソースからの実行・構成・テスト）は、`viewer/README-ja.md`にあります。Markdownの書き方（見出し・表・図・サイズ指定など）の詳細は、text-compositorの「使い方ガイド」にあります。

説明書は、Obunzu 0.4.4を基準に書いています。
