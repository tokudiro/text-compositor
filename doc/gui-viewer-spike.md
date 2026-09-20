# GUI版Viewer: スパイク（#99）の結果の要約

GUI版Markdown Viewerの本実装（[#165](https://github.com/tokudiro/text-compositor/issues/165)）に着手する前に行った、実現性の確認（スパイク）の結果をまとめる。詳細は、`viewer-csharp/README.md`と`viewer-rust/README.md`（どちらも、削除済み。下の「スパイクのコード」の取り出し方を参照）、および[#99](https://github.com/tokudiro/text-compositor/issues/99)のコメントにある。

## 目的と範囲

`TypstRenderer.render()`（Markdown文字列 → Typstコード文字列）を、C#（pythonnet）とRust（PyO3）から埋め込み呼び出しできるかを確認した。ファイル監視・Typstコンパイル・PDF表示・GUI本体は、範囲外である。

## 結果の要点

| 項目 | 結果 |
| --- | --- |
| 埋め込み連携 | 両言語で、`render()`の呼び出しと戻り値の受け取りに成功した（Windows実機、組込版Python 3.10.11）。 |
| Microsoft Store版Python | 両言語とも動かない。C#は`LoadLibrary`がアクセス拒否になる。Rustはビルド時に`.lib`が無く、実行時はDLLが見つからない。回避策は、組込版Python（python.orgのembeddable package）の同梱である。 |
| 組込版Pythonの配置 | C#は、`Runtime.PythonDLL`でフルパスを指定できるため、exeの隣の`python-embed/`に隔離できる。Rustは、DLLの検索順序の制約で、exeと同じフォルダへ直接展開する必要がある。`PYTHONHOME`は、exeの隣を自動検出する。 |
| `python3.dll` | 削除できない。pythonnet自身は使わないが、`typst`パッケージのネイティブ拡張（`_typst`、Stable ABI）が実行時に必要とする。 |
| 終了時のハング（C#のみ） | 原因は、`PythonEngine.Initialize()`の後、メインスレッドがPythonのスレッドステートを保持したままになることである。プロセス終了時の`PythonEngine.Shutdown()`が、別スレッドでGILを取得できず固まる。`PythonEngine.BeginAllowThreads()`を`Initialize()`の直後に呼ぶと解消する（[pythonnet#1701](https://github.com/pythonnet/pythonnet/issues/1701)）。 |
| 起動時間 | Rust（PyO3）の平均は203.6 ms、C#（pythonnet）は493.2 msで、Rustが約2.4倍速い（各10回、Release）。 |
| ピークメモリ | Rustの平均は26.4 MB、C#は57.2 MBで、Rustが約半分である。 |
| ライセンス | 組込版Python（PSF）と依存パッケージ（MIT・Apache-2.0）は、ライセンス全文と著作権表示の保持が条件である。`*.dist-info/`に含まれるライセンスファイルを、`python-embed/`ごと配布すれば満たせる。一覧は、削除した`viewer-csharp/THIRD-PARTY-NOTICES.md`にあった（`git show 393c9fc:viewer-csharp/THIRD-PARTY-NOTICES.md`）。本実装の配布物（ZIP）にも、同じ趣旨の一覧（`licenses/THIRD-PARTY-NOTICES.md`）がある。 |

起動時間とメモリの差は、プロセスを1回起動して固定文字列を1回変換するだけの測定である。GUIとして常駐させたときの体感は、この差と一致するとは限らない。

## 現在のmasterでの確認（#173、2026-09-19）

v0.3.0時点のmasterで、両スパイクが動くことを確認した。ただし、そのままでは動かず、次の2点を直した。

1. **モジュール名**: パッケージ化（#111）の後、リポジトリ直下の`build.py`は`build()`関数だけを公開する。`TypstRenderer`は`text_compositor.build`にある。`import build`を`import text_compositor.build`に直した。（#157で`build.py`を分割したあとは、`TypstRenderer`は`text_compositor.renderer`にある。）
2. **同梱Pythonの`site-packages`**: 手作業で組み立てているため、`requirements.txt`に依存が増えても追従しない。今回は`platformdirs`が不足した。

確認したのは`render()`の呼び出しまでで、Typstコンパイルは含まない。PDF生成までの確認は、[#167](https://github.com/tokudiro/text-compositor/issues/167)で行う。

## 未確認・課題

- **保存から更新までのレイテンシ**: スパイクでは未計測だった。[#166](https://github.com/tokudiro/text-compositor/issues/166)で計測した（[gui-viewer-design.md](gui-viewer-design.md)）。
- **`site-packages`の組み立て**: `pip install --target`と、`python310._pth`の編集による手作業である。依存の追加に追従できないことが、今回の確認で実際に起きた。自動化が要る（[#168](https://github.com/tokudiro/text-compositor/issues/168)）。
- **Typstコンパイル・PDF表示・図表の描画**: 未確認である。それぞれ、#167・#169・[#171](https://github.com/tokudiro/text-compositor/issues/171)で扱う。
- **Linux・macOS**: Rust版は、Linuxのサンドボックスで`render()`の呼び出しに成功した。C#版は、Linuxで終了時のハングが残った（その後、Windowsで原因を特定して解消した。Linuxでの再確認はしていない）。macOSは未確認である。

## ソースの場所

スパイクのコードは、`viewer-csharp/`（C#・pythonnet）と`viewer-rust/`（Rust・PyO3）にあった。実装言語をC#に決めた（#166、[gui-viewer-design.md](gui-viewer-design.md)）ため、Rust版は先に削除した。その後、本実装が、Electron製の`viewer/`（#169）に置き換わったため、C#版も削除した。参照が必要なら、次で取り出せる（どちらも、masterのコミット）。

- Rust版: `git show af23aab:viewer-rust/README.md`
- C#版: `git show 393c9fc:viewer-csharp/README.md`

連携方式も、埋め込み（pythonnet・PyO3）ではなく、常駐サブプロセスに決めた。スパイクの`viewer-csharp/`は、本実装（#169）で、別のディレクトリ（`viewer/`）の実装に置き換わった。Viewerは、PyPIの配布物には含まれない（`pyproject.toml`が`packages`を明示しているため）。
