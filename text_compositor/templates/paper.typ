// 2段組みの論文形式テンプレート（#64）。論文・査読レポート・特許明細書のような、
// タイトルブロックを全幅で置き、本文を2段組みで流す媒体向け。単一段組みの連続する文書は
// template.typ、スライドはslide.typが担う（媒体が違うときに新テンプレートを作る、という
// 判断基準は doc/usage/10_custom_template.md を参照）。
//
// 補助関数（fit-image・render-graph・callout・render-header・render-footer・render-background）は
// template.typと同一実装のため_common.typから読み込む（#63）。
#import "_common.typ": fit-image, render-graph, callout, render-header, render-footer, render-background

#let conf(
  title: none,
  subtitle: none,
  author: none,
  date: none,
  paper_size: "a4",
  landscape: false,
  // このテンプレートでは、coverは「表紙ページ」ではなく1ページ目上部のタイトルブロック
  // （タイトル・著者・日付・abstract）の有無を指す。論文には独立した表紙ページを設けないため。
  cover: true,
  // 論文には表紙ページも目次も改版履歴も無い。conf()契約の任意引数として受け取り、何もしない（no-op）。
  cover_page_number: false,
  toc: false,
  revision_history: none,
  // 概要（document.abstract）。タイトルブロックの下に、全幅で出す。
  abstract: none,
  graphviz: true,
  header: none,
  footer: none,
  paginate: true,
  background: none,
  logo: none,
  doc,
) = {
  set text(font: "Noto Sans JP", size: 10pt)

  show raw.where(lang: "dot"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }
  show raw.where(lang: "graphviz"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }

  set page(
    paper: paper_size,
    flipped: landscape,
    margin: (x: 1.8cm, y: 2.2cm),
    columns: 2,
    header: render-header(if header != none { header } else { title }, logo),
    footer: render-footer(footer, paginate),
    background: render-background(background),
  )
  set columns(gutter: 1.4em)
  set par(justify: true, leading: 0.65em, spacing: 0.9em)

  // 論文は章ごとに改ページせず、段を続けて流す。build.pyは章の末尾ごとに弱い改ページを出すが、
  // 弱い改ページは、ページ先頭にいる場合しか無視されない。そのため、ここで無効にする。
  // 代償として、<!-- pagebreak -->による明示の改ページも効かなくなる（両者は同じコードで生成される）。
  show pagebreak: none

  // 節番号は「1」「1.1」の形式。見出しの大きさは本文に近づけ、2段組みの狭い幅を圧迫しない。
  set heading(numbering: "1.1")
  show heading.where(level: 1): it => {
    v(0.9em, weak: true)
    text(12pt, weight: "bold", it)
    v(0.5em, weak: true)
  }
  show heading: it => if it.level > 1 {
    v(0.6em, weak: true)
    text(10.5pt, weight: "bold", it)
    v(0.4em, weak: true)
  } else { it }

  // タイトルブロック: 全幅（2段にまたがる）で、1ページ目の上部に置く。
  if cover {
    place(top + center, float: true, scope: "parent", clearance: 1.6em)[
      #align(center)[
        #text(18pt, weight: "bold")[#title]
        #if subtitle != none and subtitle != "" [
          #v(0.5em)
          #text(11pt)[#subtitle]
        ]
        #if author != none and author != "" [
          #v(0.9em)
          #text(11pt)[#author]
        ]
        #if date != none and date != "" [
          #v(0.3em)
          #text(10pt)[#date]
        ]
      ]
      #if abstract != none {
        v(1em)
        pad(x: 1.2cm)[
          #set par(justify: true)
          #set align(left)
          #text(9pt)[*概要* #h(0.5em) #abstract.split("\n").join(linebreak())]
        ]
      }
    ]
  }

  doc
}
