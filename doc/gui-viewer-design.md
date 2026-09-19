# GUI版Viewer: 設計の決定（#166）

GUI版Markdown Viewer（[#165](https://github.com/tokudiro/text-compositor/issues/165)）の、実装言語・Pythonとの連携方式・GUIフレームワーク・PDF表示ライブラリの決定と、その根拠である。スパイクの結果は、[gui-viewer-spike.md](gui-viewer-spike.md)にある。

## 決定

| 項目 | 決定 |
| --- | --- |
| 連携方式 | Pythonを**常駐サブプロセス**として起動し、標準入出力のJSON行で依頼する。埋め込み（pythonnet・PyO3）は採らない。 |
| 実装言語・GUI | **C# + Avalonia**（.NET 8、MIT）。Windowsを優先し、Linux・macOSは後続とする。 |
| PDF表示 | **PDFium**（[PDFtoImage](https://github.com/sungaila/PDFtoImage)、MIT）でページをビットマップへ描画し、ズーム・スクロール・ページ移動の部品は自作する。 |
| リポジトリ・CI | 同一リポジトリで、専用ディレクトリ・専用ワークフロー・専用タグにより、PyPIのtext-compositorと分離する。安定した後に、別リポジトリへ分けることを検討する。 |
| 採用しなかった候補 | Rust（egui・iced・Slint）、WPF + `Windows.Data.Pdf`、MuPDF（AGPL-3.0）、WebView2系（Tauri等。#99の「ブラウザは使わない」に反する） |

## 計測

計測環境: Windows 11 Pro、Python 3.12.10（venv）、.NET SDK 9.0.304（`net8.0`を対象）、Rust 1.97.1、Avalonia 12.1.2、PDFtoImage 5.4.0、eframe/egui 0.36.2、pdfium-render 0.9.4。計測用のスクリプトとアプリは、`benchmarks/`にある。値は、実行のたびに、10〜30%程度ばらつく。

### 1. 保存から更新まで（Python側、常駐プロセス）

`benchmarks/gui_latency.py`。原稿を書き換えては、`_build_one`（config読み込み → `TypstRenderer.render()` → Typstコンパイル → PDF書き出し）を繰り返し呼ぶ。2回目以降（warm）の平均である。

| シナリオ | 合計 | render | compile | その他 |
| --- | --- | --- | --- | --- |
| 最小 | 31 ms | 0 | 24 | 7 |
| 標準（5節・表・dot図） | 35 ms | 2 | 25 | 8 |
| 大きな文書（40節・約30ページ） | 62 ms | 13 | 37 | 12 |
| Mermaid・キャッシュ命中 | 49 ms | 1 | 39 | 9 |
| Mermaid・図を変更 | 1,815 ms | 1,414 | 49 | 352 |
| PlantUML・図を変更 | 1,544 ms | 1,467 | 72 | 6 |
| D2・図を変更 | 127 ms | 65 | 56 | 6 |

- **通常の編集**: 保存から更新まで、35〜62 msである。実装言語は関与しない。
- **時間がかかるのは図表**: Mermaid（ブラウザの起動）とPlantUML（JVMの起動）を、ビルドのたびに起動するため、約1.5秒かかる。
- **Mermaidのブラウザを開いたままにする**: 図1つあたり、1,269 ms（ブラウザの起動を含む1回目）が、2回目以降は18 msになる。`_build_one`は、ビルドのたびにrendererを閉じてブラウザを終了しているため、この差が出る。
- **`typst.Compiler`を使い回す**: 内容を書き換えても更新が反映され（10/10）、コンパイルは23 msから6.9 msになる。入力を変えずに繰り返すと、さらに速く見えるため、必ず内容を変えて測った。
- **cold**: `text_compositor.build`のimportが149 ms、最初のビルドが48〜94 msである。

### 2. 表示側と通信

| 項目 | 結果 |
| --- | --- |
| PDF 1ページの描画（MuPDFでの目安） | 96dpiで2.5 ms、200dpiで4.7 ms |
| 常駐サブプロセスとの通信（JSON行、往復） | 0.035 ms |

### 3. GUI単体（最小アプリ、12回、1回目はcold）

同じPDF（10ページ）の1ページ目を、PDFiumで描画して表示するまでを測った。

| | C# Avalonia（自己完結・ReadyToRun・シンボル除去） | Rust egui（glow） | 参考: Rust egui（既定のwgpu） |
| --- | --- | --- | --- |
| 最初のフレームまで | 295〜340 ms | 120〜190 ms | 518 ms |
| PDF 1ページ目の初回表示 | 11〜15 ms | 7〜8 ms | 7 ms |
| PDF描画（96dpi、warm） | 6 ms | 6 ms | 6 ms |
| PDF描画（200dpi、warm） | 14 ms | 19 ms | 18 ms |
| ピークのワーキングセット | 169〜191 MB | 248 MB | 354 MB |
| 配布フォルダ | 125 MB（zip 54 MB） | exe 8.2 MB + `pdfium.dll` 7 MB | exe 14.8 MB + `pdfium.dll` 7 MB |

- C#は、ReadyToRunにすると起動が速くなる（最初のフレームまで、JITの自己完結で409 ms、フレームワーク依存のJITで474 ms）。native ライブラリの`.pdb`（約105 MB）を配布物から除くと、224 MBが125 MBになる。
- Rustは、egui標準のフォントに日本語の字形が無いため、日本語のUIには、フォントの組み込みが要る（下記）。Noto Sans JP（約4.5 MB）を足すと、配布物が増える。
- 同じアプリの計測値が、日時によって変わる（例: C#の最初のフレームまで、295 msと340 ms）。差が数十msの項目は、優劣として読まない。

### 4. Pythonワーカーの起動

`benchmarks/gui-startup/worker_startup.py`（Python 3.12）。

| 項目 | 結果 |
| --- | --- |
| 起動 → `text_compositor.build`のimport完了 | 220〜270 ms |
| 起動 → 最初のPDF生成完了 | 270〜320 ms |
| 常駐メモリ | 77 MB |

GUIとPythonワーカーを並行して起動すると、最初のプレビューまでは、C#で約0.4秒、Rustで約0.35秒と見積もる（推測。GUIの最初のフレームとワーカーの準備の遅い方に、最初のビルドが続く）。この差は、一度きりの待ち時間である。

### 5. 見た目

日本語のツールバー（ボタン・コンボボックス・チェックボックス・入力欄）とステータスバーを、両方で同じ構成にして、スクリーンショットを撮った。

- **C# Avalonia**: 日本語が、追加設定なしで正しく表示された（システムフォントを使う）。Fluentテーマの標準的な部品である。
- **Rust egui（標準フォント）**: 日本語が□（豆腐）になり、文字化けした。
- **Rust egui（Noto Sans JPを追加）**: 正しく表示された。ただし、フォントを組み込む処理が要る。

## 決定の理由

1. **更新の速さは、言語で決まらない。** 通常の編集は、Python側の35〜62 msで決まる。GUI側の描画は、数msである。#99で見られた「Rustは起動が約2.4倍速い」差は、埋め込んだPythonの初期化が支配的で、常駐型では効かない。GUI単体の起動も、C#とRustの差は0.2秒程度で、一度きりである。
2. **連携は、常駐サブプロセスにする。** 通信は0.035 msで、無視できる。埋め込みで実際に起きた問題（PyO3のビルド時に組込版Pythonに無い`.lib`が要る、pythonnetの終了時のハング、手作業の`site-packages`が`requirements.txt`に追従しない）が、なくなる。Pythonがクラッシュしても、GUIに波及せず、再起動できる。
3. **見た目と日本語の扱いは、Avaloniaが有利である。** 日本語を追加設定なしで表示でき、標準の部品がそろっている。eguiは、日本語フォントを自前で組み込む必要がある。ビューアは、日本語のUI（メニュー・エラー表示）を持つ。
4. **PDF表示は、既製のPDFiumバインディングがある。** PDFtoImage（MIT）が、ページをビットマップへ描画する。ズーム・スクロール・ページ移動の部品は、どの候補でも自作である。
5. **配布サイズの差は、決め手にならない。** C#は125 MB（zip 54 MB）で、Rustは約15 MBである。しかし、同梱するPython（組込版Python + 依存パッケージ）は、スパイクの計測で約184 MBあり、全体では差が縮まる。

**トレードオフ（Rustを選ばなかったことによる損失）**: 最初のフレームが約0.2秒遅い。配布物が約110 MB大きい。この2点を優先する場合は、Rust（egui + `pdfium-render`、日本語フォントの同梱）が代替になる。

## リポジトリ・CI・リリースの分離

PyPIのtext-compositorとViewerは、ビルドの道具（Python／.NET）・成果物（sdist・wheel／zip等）・公開先が違う。次のように分離する。

- **ディレクトリ**: Viewerは専用のディレクトリに置く（本実装のディレクトリは、#169で作る。現在のスパイクは`viewer-csharp/`）。`pyproject.toml`が`packages`を明示しているため、Viewerのファイルは、sdistにもwheelにも入らない（確認済み）。
- **タグ**: `release.yml`は、`v*`のタグでPyPIへ公開する。Viewerのタグは、`v`で始まらない名前（例: `gui-v0.1.0`）にする。`viewer-v0.1.0`は、`v`で始まるため、`v*`に一致してしまう。
- **ワークフロー**: Viewer専用のワークフローを別ファイルで用意する。PyPIのTrusted Publishingは、`release.yml`と`pypi`環境に紐づいており、Viewerのワークフローには、公開の権限を与えない。`test.yml`は、`text_compositor/`等の変更でだけ動く設定のため、Viewerの変更では起動しない。Viewer側のワークフローにも、専用の`paths`を付ける。
- **GitHub Release**: Viewerのタグごとに別のReleaseを作る。`softprops/action-gh-release`の`make_latest: false`で、ViewerのReleaseが「Latest」にならないようにする（未検証）。
- **バージョン**: ViewerがPythonワーカーとして同梱する`text-compositor`は、固定のバージョンで指定する。
- **別リポジトリへの分離**: #167のPython APIを試行錯誤している間は、同一リポジトリのほうが、変更を1つのPRで扱える。APIが安定し、PyPIから固定バージョンで取れるようになったら、別リポジトリへ移すことを検討する。

## 各issueへの影響

- **#167（Python API）**: 常駐ワーカーから繰り返し呼ばれる前提にする。`typst.Compiler`の使い回しと、Mermaidのブラウザの常駐（1.3秒 → 18 ms）を設計に含める。依頼と応答は、JSON行（依頼: `id`・原稿のパス・オプション、応答: `id`・成否・PDFのパス・警告・エラー（メッセージと行番号）・所要時間）とする案から始める。
- **#168（配布）**: GUIは自己完結・ReadyToRun・シンボル除去で、約125 MB（zip 54 MB）である。配布物のコード署名の要否を、課題に加える。
- **#170（自動再描画）**: 目標値の案は、次のとおりとする。図表のキャッシュが命中する通常の文書で、保存から表示の更新まで、デバウンス（100 ms程度）を含めて300 ms以内。図表を変更した場合は、直前のPDFを表示したまま、更新できた時点で切り替える（PlantUMLは、JVMの起動で約1.5秒かかるため）。
- **#172（CI）**: Viewer専用のワークフローと、`v`で始まらないタグを使う（上記）。
- **#173（スパイク）**: 決定に伴い、`viewer-rust/`を削除した。参照が必要なら、`git show af23aab:viewer-rust/README.md`で取り出せる（`af23aab`はmasterのコミット）。

## 未確認

- **Linux・macOS**: Avaloniaは対応しているが、本実装での確認は、後続とする。
- **配布サイズの縮小**: `PublishTrimmed`やネイティブAOTは試していない。
- **日本語の入力（IME）**: 入力欄に日本語を入力する操作は、確認していない。表示だけを確認した。
- **Slint・icedの見た目と起動**: 測っていない。ライセンスの条件と概要だけを調べた。
- **埋め込み版のPython（3.10）でのワーカー起動**: 計測は、venvのPython 3.12で行った。
- **コード署名**: 要否・コスト・手順は、調べていない（#168）。
