# Raw Typstの埋め込み（上級者向け）

![text-compositor](badges/text-compositor.svg)

Obunzu（HTML出力）では、`typst-exec`は実行せず、コードブロックとして表示し、警告を出します（[#182](https://github.com/tokudiro/text-compositor/issues/182)）。

数式やTypst固有のレイアウトをどうしても使いたい場合のみ、`typst-exec`言語のコードブロックで生のTypstコードを埋め込めます。**`reviewed/` ディレクトリ配下のファイルでのみ許可**されており、それ以外の場所で使うとビルドエラーになります。AIが生成した原稿をレビューせずそのままコミットする事故を防ぐためのガードレールです。

````markdown
```typst-exec
$ sum_(i=1)^n i = (n(n+1))/2 $
```
````
