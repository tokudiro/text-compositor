// Typst Universeのテンプレート「ilm」（@preview/ilm、MIT-0）を、text-compositorのconf()契約へ
// 合わせるアダプタの例（#63）。ilmのコードはこのリポジトリへコピーせず、@previewの記法で
// ビルド時にTypstが取得する（初回のみネットワークが必要）。
//
// アダプタの役割は次の2つだけである。詳細は doc/usage/10_custom_template.md を参照。
//   1. build.pyが生成するコードが呼ぶ補助関数（fit-image等）をエクスポートする。
//      実装は、build.pyが隣へコピーする_common.typから取り込む。
//   2. conf()の引数（config.yamlのdocument:）を、ilm自身の引数へ翻訳する。
#import "_common.typ": fit-image, render-graph, render-header, render-footer, render-background, callout
#import "@preview/ilm:2.1.1": ilm

// conf()のdateは"YYYY-MM-DD"形式の文字列だが、ilmはdatetimeを要求する。形式が合わなければ日付を出さない。
#let to-datetime(s) = if type(s) == str and s.match(regex("^\d{4}-\d{2}-\d{2}$")) != none {
  let p = s.split("-").map(int)
  datetime(year: p.at(0), month: p.at(1), day: p.at(2))
} else {
  none
}

// conf()の必須引数は、テンプレートが使わなくても受け取れなければならない（受け取れないと常にビルドエラー）。
// ilmが対応しないもの（subtitle・landscape・cover_page_number・header・logo・background・revision_history）は
// 受け取って無視する。ilmのページ設定を、build.pyが章単位で出し直すheader/footerと衝突させないためでもある。
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
  // build.pyはNoto Sans JPを--font-pathで渡す。ilmの既定フォントに無い日本語はここで補う。
  set text(font: "Noto Sans JP")
  show raw.where(lang: "dot"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }
  show raw.where(lang: "graphviz"): it => if graphviz { align(center)[#render-graph(it.text)] } else { it }

  show: ilm.with(
    title: title,
    authors: author,
    date: to-datetime(date),
    paper-size: paper_size,
    cover-page: if cover { "use-ilm-default" } else { none },
    table-of-contents: if toc { outline() } else { none },
    footer: if paginate { "page-number-alternate-with-chapter" } else { none },
  )
  doc
}
