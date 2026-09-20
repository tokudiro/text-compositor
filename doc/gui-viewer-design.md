# GUI版Viewer: 設計の決定（#166）

> **注（2026-09-19）**: 本書は、PDFを表示するViewerを前提にした設計である。Viewerのコンセプトを、「閲覧専用・軽量・Diagrams as Code」に組み直した（[#165](https://github.com/tokudiro/text-compositor/issues/165)）ため、表示方法（本書の「C# + Avalonia」「PDFium」）は、見直し対象である。表示方法の計測は、[html-viewer-benchmark.md](html-viewer-benchmark.md)にある。Pythonの常駐ワーカーと標準入出力のJSON行による連携方式は、そのまま使う。

GUI版Markdown Viewer（[#165](https://github.com/tokudiro/text-compositor/issues/165)）の、実装言語・Pythonとの連携方式・GUIフレームワーク・PDF表示ライブラリの決定と、その根拠である。スパイクの結果は、[gui-viewer-spike.md](gui-viewer-spike.md)にある。

判断の優先順位は、①安定性、②見た目（好みの見た目に近づけられること）、③性能とサイズ、の順とした。

## 決定

| 項目 | 決定 |
| --- | --- |
| 連携方式 | Pythonを**常駐サブプロセス**として起動し、標準入出力のJSON行で依頼する。埋め込み（pythonnet・PyO3）は採らない。 |
| 実装言語・GUI | **C# + Avalonia 12**（MIT）。Windowsを優先し、Linux・macOSは後続とする。 |
| .NETのバージョン | **.NET 10（LTS、2028年11月まで）**。.NET 8・9は、2026-11-10にサポートが終わるため、使わない。 |
| PDF表示 | **PDFium**（[PDFtoImage](https://github.com/sungaila/PDFtoImage)、MIT）でページをビットマップへ描画し、ズーム・スクロール・ページ移動の部品は自作する。 |
| 見た目 | Fluentテーマを土台に、部品の余白・高さ・角丸・色を上書きして、eguiのような、小さく詰まった見た目にする（実物で確認済み）。 |
| リポジトリ・CI | 同一リポジトリで、専用ディレクトリ・専用ワークフロー・専用タグにより、PyPIのtext-compositorと分離する。安定した後に、別リポジトリへ分けることを検討する。 |
| 採用しなかった候補 | Rust（egui・iced・Slint）、WPF + `Windows.Data.Pdf`、MuPDF（AGPL-3.0）、WebView2系（Tauri等。#99の「ブラウザは使わない」に反する） |

## 計測

計測環境: Windows 11 Pro、Python 3.12.10（venv）、.NET SDK 10.0.401（`net10.0`。比較用に、.NET SDK 9.0.304で`net8.0`）、Rust 1.97.1、Avalonia 12.1.2、PDFtoImage 5.4.0、eframe/egui 0.36.2、pdfium-render 0.9.4、Slint 1.18.0。計測用のスクリプトとアプリは、`benchmarks/`にある。値は、実行のたびに、10〜30%程度ばらつく。

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

同じPDF（10ページ）の1ページ目を、PDFiumで描画して表示するまでを測った。C#は、自己完結・ReadyToRun・デバッグシンボル除去で配布する形である。

| | C# Avalonia（.NET 10） | C# Avalonia（.NET 8、参考） | Rust egui（glow） | 参考: Rust egui（既定のwgpu） |
| --- | --- | --- | --- | --- |
| 最初のフレームまで | 386〜446 ms | 347〜356 ms | 120〜190 ms | 518 ms |
| PDF 1ページ目の初回表示 | 12 ms | 12 ms | 7〜8 ms | 7 ms |
| PDF描画（96dpi、warm） | 6〜7 ms | 6 ms | 6 ms | 6 ms |
| PDF描画（200dpi、warm） | 14 ms | 14 ms | 19 ms | 18 ms |
| ピークのワーキングセット | 191 MB | 190 MB | 248 MB | 354 MB |
| 配布フォルダ | 131 MB（zip 59 MB） | 125 MB（zip 54 MB） | exe 8.2 MB + `pdfium.dll` 7 MB | exe 14.8 MB + `pdfium.dll` 7 MB |

- **.NET 10と.NET 8**: 同じコードを、交互に2回ずつ測った。.NET 10は、最初のフレームまでが約40 ms（約1割）遅い。メモリとPDF描画は、同じである。原因は調べていない。
- C#は、ReadyToRunにすると起動が速くなる（.NET 8で、JITの自己完結が409 ms、フレームワーク依存のJITが474 ms）。native ライブラリの`.pdb`（約110 MB）を配布物から除くと、.NET 10で241 MBが131 MBになる。
- Rustは、egui標準のフォントに日本語の字形が無いため、日本語のUIには、フォントの組み込みが要る（Noto Sans JPで約4.5 MB）。
- 同じアプリの計測値が、日時によって変わる（例: .NET 8の最初のフレームまで、295 msと356 ms）。差が数十msの項目は、優劣として読まない。

### 4. Pythonワーカーの起動

`benchmarks/gui-startup/worker_startup.py`（Python 3.12）。

| 項目 | 結果 |
| --- | --- |
| 起動 → `text_compositor.build`のimport完了 | 220〜270 ms |
| 起動 → 最初のPDF生成完了 | 270〜320 ms |
| 常駐メモリ | 77 MB |

GUIとPythonワーカーを並行して起動すると、最初のプレビューまでは、C#で約0.4〜0.5秒、Rustで約0.35秒と見積もる（推測。GUIの最初のフレームとワーカーの準備の遅い方に、最初のビルドが続く）。この差は、一度きりの待ち時間である。

### 5. 見た目

同じ画面（ツールバー・エラーバナー・PDFページ・ステータスバー、日本語、ライトとダーク）を、部品を変えて作り、スクリーンショットで比べた。作業用のモックで、リポジトリには含めない。

| | 印象 |
| --- | --- |
| C# Avalonia（Fluent標準） | ゆったりした余白のWindows 11風。ダークへの切り替えで、全体が揃う。日本語は追加設定なしで表示できる。 |
| Rust egui | 小さく詰まった素朴な見た目。ページの影は標準機能が無く、疑似的に描いた。日本語は、フォントの組み込みが要る（標準では文字化け）。 |
| Rust Slint（Fluent） | 整った見た目で、ボタンは大きい。ダークは、ビルド時にスタイルを切り替える必要があった（実行中の切り替えは、試作では反映されなかった）。 |
| **C# Avalonia（eguiに近づけた調整）** | egui風の、小さく詰まった見た目。標準のFluentの上に、スタイルを重ねただけで実現した。 |

**egui風への調整**（`Avalonia.Themes.Fluent`の上に、コードで約40行）:

- ボタン: 最小の高さ・幅を0、余白を`8,2`、角丸を3、枠なし、背景をフラットなグレー（ライト`#E6E6E6`、ダーク`#3C3C3C`）にする。
- 主ボタン: 背景を青にする。Fluentのテンプレート内のスタイルが優先されるため、`Button.accent /template/ ContentPresenter#PART_ContentPresenter`を直接指定する。
- チェックボックス: 最小の高さを0にする。
- アクセント色: OSの設定（Windowsのアクセント色）に左右されないよう、`FluentTheme.Palettes`で固定する（ライト`#0078D4`、ダーク`#4CA0E8`）。指定しないと、チェックボックスや主ボタンが、OSのアクセント色（開発機では茶色）になる。
- フォント: Noto Sans JPをアプリに埋め込む（`AvaloniaResource`）。eguiと同じ字形になる。
- 余白: ツールバー・ステータスバーの余白を小さくする。

マウスを重ねたときの色は、Fluent標準のまま残る（eguiの色に揃えるには、追加のスタイルが要る）。この調整は、.NET 10でも、同じ見た目で動いた。

### 6. 安定性

**連続再描画**（`benchmarks/gui-startup/soak.ps1`）: PDFの1ページを1,500回、古い画像を破棄しながら描き直して、メモリの推移を見た。

| | 結果 | ワーキングセット（開始 → 終了） |
| --- | --- | --- |
| C# Avalonia（.NET 10） | 完走（終了コード0）。増加なし | 181 → 185 MB（最大199 MB） |
| C# Avalonia（.NET 8） | 完走（終了コード0）。増加なし | 195 → 185 MB（最大203 MB） |
| Rust egui（glow） | 完走（終了コード0）。増加なし | 339 → 189 MB（最大350 MB。序盤だけ高く、その後に下がった） |

- 起動の成功率は、C#・Rustとも12/12だった（ここまでの計測で、起動に失敗したことはない）。
- 限界: 1種類のPDF・1台のPC・1,500回である。GPUドライバの異なる環境や、長時間の常駐は、確かめていない。

**フレームワークのAPIとサポート**:

| | 状況 |
| --- | --- |
| Avalonia 12 | 主題は「性能と安定性」。11からの破壊的変更はあるが、移行の資料がある（.NET 8以降を要求し、.NET 10を推奨）。 |
| egui / eframe（0.x） | **リリースのたびに破壊的変更**がある。今回も、0.36で`App::update`が`ui`に変わり、書き直しが必要だった（`Panel`が`&mut Ui`を取る変更も、0.34で入った）。 |
| Slint（1.x） | SemVerに従い、1.xは本番利用を想定している。デスクトップ向けは成熟の途中と、公式が述べている。 |
| .NET | .NET 8・9は2026-11-10に終了。.NET 10は、2028年11月まで。 |

## 決定の理由

1. **安定性は、Avaloniaが有利である。** 連続再描画で、メモリは増えなかった。APIは、Avalonia 12が安定性を主題とし、.NET 10（LTS）に乗れる。eguiは0.xで、リリースのたびに破壊的変更があり、保守の負担が続く。Slintは1.xで安定しているが、PDF表示などの周辺ライブラリが、C#ほど厚くない（推測）。
2. **見た目は、好みに合わせられる。** 好みは、eguiのような、小さく詰まった見た目である。Avaloniaは、標準のFluentの上にスタイルを重ねるだけで、同じ見た目にできた。eguiにする必要はない。
3. **更新の速さは、言語で決まらない。** 通常の編集は、Python側の35〜62 msで決まる。GUI側の描画は、数msである。#99で見られた「Rustは起動が約2.4倍速い」差は、埋め込んだPythonの初期化が支配的で、常駐型では効かない。GUI単体の起動も、C#とRustの差は0.2〜0.3秒程度で、一度きりである。
4. **連携は、常駐サブプロセスにする。** 通信は0.035 msで、無視できる。埋め込みで実際に起きた問題（PyO3のビルド時に組込版Pythonに無い`.lib`が要る、pythonnetの終了時のハング、手作業の`site-packages`が`requirements.txt`に追従しない）が、なくなる。Pythonがクラッシュしても、GUIに波及せず、再起動できる。
5. **日本語とPDF表示は、Avaloniaのほうが手間が少ない。** 日本語を追加設定なしで表示でき、PDFiumの既製のバインディング（PDFtoImage、MIT）がある。ズーム・スクロール・ページ移動の部品は、どの候補でも自作である。
6. **配布サイズの差は、決め手にならない。** C#は131 MB（zip 59 MB）で、Rustは約15 MBである。しかし、同梱するPython（組込版Python + 依存パッケージ）は、スパイクの計測で約184 MBあり、全体では差が縮まる。

**トレードオフ（Rustを選ばなかったことによる損失）**: 最初のフレームが約0.2〜0.3秒遅い。配布物が約115 MB大きい。この2点を優先する場合は、Rust（Slint、またはegui + `pdfium-render`。日本語フォントの同梱が要る）が代替になる。

## リポジトリ・CI・リリースの分離

PyPIのtext-compositorとViewerは、ビルドの道具（Python／.NET）・成果物（sdist・wheel／zip等）・公開先が違う。次のように分離する。

- **ディレクトリ**: Viewerは専用のディレクトリに置く（本実装のディレクトリは、#169で作る。現在のスパイクは`viewer-csharp/`）。`pyproject.toml`が`packages`を明示しているため、Viewerのファイルは、sdistにもwheelにも入らない（確認済み）。
- **タグ**: `release.yml`は、`v*`のタグでPyPIへ公開する。Viewerのタグは、`v`で始まらない名前（例: `gui-v0.1.0`）にする。`viewer-v0.1.0`は、`v`で始まるため、`v*`に一致してしまう。（実際のタグは、`obunzu-v<バージョン>`にした。[#172](https://github.com/tokudiro/text-compositor/issues/172)、[viewer-distribution.md](viewer-distribution.md)）
- **ワークフロー**: Viewer専用のワークフローを別ファイルで用意する。PyPIのTrusted Publishingは、`release.yml`と`pypi`環境に紐づいており、Viewerのワークフローには、公開の権限を与えない。`test.yml`は、`text_compositor/`等の変更でだけ動く設定のため、Viewerの変更では起動しない。Viewer側のワークフローにも、専用の`paths`を付ける。
- **GitHub Release**: Viewerのタグごとに別のReleaseを作る。`softprops/action-gh-release`の`make_latest: false`で、ViewerのReleaseが「Latest」にならないようにする（未検証）。
- **バージョン**: ViewerがPythonワーカーとして同梱する`text-compositor`は、固定のバージョンで指定する。
- **別リポジトリへの分離**: #167のPython APIを試行錯誤している間は、同一リポジトリのほうが、変更を1つのPRで扱える。APIが安定し、PyPIから固定バージョンで取れるようになったら、別リポジトリへ移すことを検討する。

## 各issueへの影響

- **#167（Python API）**: 常駐ワーカーから繰り返し呼ばれる前提にする。`typst.Compiler`の使い回しと、Mermaidのブラウザの常駐（1.3秒 → 18 ms）を設計に含める。依頼と応答は、JSON行（依頼: `id`・原稿のパス・オプション、応答: `id`・成否・PDFのパス・警告・エラー（メッセージと行番号）・所要時間）とする案から始める。
- **#168（配布）**: GUIは自己完結・ReadyToRun・シンボル除去で、.NET 10で約131 MB（zip 59 MB）である。.NET 10を対象にする（.NET 8・9は2026-11-10に終了）。配布物のコード署名の要否を、課題に加える。
- **#169（MVP）**: .NET 10 + Avalonia 12 + PDFtoImageで作る。見た目は、上記の「egui風への調整」を、最初から取り入れる。
- **#170（自動再描画）**: 目標値の案は、次のとおりとする。図表のキャッシュが命中する通常の文書で、保存から表示の更新まで、デバウンス（100 ms程度）を含めて300 ms以内。図表を変更した場合は、直前のPDFを表示したまま、更新できた時点で切り替える（PlantUMLは、JVMの起動で約1.5秒かかるため）。
- **#172（CI）**: Viewer専用のワークフローと、`v`で始まらないタグを使う（上記）。ビルドは、.NET 10の`actions/setup-dotnet`を使う。（#180でElectronに決まったため、実際のビルドは、Node.jsと組込版Pythonで行う。[viewer-distribution.md](viewer-distribution.md)）
- **#173（スパイク）**: 決定に伴い、`viewer-rust/`を削除した。参照が必要なら、`git show af23aab:viewer-rust/README.md`で取り出せる（`af23aab`はmasterのコミット）。

## 未確認

- **Linux・macOS**: Avaloniaは対応しているが、本実装での確認は、後続とする。
- **長時間の常駐・GPUドライバの違い**: 連続再描画は、1,500回・1台のPCで確かめた。
- **.NET 10の起動が、.NET 8より約40 ms遅い理由**: 調べていない。ReadyToRunの設定やAvaloniaの初期化の違いの可能性がある（推測）。
- **配布サイズの縮小**: `PublishTrimmed`やネイティブAOTは試していない。
- **日本語の入力（IME）**: 入力欄に日本語を入力する操作は、確認していない。表示だけを確認した。
- **マウスを重ねたときの色など、egui風の細部**: 静止画で確認した範囲である。
- **Slint・icedの詳細**: Slintは、見た目と、実行中のテーマの切り替えを、試作で一部だけ確かめた。icedは、測っていない。
- **埋め込み版のPython（3.10）でのワーカー起動**: 計測は、venvのPython 3.12で行った。
- **コード署名**: 要否・コスト・手順は、調べていない（#168）。
