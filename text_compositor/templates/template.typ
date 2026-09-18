// 幅・高さいずれかが利用可能領域をはみ出す場合だけ、縦横比を保って自動縮小する（mermaidなど事前レンダリング済み画像用）
#let MAX_IMG_HEIGHT = 12cm
#let fit-image(path) = layout(size => context {
  let img = image(path)
  let i-size = measure(img)
  let w-scale = size.width / i-size.width
  let h-scale = MAX_IMG_HEIGHT / i-size.height
  let scale = calc.min(w-scale, h-scale, 1.0)
  if scale < 1.0 {
    image(path, width: i-size.width * scale)
  } else {
    img
  }
})

// Graphviz（diagraph、#82でwidth/height明示指定に対応するためconf()の外へ出し、
// build.py生成コードから直接呼べるようエクスポートした。conf()内のshow raw.where(lang: "dot")
// ルールは、width/height未指定の呼び出し（自動縮小のみ）としてこの関数をそのまま使う）。
#import "@preview/diagraph:0.3.7": render
#let render-graph(code, width: none, height: none) = if width != none or height != none {
  render(code,
    width: if width != none { width } else { auto },
    height: if height != none { height } else { auto })
} else {
  layout(size => context {
    let graph = render(code)
    let g-size = measure(graph)
    if g-size.width > size.width {
      render(code, width: 100%)
    } else {
      graph
    }
  })
}

// GitHub形式のalert記法（`> [!NOTE]`等、#61）。build.py側がblockquoteの先頭行から種別を検出し、
// callout(kind: "note")[...]のようなコードを生成する。実体はnote-me（MIT、@preview/note-me:0.6.0。
// #63でライセンス確認済み）にそのまま委譲する。全テンプレートが同じ関数名を持つ必要があるため
// （原稿を書く人はテンプレートの種類を意識しない。doc/usage/10_custom_template.md参照）、
// slide.typにも同じ実装がある。
#import "@preview/note-me:0.6.0": note, tip, important, warning, caution
#let callout-fns = (note: note, tip: tip, important: important, warning: warning, caution: caution)
#let callout(kind: "note", body) = (callout-fns.at(kind, default: note))(body)

// 本文ページのヘッダー・フッター（#42）。chapters[]/front-matterによるチャプター単位の上書きは
// build.py側が章ごとに#set page(header: render-header(...), footer: render-footer(...))を
// 再発行する形で実現する（state()は使わない。#16の反省点。landscape/paper_sizeと同じ
// 「明示指定を都度出し直す」パターンで、チャプターの並べ替えに対して安全）。
// logo（#54）: 左にロゴ画像、右にheader_text。logoがnoneのときは従来どおり右寄せのみ。
#let render-header(header_text, logo) = {
  if logo != none {
    grid(
      columns: (auto, 1fr),
      align: (left + horizon, right + horizon),
      image(logo, height: 1.2em),
      text(8pt, fill: luma(100))[#header_text],
    )
  } else {
    align(right)[#text(8pt, fill: luma(100))[#header_text]]
  }
  v(0.5em)
  line(length: 100%, stroke: 0.5pt + luma(200))
}

#let render-footer(footer_text, paginate) = {
  let page-num = context counter(page).display("1")
  if footer_text != none and paginate {
    grid(
      columns: (1fr, 1fr),
      align(left)[#text(9pt)[#footer_text]],
      align(right)[#text(9pt)[#page-num]],
    )
  } else if footer_text != none {
    align(left)[#text(9pt)[#footer_text]]
  } else if paginate {
    align(center)[#text(9pt)[#page-num]]
  } else {
    none
  }
}

// 本文ページの背景画像（#55）。header/footerと同じ「章単位で明示指定を出し直す」パターンで、
// build.py側が章ごとに#set page(background: render-background(...))を再発行する。
// 画像はページ全面に敷き、本文はその上に通常どおりレイアウトされる（重なりの調整はしない。
// 濃い背景を使うと本文が読みにくくなるため、薄い画像を使うことを利用者側で判断する）。
#let render-background(path) = if path != none {
  place(top + left, image(path, width: 100%, height: 100%))
} else {
  none
}

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
