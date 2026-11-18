# 1 はじめに と 目標

## 1.1 この文書について

この文書は、text-compositor自身の構造を、arc42の章立てとC4モデルで説明する。text-compositorは、Markdownと図表のソースから、PDF（とHTML）を組み上げるツールである。この文書の[[原稿]]も、text-compositorでPDFにしている。

arc42は、アーキテクチャ設計書の章立てのテンプレートで、全部で12章ある。C4モデルは、System Context・Container・Component・Codeの4つの階層で、構造を段階的に描く方法である。この文書では、Codeを除く3つの階層と、実行時の流れ（Dynamic）、配置（Deployment）を示す。

**根拠の置き方**: 制約・品質目標・決定は、リポジトリの記録（`README.md`、`doc/`の文書、issue番号、コード）に書かれた事実と判断だけを根拠にする。根拠は、`#625`のようなissue番号か、`doc/spec.md`2章のような文書の章で示す。リポジトリに記録がなく、確認できなかったことは、「未確認」「推測」と書く。作り話の数値や理由は、書かない（[#627](https://github.com/tokudiro/text-compositor/issues/627)）。

**対象の版**: text-compositor v0.4.7（`pyproject.toml`）。Obunzu Markdown Viewer（以下、Obunzu）も含む。Obunzuは、同じ版のtext-compositorを同梱し、同時にリリースする（ADR-9）。

| 章 | arc42の章名 | 内容 | C4の図 | 主な読み手 |
| --- | --- | --- | --- | --- |
| 1 | はじめに と 目標 | 目的・要求・品質目標・関係者 | | 全員 |
| 2 | 制約 | 守るべき制約 | | 開発者 |
| 3 | コンテキストとスコープ | 外部との関係 | System Context | 全員 |
| 4 | 解決策の戦略 | 品質目標を満たす方針 | | 開発者 |
| 5 | 構成要素の見方 | 構成要素と、そのインターフェース | Container・Component | 開発者 |
| 6 | 実行時の見方 | ビルド・更新・リリースの流れ | Dynamic | 開発者 |
| 7 | 配置の見方 | 利用者のPC・CIでの配置と、配布物の中身 | Deployment | 開発者 |
| 8 | 横断的な関心事 | 再現性・取得・診断・安全性・テスト | | 開発者 |
| 9 | アーキテクチャ上の決定 | 判断とその理由 | | 開発者 |
| 10 | 品質要求 | 品質の目標値と評価の方法 | | 全員 |
| 11 | リスクと技術的負債 | 既知の弱点 | | 開発者 |
| 12 | 用語集 | 用語の定義 | | 全員 |

図の書き方は、1.7に書く。


## 1.2 目的とスコープ

**目的**: 複数のテキスト（Markdown・図表のソース・CSVなど）を、人が見た目を調整しなくても、1つの読みやすい文書（PDF）に組み上げる。同じ入力からは、同じ出力を得る（`doc/spec.md`1章）。原稿（Model）と見た目（View）を分け、書き手がレイアウトを調整しなくてよいようにする。人が書いた文書にも、AIが書いて人が直した文書にも使える。

**対象（スコープ内）**
- Markdown（とYAML・JSON・CSV・図表ソース）の複数ファイルを、1つのPDFに組む（変換エンジン、CLI）
- 図の[[フェンス]]（Mermaid・PlantUML・D2・Graphviz・Structurizr・Pikchr・CeTZ・Fletcher・Vega-Lite・Vega・WaveDrom・Bytefield・SVGなど）を、同じ原稿の中で混ぜて描く
- 同じ変換を、HTMLにも出す（実験的。[#161](https://github.com/tokudiro/text-compositor/issues/161)）
- Python APIと、常駐ワーカー（Viewerなどの呼び出し元向け）
- Obunzu: Markdownを開いて、保存のたびに更新して表示する、閲覧専用のViewer（Windows向けのポータブルなZIP）
- 同梱する部品の更新と、リリース

**対象外**
- Obunzuでの編集（閲覧専用とする。[#165](https://github.com/tokudiro/text-compositor/issues/165)）
- ObunzuのLinux・macOS版（Windowsを優先し、他は後続とした。`doc/gui-viewer-design.md`）
- PDFのアクセシビリティ（PDF/UAタグ・読み上げ順序）。検討中で、未着手（[#319](https://github.com/tokudiro/text-compositor/issues/319)）
- 外部のサーバー・SaaSを使った図の生成（ツール群の方針2。禁止）

## 1.3 前提

| 項目 | 前提 | 根拠 |
| --- | --- | --- |
| 動かす場所 | pip版は、Python 3.10以上があるPC・CI。ObunzuのZIPは、Windows（x64）で、Pythonが無くてもよい | `pyproject.toml`、`doc/viewer-distribution.md` |
| 利用の条件 | 商用を含めて無償。登録・回数・地域の制限なし。本体のライセンスはMIT | `doc/spec.md`2章 |
| 通信 | 原稿・出力は外へ送らない。ツールとフォントの取得のためだけに通信する | `doc/spec.md`2章 |
| 作り方の決まり | issueを先に作る。コミットとPRは英語、issueとコードのコメントは日本語。人もAIも同じ決まりに従う | `doc/development.md` |
| 公開 | 公開リポジトリ。個人情報・社外秘・個人の環境の事情は書かない | `doc/development.md`4章 |


## 1.4 要求の概要

| 番号 | 機能 | 説明 |
| --- | --- | --- |
| F1 | 原稿の結合 | `config.yaml`の`chapters`に並べた複数のファイルを、順に1冊にする。拡張子で扱いが分かれる（`.md`はMarkdown、`.csv`は表、`.mmd`・`.puml`・`.dot`などは図1枚） |
| F2 | 図のフェンス | Markdownの中の```` ```plantuml ````などを、描いて埋め込む。記法は、描くツールによらず同じ |
| F3 | 組版 | 表紙・目次・改訂履歴・用語索引・ヘッダー・フッター・用紙の向き・2段組などを、設定で切り替える。見た目の既定値は、テンプレート（Typst）が持つ |
| F4 | 出力 | PDF（既定）と、HTML（実験的） |
| F5 | 診断 | 警告とエラーを、原稿の行つきで返す。描画に失敗したら、静かに飛ばさず、止まる |
| F6 | Python API・常駐ワーカー | `Session.build()`と、標準入出力のJSON行。Viewerが使う |
| F7 | Obunzu | ファイル・フォルダ・タブ・検索・設定。保存のたびの自動更新。Mermaidなどの描画をElectronに任せる |
| F8 | 配布 | PyPI（pip版）と、GitHub ReleaseのZIP（Obunzu）。同じ版を、同時に出す |

## 1.5 品質目標

アーキテクチャ上、特に重要な品質目標は、次の5つ。数値の目標と測り方は、10章に書く。

| 番号 | 品質 | 動機 |
| --- | --- | --- |
| Q1 | 再現性 | 「同じ入力から、同じPDFを得る」ことが、このツールの核である（`doc/spec.md`1章・9章）。依存・同梱部品の版が勝手に変わると、文書の見た目が変わる |
| Q2 | 自己完結 | 方針3は、配布物に全部入っていて、ネットワークへ接続してインストールしなくてよいこと。Obunzuは、ZIPを展開して起動するだけで、対応する図を描けることを目標にする（`doc/spec.md`2章） |
| Q3 | 応答性（Viewer） | 保存してから、表示が更新されるまでが遅いと、書く作業の流れが切れる。起動から表示まで1秒以内を、基準にした（`doc/html-viewer-benchmark.md`） |
| Q4 | 拡張容易性 | 図表ツールの追加の要望が続く（対応ツール追加のissueが、5件開いている）。図を1つ足すたびに手で同期する場所が多いと、保守が続かない（`doc/plugin-architecture.md`2章） |
| Q5 | 安全性 | 他人の原稿を開く場面がある。原稿の中の`!include`・画像のURL・HTMLが、PCのファイルや外部通信に届いてはならない（#622・#238） |


## 1.6 関係者

| 役割 | 関心事 |
| --- | --- |
| 書き手（人、またはAI） | 見た目を調整せずに、図の多い文書を書けること。図の記法が、ツールによらず同じであること。エラーが、原稿の行で分かること |
| 読み手 | PDFが読みやすいこと。Obunzuで、保存のたびに更新されること。画面が、スクリーンリーダーとキーボードで使えること（[#340](https://github.com/tokudiro/text-compositor/issues/340)） |
| 開発者（保守者） | 変更の影響が分かること。同梱部品の更新を、見逃さないこと。リリースの手順が、決まっていること |
| 導入する組織 | 商用で、無償で、制限なく使えること。ライセンスの条件が、満たされていること |
| 上流のOSS（Typst・PlantUML・Mermaid・D2など） | ライセンスの条件（表示・全文・ソースの入手先）が、守られること |

## 1.7 この文書の書き方（PlantUML版）

この文書の図は、PlantUMLの標準ライブラリに入っている、C4-PlantUML（<https://github.com/plantuml-stdlib/C4-PlantUML>）のマクロで書く。ライブラリは`plantuml.jar`に同梱されているため、追加の取得は要らない。要素の名前・技術・説明は、`c4-defs.iuml`に、変数として1か所にまとめた。関係（`Rel`）は、図ごとに書く。

同じ題材のStructurizr版は、作らなかった。理由は、構造の繰り返しになるためである。ECサイトのサンプル（`sample/c4-structurizr/`・`sample/c4-plantuml/`）が、同じ12章の構成で、両方の書き方を示している。この文書の目的は、書き方の比較ではなく、実在のシステムの事情を根拠にすることである。
