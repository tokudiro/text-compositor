# ライセンスと、関連する文書

## ライセンス

Obunzuは、MITライセンスで公開しています。商用利用も、無償で、制約なく、使えます。

Obunzuの配布物（ZIP）には、Electron（Chromiumを含む）・Python・Typst・フォント（Noto Sans JP）など、ほかのソフトウェアが、入っています。それぞれのライセンスの表記は、展開したフォルダの中の、次のファイルにあります。

| ファイル | 内容 |
| --- | --- |
| `licenses\THIRD-PARTY-NOTICES.md` | 同梱するソフトウェアの一覧（版・ライセンス・入手先） |
| `licenses\` | 各ライセンスの全文 |
| `LICENSE`・`LICENSES.chromium.html` | ElectronとChromiumのライセンス |

図を描くために、Typstの描画ライブラリ、CeTZを同梱しています。CeTZは、LGPL-3.0以降のライセンスです。改造せずに、別のフォルダ（`typst-packages\preview\cetz\`）のまま入れているため、別の版に、差し替えられます。ライセンスの全文は、そのフォルダの、`LICENSE`です。ソースは、[Typst Universe](https://typst.app/universe/package/cetz)と、[GitHub](https://github.com/cetz-package/cetz)にあります。Obunzuで作る図や、あなたの文書には、LGPLは、及びません。

初回に取得する、Mermaid・PlantUML・D2・Javaは、Obunzuには、入っていません。それぞれのライセンスに従って、取得したものを、使います。

## 関連する文書

- [text-compositorの使い方ガイド](https://github.com/tokudiro/text-compositor/releases)（Releasesに、PDFがあります）: Markdownの書き方・図表・PDFの作り方。
- [Obunzuの開発者向けの説明](https://github.com/tokudiro/text-compositor/blob/master/viewer/README-ja.md): ソースからの実行・構成・テスト・環境変数。
- [配布物の詳細](https://github.com/tokudiro/text-compositor/blob/master/doc/viewer-distribution.md): 同梱物・大きさ・初回に取得するもの・更新の方法。
