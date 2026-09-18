// 全テンプレート共通の補助関数（#63）。build.pyがテンプレートを`.text-compositor/_template.typ`へ
// コピーする際、このファイルも同じ場所（`.text-compositor/_common.typ`）へコピーする。
// そのため、同梱テンプレートも、利用者が書くアダプタ（Typst Universe等の外部テンプレートを
// conf()契約へ合わせる薄い.typ）も、`#import "_common.typ": fit-image, ...`と相対パスで読み込める。
//
// ここにある関数は、build.pyが生成するコードが直接呼び出す（conf()以外の）契約である
// （doc/usage/10_custom_template.md）。template.typ（文書）とslide.typ（スライド）で実装が
// 同一のものだけを置く。render-header/render-footerは、テンプレートごとに見た目が違うため
// 各テンプレートが持つ。下のものは、文書向けテンプレート（template.typ）と同じ既定の実装で、
// アダプタが自前の実装を用意しない場合の出発点として提供する。

// 幅・高さいずれかが利用可能領域をはみ出す場合だけ、縦横比を保って自動縮小する
// （mermaidなど事前レンダリング済み画像用。正方形に近い図は幅基準だけだと高さが溢れるため、
// 幅・高さ両方の縮小率を計算し、小さい方（より厳しい制約）を採用する）。
// 【注意】layout()が返すsize.heightは「ページの残りスペース」ではなく「コンテナ全体の高さ」を
// 返すため、見出しや説明文がすでに使った分は考慮されない。動的計算は信頼できないため、
// タイトル・本文の余地を見込んだ固定の高さ上限(MAX_IMG_HEIGHT)を安全側に設定する。
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
