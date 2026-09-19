# GUI版Viewerの起動時間・メモリ・配布サイズ・見た目の計測（#166）

`doc/gui-viewer-design.md`の根拠になった計測に使った、最小のアプリとスクリプトである。ビルド成果物は、リポジトリに含めない。

## 中身

- `cs/`: C#（Avalonia 12.1.2 + PDFtoImage 5.4.0）の最小アプリ。
- `rs/`: Rust（eframe/egui 0.36.2 の glow + pdfium-render 0.9.4）の最小アプリ。
- 2つとも、ウィンドウを開き、PDFの1ページ目をPDFiumで描画して表示し、標準出力へ`first_frame`・`pdf_ms`・`pdf_warm_96dpi_ms`・`pdf_warm_200dpi_ms`を出して終了する（環境変数`HOLD=1`なら終了しない）。日本語のボタン・コンボボックス・チェックボックス・入力欄・ステータスバーも並べている（見た目の比較用）。
- Rustは、環境変数`CJK_FONT`にフォントファイルのパスを渡すと、日本語フォントを追加する。指定しないと、egui標準のフォントで、日本語が文字化けする。
- `measure.ps1`: アプリを繰り返し起動し、最初のフレームまでの時間・PDF描画の時間・ピークのワーキングセットを集計する。
- `shot.ps1`: アプリのウィンドウのスクリーンショットを撮る（`HOLD=1`で起動する）。
- `worker_startup.py`: 常駐Pythonワーカーの、起動からimport完了・最初のPDF生成までの時間と、メモリを測る。

## 手順（Windows）

必要なもの: .NET SDK（`net8.0`を対象にビルドする）、Rust、PDFium（`pdfium.dll`）。

```powershell
# C#: 自己完結・ReadyToRun・デバッグシンボルなし。native ライブラリの .pdb が大きいため、除く
cd benchmarks\gui-startup\cs
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishReadyToRun=true `
  -p:DebugType=none -p:DebugSymbols=false -p:InvariantGlobalization=true -o ..\pub-slim
Get-ChildItem ..\pub-slim -Recurse -Filter *.pdb | Remove-Item

# Rust: pdfium.dllは https://github.com/bblanchon/pdfium-binaries の pdfium-win-x64.tgz から取り出す
cd ..\rs
cargo build --release
Copy-Item <pdfium.dllのパス> target\release\pdfium.dll

# 計測（1回目はcold、2回目以降をwarmとして集計する）
cd ..
.\measure.ps1 -Exe pub-slim\StartupCs.exe -Pdf <PDFのパス> -Runs 12 -Label "C#"
.\measure.ps1 -Exe rs\target\release\startup-rs.exe -Pdf <PDFのパス> -Runs 12 -Label "Rust"
python worker_startup.py
```

## 注意

- `measure.ps1`・`shot.ps1`は、入れ子の`powershell -File`ではなく、呼び出し元のPowerShellで直接実行する。
- 計測値は、実行のたびに、10〜30%程度ばらつく（ディスクのキャッシュ等の影響）。
- `worker_startup.py`は、実行中のPythonで測る（`text_compositor`をimportできる環境が要る）。
