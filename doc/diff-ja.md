# 汎用ツールとの違い

*[English version (英語版)](diff.md)*

「Text → PDF」という技術スタック自体は、text-compositor独自のものではない。[Quarto](https://quarto.org/docs/output-formats/typst.html)はTypstをバックエンドに選べる汎用出版システムで、v1.9以降はbookプロジェクトで複数の`.qmd`ファイルを1つのPDFへ合成する機能も持つ。[md2pdf](https://github.com/cipherchabon/md2pdf)のような単一ファイル向けの軽量CLIも複数存在する。

したがって、text-compositorの存在意義は「技術的に他にない機能」ではなく、**特定のワークフロー（複数の書き手——人間もAIも問わない——が持ち寄った断片的なテキストを練り上げ、安全に本番化する）専用に、運用ルールごとツールへ埋め込んでいること**にある。以下、具体的な違いを挙げる。

## Typst自体との違い

Quartoとの比較の前に、より根本的な疑問に答えておく。「Typstコンパイラを直接使えばよいのでは」という疑問である。

答えは、両者はレイヤーが異なるため比較の対象にならない、というものである。Typstはタイプセッティングエンジンであり、Typst構文で書かれたファイルをPDFに変換する。text-compositorはそのTypstに依存するツールであり、Typstを置き換えるものではない。text-compositorは最終的に`compiler.py`からTypstコンパイラ（`typst.compile()`）を呼び出すだけであり、PDF生成そのものはTypstが行う（3章）。

両者の役割の違いは3点ある。

* **入力形式**: 原稿を書く人間（AIも含む）はMarkdown等の平易なテキストで書く。Typst構文は一切書かない。text-compositorが`markdown-it-py`でAST化し、決定論的にTypst構文へ変換する（1章）。Typstを直接使う場合、原稿自体をTypst構文で書く必要がある。
* **複数ファイルの合成**: 独立した複数のテキストファイル（`chapters`）を、章ごとの用紙設定・ヘッダー/フッターも含めて1冊のPDFに組み上げる`config.yaml`駆動の仕組みは、Typst自体には無い。Typstの`#include`で自分で書くことは可能である。しかし、それは「Typstで自分用のビルドシステムを都度書く」のと同義であり、3章で述べた「ツールとドキュメントの分離」は得られない。
* **書き手へのデザイン権限の遮断**: これが最も本質的な違いである。Typstは本来プログラマブルなレイアウト言語であり、Typst構文を直接扱えるなら、レイアウトの制御もその場でできてしまう。原稿の書き手（AIか人間かを問わない）がTypst構文を直書きできる状態は、その書き手にレイアウトの決定権まで渡すことを意味する。text-compositorがMarkdownしか受け付けない設計にしているのは、レイアウトの決定権をテンプレート（人間が書き・レビューする`.typ`ファイル）側に固定するためである（1章）。

例えるなら、LaTeXに対するSphinxやPandocの関係に近い。「PandocとLaTeXは何が違うのか」が疑問になりにくいのと同様に、text-compositorはTypstの代替ではなく、Typstを変換先として使うツールである。

## 比較表

| 観点 | 汎用ツール（Quarto等） | text-compositor |
| --- | --- | --- |
| 未レビューコードの実行制御 | 特になし。Markdown内のコードは基本そのまま実行系（code cell等）に渡る前提 | `typst-exec`はホワイトリスト方式。`reviewed/`配下のファイルでのみ生Typstコードを許可し、それ以外は即エラー（仕様書7章・8章）。書き手（AIか人間かを問わない）が持ち込んだ「未レビューの表現力」を本番に混ぜない、という運用ルールをツール自体に埋め込んでいる |
| 意図しないHTML混入の検知 | 通常はそのまま無視してレンダリング | AST解析でHTMLタグを検出したら行番号付き警告（仕様書9章）。Markdownにたまに混ざるHTMLタグを「サイレントに握りつぶさない」設計 |
| ファイルアクセスの境界 | プロジェクト全体が信頼された前提 | `--root`をプロジェクトディレクトリに厳密に閉じる。`typst-exec`で`read()`が使われても、意図しないファイルを読めないサンドボックス（仕様書5章・8章） |
| ツールとドキュメントの分離 | プロジェクトディレクトリの中にツールの設定・拡張を書き込む前提が多い | `--config`一つで完全分離。ツール本体を一切変更せず、任意の場所にあるドキュメントをビルドできる（仕様書3章） |
| 再現性への態度 | バージョン固定は利用者側の裁量 | Typst本体・プラグイン・フォントをすべてSHA256/バージョンピン留め（仕様書9章）。「同じ入力なら同じ出力」を強く担保 |
| ファイル分割の単位 | 章・セクション単位の分割が一般的 | 「1ファイル＝1つの独立した断片」という粒度。AIとの対話1回分でも、既存ドキュメントの1章分でも、由来を問わずそのままファイル境界にできる設計（仕様書1章） |
| コードベースの規模 | 大規模・汎用（多数の出力形式、拡張機構、実行可能セル等） | 実装本体は`text_compositor/`配下（トップレベルの`build.py`はこれを呼び出す薄いラッパー、[#111](https://github.com/tokudiro/text-compositor/issues/111)）。`build.py`単体は当初約2,300行まで肥大化したが、[#157](https://github.com/tokudiro/text-compositor/issues/157)で責務ごとのモジュール（`config.py`・`renderer.py`・`chapters.py`・`compiler.py`等、依存は一方向で循環しない）へ分割済み。全体を読んで理解・改造できる規模に留めている |

## GitHub Actions上でのダウンロード量

かつて（#34・#35着手前）は、mmdc（`@mermaid-js/mermaid-cli`）をnpx経由で使う実装だったため、Mermaidを使う場合はtext-compositorの方がQuartoよりダウンロード量が多いという、意図と逆の結果になっていた。#34（システムブラウザの検出・再利用）と#35（`mermaid-cli`丸ごとではなく単一バンドルJS+Playwright経由のCDP直接操作に置き換え）を実装した現在は、以下のとおり逆転している。

| | ダウンロード量 | 内訳 |
| --- | --- | --- |
| Quarto（Mermaidなし、Typstバックエンドでbook合成） | 約140MB | [Quarto CLI tarball](https://github.com/quarto-dev/quarto-cli/releases/) 1本。Pandoc・Deno・[Typstまで同梱済み](https://quarto.org/docs/output-formats/typst.html)で追加ダウンロード不要 |
| Quarto（Mermaidあり） | **約254MB** | 上記140MB + Mermaid図をPDF化するために必要な[Chrome Headless Shell](https://quarto.org/docs/blog/posts/2026-04-14-chrome-headless-shell.html) linux64版。[Google公式配布元](https://storage.googleapis.com/chrome-for-testing-public/152.0.7977.42/linux64/chrome-headless-shell-linux64.zip)で実測 **119,483,791バイト（約114MB、圧縮zip）** |
| text-compositor（Mermaidなし） | 約60.5MB | pip: `typst`(32.6MB) + `markdown-it-py`(0.08MB) + `mdit-py-plugins`(0.05MB) + `PyYAML`(0.73MB) ≈ 33.5MB／Noto Sans JP: ZIP全体27MBをダウンロードし2ファイルだけ使用 |
| text-compositor（Mermaidあり） | **約109MB** | 上記60.5MB + `playwright`パッケージ（PyPI、manylinux1_x86_64ホイール実測**約45.5MB**） + `mermaid.min.js`（実測3.4MB）。ブラウザは`ubuntu-latest`に標準搭載のChromeを`find_system_browser()`（#34）で検出・再利用するため追加ダウンロードなし（11章、#35で実装済み） |
| text-compositor（PlantUMLあり） | 約78MB | 上記60.5MB + `plantuml-mit-*.jar`（実測約17.6MB）。Javaは`ubuntu-latest`に標準搭載のものを`find_system_java()`で検出・再利用するため、CI上ではEclipse Temurin JREの追加ダウンロードは発生しない（11章、#22で実装済み）。Quartoは標準非対応のため比較対象なし |
| Marp CLI（`npx @marp-team/marp-cli`） | 約123MB＋ブラウザ | HTML/CSSをヘッドレスブラウザ（Puppeteer-core）で描画してPDF化する方式。パッケージ自体は約123MB。別途Chromiumが必要 |
| Vivliostyle CLI（`npx @vivliostyle/cli`） | 約242MB＋ブラウザ | Marpと同じくPuppeteer-core方式。CSS組版のフル機能を持つ分、依存ツリーがさらに大きい |

Mermaid込みで比較すると、text-compositor（約109MB）はQuarto（約254MB）の半分以下に収まる。Mermaidを使わない用途ではさらに差が開く（60.5MB対140MB）。この差はNoto SansフォントZIPの無駄（27MBダウンロードして9.2MBしか使わない）を解消すればさらに縮められる（今後の課題）。

実測値は展開後のディスク使用量、またはHTTPヘッダーから直接取得した圧縮ファイルサイズのいずれか（各行に記載の取得方法を参照）。両ツールとも、GitHub Actionsのキャッシュ機構（`actions/cache`等）を使えば2回目以降の実行コストは大きく下げられる。

## 図表描画の対応状況

これも実際に調べると、Mermaid/GraphvizについてはQuartoに対する優位性は薄い。ただしPlantUML・D2は状況が異なる。[#213](https://github.com/tokudiro/text-compositor/issues/213)・[#212](https://github.com/tokudiro/text-compositor/issues/212)・[#236](https://github.com/tokudiro/text-compositor/issues/236)を経て、text-compositorが対応する図の種類は、Mermaid・Graphviz(dot)・PlantUML・D2・Pikchr・Structurizr・CeTZ・Fletcherの8種類まで増えた（仕様書11章）。

| ツール | Mermaid | Graphviz(dot) | PlantUML | D2 |
| --- | --- | --- | --- | --- |
| text-compositor | 実装済み（Playwright経由のCDP直接操作、#35） | 実装済み（`diagraph`） | 実装済み（ローカルJava+Smetana、#22） | 実装済み（D2公式CLIバイナリ、#90） |
| [Quarto](https://quarto.org/docs/authoring/diagrams.html) | **ネイティブ組み込み**、追加設定不要 | **ネイティブ組み込み**、`{dot}`セルで即使える（[参照](https://medium.com/codex/quarto-1-4-adds-mermaid-and-graphviz-604de76fca21)） | 標準非対応。サードパーティのpandocフィルタか、Java+PlantUML jarの手動セットアップが必要（[参照](https://github.com/orgs/quarto-dev/discussions/6549)） | 標準非対応（公式ドキュメントに記載なし） |
| Marp CLI | 組み込みなし。`markdown-it-mermaid`等を自分で`engine.js`に組み込む必要（[参照](https://github.com/orgs/marp-team/discussions/207)） | 組み込みなし（[要望issueあり](https://github.com/orgs/marp-team/discussions/219)、未実装） | 組み込みなし | 組み込みなし |
| Vivliostyle CLI | 組み込みなし。`rehype-mermaid`等をprocessor置き換え拡張点経由で手動導入（[参照](https://zenn.dev/mura_mi/articles/4f08cc99f19887)） | 情報なし、おそらく同様に手動 | 情報なし、おそらく同様に手動 | 情報なし、おそらく同様に手動 |

Mermaid・GraphvizはQuartoが最初からネイティブに持っており、追加設定が一切要らない。text-compositorは独自に実装した図表連携（Playwright/CDP直接操作・`diagraph`）で、ダウンロード量の面では上回るようになった。ただし、「設定不要ですぐ使える」という手軽さではQuartoに及ばない。PlantUML・D2はQuartoが標準非対応な一方、text-compositorは`plugins.plantuml: true`/`plugins.d2: true`の設定だけで使え（ローカルに実行環境が無ければそれぞれEclipse Temurin JRE・D2公式CLIバイナリを自動取得）、ここは明確な差別化点になった。

### 新しく加わった対応: PikchrとStructurizr

CeTZ・Fletcher（#236）は、独立したエコシステムを持つ図表DSLではなく、Typst自体のネイティブな描画パッケージである。text-compositorがこれらを直接扱えるのは、Typstを変換先にしているからにすぎない。Typstを変換先にしない他ツールとの比較は、同じ形では成立しない。一方PikchrとStructurizrは事情が異なる。どちらも独立したエコシステムを持つ図表言語であるため、下表のような同じ形の比較ができる。

| ツール | Pikchr | Structurizr |
| --- | --- | --- |
| text-compositor | 実装済み（`kip`、Typstネイティブのwasmパッケージ、#213） | 実装済み（公式`structurizr-cli`で既存のPlantUMLパイプラインへ橋渡し。CLI一式が約99MBあるため、既定で無効のオプトイン、#212） |
| [Quarto](https://quarto.org/docs/authoring/diagrams.html) | 組み込みなし。サードパーティのR/knitrエンジンラッパー経由でのみ利用可能（Quarto本体の機能ではない） | 情報なし、標準非対応と思われる |
| [Asciidoctor Diagram](https://docs.asciidoctor.org/diagram-extension/latest/) | 組み込みバックエンド | 組み込みバックエンド |
| Marp CLI | 情報なし | 情報なし |
| Vivliostyle CLI | 情報なし | 情報なし |

## 「対応ツールの広さ」だけでは足りない: Asciidoctor DiagramとKrokiとの比較

率直に確認しておきたい論点がある。「幅広い図表ツールに対応している」こと自体は、差別化根拠になるのか、という論点である。答えは否である。この立ち位置には、既に先例がある。

AsciiDoc用の拡張機能[Asciidoctor Diagram](https://docs.asciidoctor.org/diagram-extension/latest/)は、20種類以上のバックエンドへディスパッチする。AsciiToSVG、BlockDiag系（BlockDiag/SeqDiag/ActDiag/NwDiag/RackDiag/PacketDiag）、Bytefield-SVG、DBML、Ditaa、Dpic、Erd、Gnuplot、GoAT、Graphviz、LilyPond、Mermaid、MscGen、Nomnoml、Penrose、Pikchr、Pintora、PlantUML、Shaape、State Machine Cat、Structurizr、SvgBob、Symbolator、Syntrax/JSyntrax、UMLet、Vega/Vega-Lite、WaveDromである。このリストは、text-compositor自身の8種類より、既に広い。したがって、「対応ツールの広さ」単体は、text-compositorが主張してよい差別化根拠ではない。より広い先例が、既に存在する。

決定的な違いは、別のところにある。Asciidoctor Diagramは、各バックエンドの実行環境——Graphvizバイナリ、Java+`plantuml.jar`、一部バックエンドではNode.js等——が、利用者によって事前にインストール済みであることを前提とする。これは純粋なディスパッチ層である。20種類以上のいずれかの言語で、既に書かれたコードを渡せば、対応するローカルCLIを呼ぶだけである。text-compositorの「無ければ自動取得・SHA256固定・キャッシュ」（仕様書11章）に相当する仕組みは、無い。

[Kroki](https://kroki.io/)は逆の方式を取る。20種類以上の図表DSLを、単一のAPIへ統合している。しかし、公開版のWebサービスは、図のソースを外部サーバーへ送信する方式に依存する。これは、仕様書2章の絶対要件（図表生成のための外部通信を行わない）と相反する。セルフホスト版のDocker配布は、この外部通信への依存は避けられる。しかし、代わりにDockerという、本来このツールには不要な依存を持ち込む。

Quartoは、ここでもAsciidoctor Diagramの対極にある。ネイティブ対応は狭い（Mermaid/Graphvizのみ）。しかし、その2つに関しては、本当に設定不要である。

| 軸 | Asciidoctor Diagram | Quarto | Kroki | text-compositor |
| --- | --- | --- | --- | --- |
| バックエンド対応の広さ | 広い（20種類以上） | 狭い（Mermaid/Graphvizのみネイティブ） | 広い（20種類以上） | 中程度（8種類、拡張継続中） |
| 手動インストール不要（自動取得＋キャッシュ） | 不可。ローカル実行環境が事前導入済みという前提 | 部分的（Mermaid/Graphvizのみ） | 可能。クライアント側には何もローカルに要らないという意味では | 可能（SHA256固定、仕様書9章・11章） |
| 外部通信・重い追加依存の回避 | 可能（ローカルCLI前提） | 可能 | 公開APIでは不可能。セルフホスト版はDocker依存 | 可能（仕様書2章の絶対要件） |

この表の中に、「広さ」と「自動取得」を両立させたうえで、外部通信・重い追加依存も回避できているツールは無い。text-compositorの立ち位置は、他の広範囲対応ツールがそれぞれどちらかの方向へ手放している「外部通信をしない・重い依存を持たない」という制約を保ったまま、「広さ」と「手動インストール不要」という2つの長所を両方とも手放さずにいようとする試みである。

## なぜ、この種のツールが今まで無かったのか

率直な疑問にも答えておく。このワークフローが本当に有用であるなら、なぜ既存の汎用ツールが、まだ対応していないのか、という疑問である。理由は、大きく4点に整理できる。

**1. 土台となる技術自体が新しい。** Typst以前、プログラマブルなPDF生成の現実的な選択肢は、LaTeX（巨大で、配布の複雑なツールチェイン）か、Chromiumを同梱した重いHTML→PDF変換（本書で既に比較したMarp・Vivliostyleが採る方式）のいずれかだった。`diagraph`/`kip`/`cetz`/`fletcher`/`timeliney`を、外部実行環境不要の軽量なWASM/Typstパッケージとして同梱する選択肢は、Typstが変換先として存在するまで、現実的ではなかった。

**2. 「ツールが必要な依存関係を、利用者に何もインストールさせず、固定・キャッシュしたうえで自動取得してくる」という発想自体が、比較的新しいUX規範である。** AsciiDoc・Sphinx・LaTeXは、いずれも10〜20年前に設計された。当時は、「Graphviz・JDKくらい自分で入れて当然」という前提が、ごく普通のことだった。「ツールが初回実行時に、自分で依存関係を解決する」という期待は、これより後、`npx`的なツール群が広まってからの規範に近い。

**3. 最も本質的な理由として、text-compositorが実際に解いている課題自体、今の形では最近まで存在しなかった。** AsciiDoc・Sphinx・LaTeX・Quartoは、いずれも「1人の熟練した書き手が、時間をかけてツールを学んで使う」という前提で設計されている。本書冒頭で述べたこのツールの存在理由——複数の書き手（AIが書いた断片も含む）の寄稿を、安全にレビュー済みの本番成果物へ組み上げること——へのニーズは、LLMが日常的な執筆に入り込んだ、ここ数年の産物である。既存ツールのどれもが「未レビューコードの実行制御」（本書冒頭付近の比較表1行目）の仕組みを持たないのは、対応し損ねたからではない。より正確には、**その課題自体が、まだ存在していなかったから**である。

**4. 加えて、テキストであること自体の強みも、独立した論点として明記しておく。** 原稿がプレーンテキスト（Markdown・`config.yaml`）であるため、gitの差分・履歴・プルリクエストレビューが、特別な仕組みを追加せずにそのまま使える。これは、GUIツールやバイナリ形式のツール（Word・PowerPoint・Excalidraw等）に対する、テキストベースのツール全般（AsciiDoc・Sphinx・LaTeX・Quarto）に共通する強みである。しかし、text-compositorの核心にとっては、特に土台として重要である。AIが書いた断片をレビューする作業自体が、gitの差分・プルリクエストレビューという既存の仕組みに直接乗る。この点は、3番目の論点と直結する。

以上は、「text-compositorのようなツールを、もっと早く作れたはずだ」という主張ではない。作るのが妥当だと言える条件——軽量な変換先の存在、自動取得というUX規範、そして何より、AIが書いた断片と人間のレビューが実際に混ざり合う執筆スタイル——が揃ったのが、最近になってからだ、という点だけを述べている。

## 結論

「図表描画機能の手軽さ（追加設定の要否）」では、Mermaid/GraphvizについてQuartoに明確な優位性は見出せなかった。ただしPlantUML・D2はQuartoが標準非対応なのに対し、text-compositorは`plugins.plantuml: true`（#22）/`plugins.d2: true`（#90）だけで使えるため、この点は明確な差別化点になった。「ダウンロード量」は、#34・#35の実装によりMermaid込みでもtext-compositorがQuartoの半分以下に収まるようになった。

とはいえ比較表（冒頭）に挙げた項目——`typst-exec`のホワイトリスト、HTMLタグのフェイルファスト、`--root`のサンドボックス化、ツール/ドキュメントの完全分離——は、Quartoを含む汎用ツールが標準では持たない、**複数の書き手（人間もAIも問わない）が持ち寄ったテキストを、レビューを経て安全に本番化するための運用ルール**である。これがtext-compositorの存在意義の核であることに変わりはなく、「軽量」は達成できた副次的な利点という位置づけに留め、主張の軸はこのガバナンス面に置き続けるべきである。
