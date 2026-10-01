# HTML表示方法の計測（#180）

Viewerが、HTMLをどう表示するかを決めるための、計測用のコードである。結果と結論は、[doc/html-viewer-benchmark.md](../../doc/html-viewer-benchmark.md)にある。

## 構成

| パス | 内容 |
| --- | --- |
| `fixture/` | 全候補に表示させる、固定の入力。`fixture.md`（text-compositorの記法を含む原稿）→`index.html`（`render_html`の出力）。`fixture-gfm.md`は、他のツールに開かせる、標準GFMだけの原稿。`make_fixture.py`が生成する（生成物は、リポジトリに含める）。 |
| `wv2/` | WebView2（.NET 10・WinForms）で表示する最小アプリ |
| `wry/` | Tauriのホスト層（tao＋wry。Rust）で表示する最小アプリ |
| `electron/` | Electronで表示する最小アプリ |
| `browser/serve.py` | 「ブラウザ＋ローカルサーバ」の参考用のサーバ（採用しない方式） |
| `measure.ps1` | 自作の候補の、起動・再読み込み・メモリ・プロセス数・待機CPUを測る |
| `measure-visual.ps1` | 全候補（既存のツールを含む）の、画面が落ち着くまでの時間と、再読み込みのちらつきを、画面のキャプチャで測る |
| `measure-external.ps1` | 既存のツール（Arto・Shiba・mo等）の、メモリ・プロセス数・待機CPUを測る |
| `bench-lib.ps1`・`bench-visual.ps1` | 共通の部品（プロセスツリー・画面のキャプチャ） |

各アプリの共通の動作: 引数のHTMLを表示し、読み込みの完了を標準出力へ`loaded`（再読み込みは`reloaded`）と出し、ファイルの変更を検知して再読み込みする。

## 前提

Windows 11。PowerShell 7。次を用意する。

- 固定の入力: `python benchmarks/html-view/make_fixture.py`（Mermaid用のChrome／Edgeが要る。生成済みのファイルが、リポジトリにある）
- WebView2: .NET 10のSDKで、`dotnet build -c Release`（`wv2/`）。環境変数`DOTNET_ROOT`で、SDKの場所を指定できる。
- wry: `cargo build --release`（`wry/`）
- Electron: 公式の配布物（`electron-v44.4.3-win32-x64.zip`）を、`temp/html-view-tools/electron/`へ展開する。
- 既存のツール（任意。`temp/html-view-tools/`に置く）: Arto（`arto-windows-x86_64.exe`）、Shiba（`shiba/shiba.exe`）、mo（`mo/mo.exe`）、MDHero（`mdhero/PFiles/MDHero/mdhero.exe`）、MarkText（`marktext/marktext.exe`）、Ghostwriter（`ghostwriter/ghostwriter.exe`）。

## 実行

```powershell
# 自作の候補（起動・再読み込み・メモリ）
.\benchmarks\html-view\measure.ps1 -Candidate wry -Runs 10 -Reloads 5 -BrowserArgs "--disable-gpu --in-process-gpu"

# 画面の計測（表示までの時間・ちらつき）。測っている間は、他の画面操作をしないこと
.\benchmarks\html-view\measure-visual.ps1 -Tool wry-tuned -Runs 8 -Flicker

# 既存のツール
.\benchmarks\html-view\measure-external.ps1 -Tool arto -Runs 5
```

`-Candidate`・`-Tool`の値は、各スクリプトの`ValidateSet`を参照する。

## 注意

- 画面の計測は、ウィンドウを最前面の同じ位置に置く。計測中は、画面を操作しない。
- 計測の途中で、`fixture/`のファイルの先頭行の空白が、切り替わる（ちらつきの計測のため）。計測の後は、`make_fixture.py`で、元に戻す。
- 「内容が出る」の判定は、画面の中央部の、背景と違う画素の割合による。ばらつく回があるため、傾向を見る目的で使う。
