# 8 横断的な関心事

複数の構成要素にまたがる決まりを書く。5章の各構成要素は、ここに書いた決まりに従う。

## 8.1 再現性（版の固定）

「同じ入力から、同じ出力を得る」ために、出力に影響するものの版を、コードに固定する（Q1）。

| 対象 | 固定のしかた | 確認 |
| --- | --- | --- |
| Typstコンパイラ | `requirements.txt`と`pyproject.toml`で`typst==0.15.2`。ビルドのたびに、入っている版と比べ、食い違えば、警告する（ビルドは続ける。[#49](https://github.com/tokudiro/text-compositor/issues/49)） | `--check-env`。`requirements.txt`が無いpip環境では、比べる対象が無く、何もしない |
| Typstのパッケージ | `_common.typ`などで、版を固定する（例: `diagraph` 0.3.8） | `tests/test_bundled_typst_assets.py`が、配布物の版と、ツール本体の版を比べる |
| 図表ツール・JS・JRE・フォント | `deps.py`に、URLとSHA256を固定する（PlantUML 1.2026.9、Temurin JRE 21.0.13+9、D2 v0.9.0、Mermaid 12.3.0、Noto Sans JP 2.004など） | `tests/test_bundled_diagram_tools.py`。取得のたびに、SHA256を確かめる |
| フォント | OSのフォントを使わない。Noto Sans JPなどを、`font_paths`で指定する（TC6） | `tests/test_pdf_fonts.py`。`template.typ`は、OSのフォント名を書かない |
| 配布物の依存 | `viewer/dist-requirements.txt`に、版を固定する | `tests/test_distribution.py`が、`pyproject.toml`と比べる |
| 図のSVGのキャッシュ | キーに、図の種類・ツールの版・入力を入れる。`!include`するファイルの相対パスと中身も入れる（`:inc=<ハッシュ>`） | `tests/test_diagram_cache_key.py` |

版の更新の影響は、同じ入力で、新旧を描いて比べてから上げる。ギャラリーのPDFを、画素まで比べた例がある（Pikchrの載せ替え。`doc/plugin-architecture.md`）。バイト単位の一致までは、確かめていない（未確認）。

## 8.2 取得とキャッシュ

- **取得**: 6.5の規則（`.part`・SHA256・合計3回の再試行）に従う。キャッシュの置き場所は、7.2。
- **JSのキャッシュ**: ファイル名に、固定したSHA256の先頭12文字を含め、使う前に一致を確かめる。以前は、固定名で、確認なしに使っていたため、版を上げても、古い版が使われた（[#597](https://github.com/tokudiro/text-compositor/issues/597)）。
- **SVGのキャッシュ**: キーが変わらない限り、再利用する。Mermaidの`mermaid.min.js`など、版を固定したものは、版が変わるとキーが変わる。
- **使い回し**: `Session`は、`typst.Compiler`と、Mermaid用のブラウザを、呼び出しをまたいで使い回す。使い回している間にブラウザが落ちたら、片付けて、起動し直す。

## 8.3 診断と行番号

- 診断は、`error`・`warning`・`hint`・`info`の4段階で、`message`（要約）・`file`・`line`・`detail`（Typstが整形したエラー全文など）を持つ。
- **行の対応づけ**: Typstのエラーは、`temp_build.typ`の行を、srcmapで、元のMarkdownの行に直す。図の中の行は、フェンスの開始行を足して、原稿の行にする。インラインHTMLの警告は、直近のブロックの開始行で近似する。
- CLIの出力（`[Error]`・`[Warning]`・`[Hint]`）は、Python APIを入れても、変わらない（全ページ画像の一致で確かめた）。
- `lint:`で、原稿の警告のオン・オフを選べる。誤りは、描画の前に、Fail-fastで報告する。

## 8.4 エラー処理（Fail-fast）

この方針を[[Fail-fast]]と呼ぶ。描画に失敗したら、テキストへ静かにフォールバックせず、診断つきで終了する（ADR-7）。configの誤り・未設定の変数・許可されていない`plugins`のキーは、長い描画を始める前に、報告する。例外は、Typstの版の不一致（警告だけで、続ける）。Python APIは、例外を出さず、`ok=False`の結果を返す。

## 8.5 安全性

| 対象 | 決まり | 確認 |
| --- | --- | --- |
| PlantUML | `PLANTUML_SECURITY_PROFILE=ALLOWLIST`で起動する。既定のままだと、`!include`が、プロジェクトの外のファイルや公開URLを読めてしまう（実機で確認）。呼び出し元の設定は上書きし、`PLANTUML_ALLOWLIST_PATH`・`PLANTUML_INCLUDE_PATH`は取り除く（ADR-8） | `tests/test_plantuml_security.py` |
| `!include` | 原稿のフォルダの中のファイルだけ許す。URL・絶対パス・フォルダの外・見つからないものは、理由つきのエラーにする。深さは8まで | `tests/test_plantuml_include.py` |
| Obunzuの文書 | HTMLのスクリプトを無効にし（CSP）、サンドボックスを使う | `viewer/`のテスト |
| 外部の画像 | 既定で読み込まない。CSPの`img-src`と、メインプロセスの`session.webRequest`で、`http`・`https`のリクエスト自体も拒否する（二重の防御。[#238](https://github.com/tokudiro/text-compositor/issues/238)） | 同上 |
| 通信 | 原稿・出力を外へ送らない。テレメトリは無い（OC2） | — |
| 取得物 | SHA256を固定し、不一致なら、使わない | `tests/test_download.py` |
| 同梱部品の脆弱性 | 利用者に届くのは、こちらが新しい版を出してから。検知の仕組みは、8.6 | R3 |

## 8.6 同梱部品の更新

同梱した部品の更新は、こちらの責任になる（方針3。[#240](https://github.com/tokudiro/text-compositor/issues/240)）。

| 対象 | 検知 | 知らせ方 |
| --- | --- | --- |
| Electron・npm、PyPI、GitHub Actions | Dependabot（週次・月曜） | PR |
| コードに直接書いた版（Mermaid・PlantUML・D2・Structurizr CLI・Temurin JRE・Noto Sans JP・組込版Python・Typstのパッケージ） | `check-pins.yml`（週次・火曜）が、`check-pins.py`で、上流の最新版と比べる | issue [#255](https://github.com/tokudiro/text-compositor/issues/255)（差があるときだけ。すべて最新になると、自動で閉じる） |

- 通常の更新は、月1回程度、まとめて確認する。重大な脆弱性は、早めにパッチ版を出す。
- メジャー更新は、互換性を確認してから取り込む。図の描画が変わりうるものは、`check-dist.js`と、実際の文書で確かめる。
- 1件ずつ、別のPRにする。版の書き換え先は、`deps.py`・`build-dist.js`・`check-dist.js`・文書。SHA256は、自分で取得して計算し、公表値と突き合わせる。
- 読み取れなかった上流の版は、「確認できず」と書き、差には数えない。読み取れなかった固定箇所は、ワークフローを失敗させる。

## 8.7 テストと確認

| 種類 | 内容 | 実行する場所 |
| --- | --- | --- |
| `pytest`（`tests/`。約100本のテストファイル） | 変換・設定・図の描画・キャッシュのキー・ワーカー・配布物の版の整合など | ubuntu-latest（`test.yml`）。ローカル |
| Node.jsのテストと、実際のワーカーとの結合（`viewer/test/`） | Viewerの部品と、ワーカーとの往復 | windows-latest（`viewer.yml`） |
| `check-*.js`（`viewer/scripts/`） | ElectronのGUIの確認（タブ・検索・設定・自動更新・アクセシビリティなど） | 手元 |
| `check-dist.js` | 展開した配布物を、Pythonへの手がかりを外した環境で起動して確認する（54項目）。Typst関連は、ネットワークを遮断して確認する | 手元 |
| 週次の固定値の確認 | `check-pins.py`の読み取りを、`tests/test_check_pins.py`が確かめる | CI |

## 8.8 アクセシビリティ（Obunzu）

axe-core 4.13と、実際のElectronの操作で、画面を調べた（2026-10-02。[#340](https://github.com/tokudiro/text-compositor/issues/340)）。文書の言語（`lang`）の欠落・選択肢の文字のコントラスト比（3.7:1と4.1:1。基準は4.5:1）・エラーの帯の通知・設定画面のフォーカスなどが、問題として挙がった。確認は、`check-a11y.js`（自動）と、NVDAでの手動で行う。変換したHTMLには、図の代替テキスト（`{alt="..."}`）を付けられる（[#398](https://github.com/tokudiro/text-compositor/issues/398)）。PDFのアクセシビリティ（PDF/UA）は、未着手である（D2）。

## 8.9 日本語

- フォントは、OSに依存せず、Noto Sans JPと、コードブロック用のNoto Sans Mono CJK JPを使う（TC6）。どちらも、Typstが、`ignore_system_fonts`と`font_paths`で、指定したものだけを使う（Obunzu）。
- JVMの文字コードは、`-Dfile.encoding`・`-Dstdin.encoding`・`-Dstdout.encoding`・`-Dstderr.encoding`を、`UTF-8`に明示する。システムのJavaを使うと、日本語のラベルが文字化けし得るためである（[#306](https://github.com/tokudiro/text-compositor/issues/306)）。
- 日本語の文章の書き方（一文は40〜60文字・結論を先に・「が」をつなぎに使わない）は、`doc/development.md`6章に従う。
