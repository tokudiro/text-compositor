# 2 制約

この設計が従う制約を、3つに分けて示す。各制約には、根拠と、設計への影響を書く。制約は、他の章から、IDで参照する。

## 2.1 技術的な制約

| ID | 制約 | 根拠と、設計への影響 |
| --- | --- | --- |
| TC1 | 実装は、Python 3.10以上で動く | `pyproject.toml`の`requires-python`。コアは、Pythonだけで完結し、常駐サーバーやコンテナを要求しない（`doc/spec.md`2章）。→ 5章の変換エンジンは、Pythonのパッケージ |
| TC2 | Typstコンパイラのバイナリは、同梱しない。PyPIの`typst`パッケージ（`requirements.txt`で、`typst==0.15.2`に固定）から得る | OSごとのwheelにコンパイラ本体が入るため、`pip install`だけで済む（`doc/spec.md`3章）。→ 5章のTypstコンパイラは、プロセス内で動く。版は、ADR-1・8.1で固定する |
| TC3 | 重い実行環境を要る図表ツールは、コアとは別のプラグインに分け、実行環境の取得・固定・キャッシュまで、ツール自身が引き受ける | Asciidoctor Diagramのように、利用者が事前に環境を入れる前提を採らない（`doc/spec.md`11章、[#308](https://github.com/tokudiro/text-compositor/issues/308)）。→ ADR-2 |
| TC4 | ObunzuのZIPは、Windows（x64）向け。Electron（Chromium）を同梱する | Viewerの表示エンジンは、実測の体感で、Electronに決めた（[#180](https://github.com/tokudiro/text-compositor/issues/180)）。Windowsを優先し、他は後続（`doc/gui-viewer-design.md`）。→ ADR-4・7章 |
| TC5 | 図表の描画に、外部のAPI・SaaSを使わない。完全にローカルで完結する | `doc/spec.md`2章の「絶対要件」。11章のプラグインにも適用する。→ 3章の外部は、取得元だけ |
| TC6 | PDFのフォントは、OSのフォントに依存しない。Noto Sans JPと、等幅のNoto Sans Mono CJK JP（どちらもOFL-1.1）を、`font_paths`で明示する | 同じ入力から、同じ見た目を得るため（`doc/spec.md`9章）。→ 8.1 |

<!-- pagebreak -->

## 2.2 組織上の制約

| ID | 制約 | 根拠と、設計への影響 |
| --- | --- | --- |
| OC1 | 利用は、商用を含めて無償。登録・回数・地域・出力への制限や課金は、設けない。依存は、この条件を妨げないライセンスのものに限る | `doc/spec.md`2章の方針1。GPL・AGPLなどの強いコピーレフトのものは、取り込まない（`doc/development.md`3章）。→ 同梱するときは、ライセンスの全文・表記・ソースの入手先を添える（7.4） |
| OC2 | 読み込む情報と出力する情報は、すべてローカルPC内に閉じる。テレメトリ・利用状況の送信は、行わない | 方針2。文書を開く・ビルドするだけで、原稿の内容が外へ出る通信（画像のURLの読み込みなど）が起きないようにする。→ Obunzuは、外部の画像を、既定で読み込まない（8.5） |
| OC3 | PyPIは、同じ版を再アップロードできない。タグのpushで、PyPIへ自動で公開される（取り消せない）。`pypi`環境には、承認の保護が付いていない | `doc/viewer-distribution.md`のリリース手順。→ タグを打つ前に、`pytest`・wheelのビルド・新しいvenvでの確認を、必ず行う（6.6） |
| OC4 | リリースの完了の判断（マージ・クローズ・公開）の前に、確認を取る | `doc/development.md`1章。→ 6.6の手順4 |
| OC5 | 公開リポジトリに、個人情報・社外秘・非公開リポジトリの内容・個人の環境の事情を書かない。書いてしまうと、履歴の書き換え（force push）という、高い費用の対応が要る | `doc/development.md`4章。→ この文書も、公開されている記録だけを根拠にする |
| OC6 | 配布物（Obunzu）に、コード署名をしていない | 署名の要否・費用・手順は、必要が出たときに、別に検討する（`doc/viewer-distribution.md`）。→ R2 |

## 2.3 規約

| ID | 規約 | 背景 |
| --- | --- | --- |
| C1 | 新しい作業（機能・調査・修正）は、先にissueを作ってから、取りかかる。ゴール（完了条件）を本文に書く | 作業中の論点を、後続のissueへ散らさないため。判断の理由も、履歴に残る（`doc/development.md`1章） |
| C2 | 技術的に成立しない案・方針に合わない案は、理由を書いて、`not planned`でクローズする。需要が確認できない記法・機能は、クローズせず、優先度を下げる | 需要は、時間とともに変わるため（`doc/development.md`1章） |
| C3 | コミットとPRは英語。コード内のコメントと、issue・文書は日本語。コメントには、設計意図・背景・トレードオフを書く | `doc/development.md`2章 |
| C4 | PRが、issueの一部だけを解決するときは、`Refs #N`と書く。全部を解決するときだけ、`Closes #N`と書く | `Closes`だと、マージでissueが閉じてしまう（`doc/development.md`2章） |
| C5 | docs・README・版上げだけのPRでは、CI（`test.yml`）を起動しない。ローカルで`pytest`を実行して、代わりにする | 無関係な変更で、CIを動かさない方針（[#97](https://github.com/tokudiro/text-compositor/issues/97)） |
| C6 | 作業用の一時ファイルは、リポジトリ直下の`temp/`に置く（`.gitignore`済み） | システムの一時フォルダは、パスが長く、場所が分かりにくい（`doc/development.md`5章） |
| C7 | サンプルは、具体的に書く（数値・入力と出力と失敗・他の章への参照・図に出ない情報）。省くときは、構造上の理由を、文書に書く | `doc/spec.md`3章（[#641](https://github.com/tokudiro/text-compositor/issues/641)）。この文書も、これに従う |
