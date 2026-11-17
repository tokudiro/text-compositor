# ECサイト アーキテクチャ設計書（PlantUML版）

この文書は、ECサイトの構造を、C4モデルで説明します。図は、PlantUMLの標準ライブラリに入っている、[C4-PlantUML](https://github.com/plantuml-stdlib/C4-PlantUML)のマクロ（`Person`・`Container`・`Rel`など）で書きます。ライブラリは、`plantuml.jar`に同梱されているため、`!include <C4/C4_Container>`と書くだけで使えます。追加の取得は要りません。

同じ題材を、Structurizr DSLで書いた例が、`sample/c4/`にあります。

| | Structurizr（`sample/c4/`） | PlantUML（この例） |
| --- | --- | --- |
| 追加で要るもの | `plugins.structurizr: true`、Java、`structurizr-cli`（約99MB） | なし（既定で使える。Javaは、無ければ自動で取得する） |
| モデルの共有 | 1つのモデルを、すべてのビューが共有する | 図ごとに、要素を書く |
| 書き方 | DSL（要素・関係・ビューを別に書く） | マクロ（図の中に、要素と関係を書く） |

## 図ごとに要素を書く理由

PlantUMLの`!include`は、原稿のあるフォルダではなく、ビルドを実行した場所を基準に、ファイルを探します。また、取り込んだファイルを直しても、図は描き直されません。そのため、この例では、共通の定義ファイルを使わず、図ごとに、要素と関係を書いています。要素を直すときは、それを使う図を、すべて直してください。1つのモデルから、複数の図を作りたい場合は、Structurizr版を使ってください。

| 章 | 図 | 読み手 |
| --- | --- | --- |
| 2 | System Context | 誰でも（利用者・企画・他チーム） |
| 3 | Container | 開発者・運用担当 |
| 4 | Component | このシステムの開発者 |
| 5 | Dynamic | 開発者・運用担当 |
| 6 | Deployment | 運用担当・インフラ担当 |
