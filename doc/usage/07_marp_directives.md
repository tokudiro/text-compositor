# Marp/Pandoc互換

![Marp](badges/marp.svg)

## Marpディレクティブ

Obunzu（HTML出力）も、同じディレクティブを、警告なしで読み捨てます。

Marp形式のスライドでよく使う3つのHTMLコメントディレクティブ（`header`/`footer`/`paginate`）は認識します。ただし、**値は反映しません**（読み捨てます）。Marp原稿をそのまま`chapters`に流し込んでも、ビルドが失敗したり不要な警告が大量に出たりしないための措置です。

```markdown
<!-- header: "第1部" -->
<!-- footer: "社外秘" -->
<!-- paginate: false -->
```

このHTMLコメント形式のディレクティブは、ファイル内の任意の位置に置け「以降のページに持続する」というMarp本来の性質を持っています。これは章の並べ替えに対して安全でない（並べ替えると意図しないヘッダーが別の章に混入しうる）ため、値の反映はしていません（[#41](https://github.com/tokudiro/text-compositor/issues/41)）。

**同じキー名でも、front-matter（「Markdownファイルの書き方」の章）や`chapters[].header`/`footer`/`paginate`（「chapters: 章の並び」の章）で指定した場合は、実際に反映されます。** こちらはファイル全体に対する1回きりの明示指定で、他の章には持続しないため安全です（[#42](https://github.com/tokudiro/text-compositor/issues/42)）。Marp原稿の見た目を再現したい場合は、ディレクティブコメントをそのまま使うのではなく、front-matterまたは`config.yaml`側に書き写してください。

上記以外のディレクティブや通常のHTMLタグ（`<br>` 等）は、従来どおり警告を出すだけで、ビルドは継続します。

## Pandoc原稿を流し込む場合

Pandocでよく使われる主要拡張（fenced divs・属性付きフェンスコードブロック・footnote・citation・definition list）を`chapters`にそのまま流し込んでも、Marpと同じ意味で「通ります」。つまり、ビルドが失敗したり大量の警告が出たりはしません。**ただし、値は反映されません。** footnoteを実際の脚注として組版する、citationを参考文献として解決する、fenced divsのクラス指定で見た目を変える、といった機能は無く、いずれも素の地の文としてそのまま表示されます。

```markdown
::: {.note}
Pandocのfenced divsは、そのままの見た目のテキストとして表示されます。
:::

footnoteの参照[^1]も、citationの参照[@key]も、そのままの記号付きで表示されます。

[^1]: footnoteの本文もそのまま表示されるだけで、実際の脚注にはなりません。

Term
: definition listも、通常の段落として表示されます。
```

これらの値を実際に反映したい場合は、Pandocの機能に頼らず、このツールが対応する記法（このツール独自の`:::`ブロック——「Markdownファイルの書き方」の章——や、通常のMarkdownの脚注・参考文献リストとしての段落）で書き直してください。
