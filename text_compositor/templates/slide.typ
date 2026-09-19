// fit-image・render-graph・callout・render-backgroundは、template.typと同一実装のため_common.typに
// 置いている（#63）。render-header/render-footerはスライド固有の見た目のため、このファイルに持つ。
#import "_common.typ": fit-image, render-graph, callout, render-background

// 本文ページのヘッダー・フッター（#42）。template.typと同じ関数名でエクスポートし、build.py側が
// テンプレート種別を意識せず同じ呼び出し方でチャプター単位の上書きを再発行できるようにする。
// logo（#54）: template.typと同じ実装。
#let render-header(header_text, logo) = if logo != none {
  grid(
    columns: (auto, auto),
    column-gutter: 0.5em,
    align: (left + horizon, left + horizon),
    image(logo, height: 1.5em),
    text(16pt, fill: luma(100))[#header_text],
  )
} else {
  align(left)[#text(16pt, fill: luma(100))[#header_text]]
}

#let render-footer(footer_text, paginate) = {
  let page-num = align(right)[#text(16pt, fill: luma(100))[#context counter(page).display("1")]]
  if footer_text != none and paginate {
    grid(
      columns: (1fr, 1fr),
      align(left)[#text(16pt, fill: luma(100))[#footer_text]],
      page-num,
    )
  } else if footer_text != none {
    align(left)[#text(16pt, fill: luma(100))[#footer_text]]
  } else if paginate {
    page-num
  } else {
    none
  }
}

#let conf(
  title: none,
  subtitle: none,
  author: none,
  date: none,
  paper_size: "presentation-16-9",
  landscape: true,
  cover: true,
  cover_page_number: false,
  toc: false,
  // 改版履歴（#56）。スライドには意味を持たない引数のため、受け取るだけで何もしない（no-op）。
  // config.yamlに書いてもエラーにならないようにするため（doc/usage/10_custom_template.md参照）。
  revision_history: none,
  abstract: none, // 論文形式のテンプレート（paper.typ）用。ここでは受け取るだけで何も出さない（#64）
  graphviz: true,
  header: none,
  footer: none,
  paginate: true,
  background: none,
  logo: none,
  doc,
) = {
  // フォント設定（CJKフォントは build.py が取得・キャッシュした Noto Sans JP を --font-path 経由で渡す。
  // OSフォントは直接指定しない。Noto Sans JP に無いグリフはTypstが自動でシステムフォントにフォールバックする）
  set text(font: "Noto Sans JP", size: 18pt)

  // Graphviz。graphviz: false のときは既定のraw表示（素のコード表示）にフォールバックする。
  // showルール自体は常時登録する（ブロックスコープで閉じるため、ifの中で宣言すると効かなくなる）。
  // render-graph()自体はモジュールのトップレベルで定義済み（#82でwidth/height対応のため移動）。
  show raw.where(lang: "dot"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }
  show raw.where(lang: "graphviz"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }

  let page-number-footer = align(right)[#text(16pt, fill: luma(100))[#context counter(page).display("1")]]

  // 表紙（cover: false のときは出さず、Markdown側のタイトルスライドに任せる）
  // 表紙だけページ番号表示を切り替えたいので、本文とは別に一時的な set page で囲む
  // （Typstの set は現在のブロックを抜けると元に戻るため、表紙用ページ設定を本文へ漏らさず適用できる）
  if cover and title != none {
    set page(
      paper: paper_size,
      flipped: landscape,
      margin: (x: 2cm, y: 1.5cm),
      header: none,
      footer: if cover_page_number { page-number-footer } else { none }
    )
    align(center + horizon)[
      #text(44pt, weight: "bold", fill: rgb("#003366"))[#title]
      #v(2em)
      #text(28pt)[#subtitle]
      #v(3em)
      #text(20pt)[#author]
    ]
    pagebreak()
  }

  // 本文のページ設定
  set page(
    paper: paper_size,
    flipped: landscape,
    margin: (x: 2cm, y: 1.5cm),
    header: if header != none { render-header(header, logo) } else { none },
    footer: render-footer(footer, paginate),
    background: render-background(background),
  )

  // 本文の設定
  set par(justify: true, leading: 1.2em)

  // H1 (実は使用しない想定だが念のため)
  show heading.where(level: 1): it => {
    align(center)[#text(36pt, weight: "bold")[#it.body]]
    v(1.5em)
  }

  // H2をスライドタイトルとして扱う
  show heading.where(level: 2): it => {
    text(24pt, weight: "bold", fill: rgb("#003366"))[#it.body]
    v(0.5em)
    line(length: 100%, stroke: 2pt + rgb("#003366"))
    v(1em)
  }

  // ブロッククオートのスタイル
  show quote.where(block: true): it => rect(
    fill: luma(245),
    stroke: (left: 4pt + rgb("#003366")),
    inset: 1em,
    width: 100%
  )[#it.body]

  doc
}
