// 補助関数（fit-image・render-graph・callout・render-header・render-footer・render-background）は
// _common.typへ切り出した（#63）。build.pyが生成するコードはこのモジュールからも
// 同じ名前でimportするため、ここで読み込むだけで（再エクスポートされて）そのまま使える。
#import "_common.typ": fit-image, render-graph, callout, render-header, render-footer, render-background

#let conf(
  title: none,
  subtitle: none,
  author: none,
  date: none,
  paper_size: "a4",
  landscape: false,
  cover: true,
  cover_page_number: false,
  toc: false,
  revision_history: none,
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
  set text(font: "Noto Sans JP", size: 10.5pt)

  // プラグイン: Graphviz (dot) 自動レンダリングと、はみ出し防止の自動縮小
  // graphviz: false のときは既定のraw表示（素のコード表示）にフォールバックする。
  // showルール自体は常時登録する（ifブロックの中で宣言すると、ブロックを抜けた
  // doc側には効かなくなる。show/setはブロックスコープで閉じるため）。
  // render-graph()自体はモジュールのトップレベルで定義済み（#82でwidth/height対応のため移動）。
  show raw.where(lang: "dot"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }
  show raw.where(lang: "graphviz"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }

  // -------------------------
  // 1. 表紙 (Cover Page) : cover: false のときは省略する
  // -------------------------
  if cover {
    set page(
      paper: "a4", flipped: false, margin: 2.5cm, header: none,
      footer: if cover_page_number { align(center)[#text(10pt)[#context counter(page).display("1")]] } else { none }
    )

    align(center + horizon)[
      #text(24pt, weight: "bold")[#title]
      #v(3em)
      #text(14pt)[#subtitle]
      #v(4em)
      #text(12pt)[#author]
      #v(1em)
      #text(12pt)[#date]
    ]
    pagebreak()
  }

  // -------------------------
  // 1.5. 改版履歴 (Revision History) : revision_history: none のときは省略する（#56）
  //   表紙と目次の間に、独立した1ページとして挿入する。revision_historyは
  //   (version:, date:, description:, author:) の辞書の配列（値はいずれも文字列。build.pyが
  //   document.revision_historyから生成する）。担当（author）列は、1件でも値があるときだけ出す。
  //   descriptionの改行は、文字列中の\nをlinebreak()へ変換して表現する。
  //   ページ番号は目次と同じローマ数字で、目次へ続ける（下の目次側でリセットしない）。
  // -------------------------
  if revision_history != none {
    set page(
      paper: paper_size,
      flipped: landscape,
      margin: (x: 2cm, y: 2.5cm),
      header: none,
      footer: align(center)[#text(10pt)[- #context counter(page).display("i") -]]
    )
    counter(page).update(1)

    align(center)[
      #text(18pt, weight: "bold")[改版履歴]
    ]
    v(1.5em)

    let has-author = revision_history.any(r => r.author != "")
    let cell(s) = s.split("\n").join(linebreak())
    let head = ([*版数*], [*日付*], [*改版内容*])
    let widths = (auto, auto, 1fr)
    if has-author {
      head.push([*担当*])
      widths.push(auto)
    }
    let rows = revision_history.map(r => {
      let cells = (cell(r.version), cell(r.date), cell(r.description))
      if has-author { cells.push(cell(r.author)) }
      cells
    }).flatten()
    table(
      columns: widths,
      align: left,
      stroke: 0.5pt + luma(150),
      fill: (_, row) => if row == 0 { luma(240) } else { none },
      table.header(..head),
      ..rows,
    )
    pagebreak()
  }

  // -------------------------
  // 2. 目次 (Table of Contents) : toc: false のときは省略する
  // -------------------------
  if toc {
    set page(
      paper: paper_size,
      flipped: landscape,
      margin: (x: 2cm, y: 2.5cm),
      header: none,
      footer: align(center)[#text(10pt)[- #context counter(page).display("i") -]]
    )
    // 目次のページ番号を i から開始。ただし改版履歴ページがある場合は、その続き（ii）にする
    if revision_history == none { counter(page).update(1) }

    align(center)[
      #text(18pt, weight: "bold")[目次]
    ]
    v(1.5em)
    outline(title: none, indent: auto)
    pagebreak()
  }

  // -------------------------
  // 3. 本文 (Body)
  // -------------------------
  set page(
    paper: paper_size,
    flipped: landscape,
    header: render-header(if header != none { header } else { title }, logo),
    footer: render-footer(footer, paginate),
    background: render-background(background),
  )
  counter(page).update(1) // 本文のページ番号を 1 からリセット

  set par(justify: true, leading: 0.8em)

  // 見出し1 (大見出し/章) の直前で必ず改ページする（すでにページ先頭の場合はスキップ）
  show heading.where(level: 1): it => {
    pagebreak(weak: true)
    v(1em)
    it
    v(0.5em)
  }

  doc
}
