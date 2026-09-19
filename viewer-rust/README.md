# viewer-rust（Issue #99 スパイク）

Rust + [PyO3](https://pyo3.rs/) で、`build.py` の `TypstRenderer.render()`（Markdown文字列→
Typstコード文字列の変換）を埋め込み呼び出しできるかを確認するだけの最小疎通確認（スパイク）。
ファイル監視・Typstコンパイル・PDF表示・GUI本体は範囲外。詳細は
[Issue #99](https://github.com/tokudiro/context-compositor/issues/99) を参照。

## 前提

- リポジトリ直下の `requirements.txt` の依存パッケージ（`markdown-it-py` 等）がインストール済みの
  Pythonが必要（`build.py` を `import` するため）。
- PyO3はビルド時に `PYO3_PYTHON` 環境変数（未指定時はPATH上の `python3`）が指す Python の
  ヘッダ・共有ライブラリ情報を使ってリンクする。実行時も同じPythonのインタプリタが埋め込まれる。

```bash
python3 -m venv /path/to/venv
/path/to/venv/bin/pip install -r ../requirements.txt
```

## ビルド・実行

```bash
cd viewer-rust
PYO3_PYTHON=/path/to/venv/bin/python3 cargo build

# 実行時、依存パッケージ（markdown-it-py等）のsite-packagesをPYTHONPATHへ通す。
# 埋め込まれるPythonの標準ライブラリ探索が環境依存（Microsoft Store版Python等）で崩れる場合は
# PYTHONHOME等の追加調整が必要になる可能性がある（下記「検証結果」参照）。
PYTHONPATH="$(/path/to/venv/bin/python3 -c 'import site; print(site.getsitepackages()[0])')" \
  ./target/debug/viewer-rust
```

固定のサンプルMarkdown文字列を `TypstRenderer.render()` に渡し、変換結果のTypstコードを
標準出力へ表示するだけのプログラム（`src/main.rs`）。

Windows実機での具体的な手順は「検証結果（Windows実機）」を参照。要点だけ書くと、
ビルド時は`PYO3_PYTHON`をMicrosoft Store版Pythonに向け、実行時は組込版Python一式を
exeと同じフォルダに展開する（`PYTHONHOME`は未設定なら自動検出される）。

## 検証結果（Linux・開発機ではないサンドボックス環境）

- `TypstRenderer.render()` の呼び出し・戻り値の受け取り・表示は問題なく動作した。
- プロセスは正常終了する（exit code 0）。GIL解放やインタプリタの後始末で固まる事象は見られなかった。
- 開発機のMicrosoft Store版Pythonでの検証はしていない（本スパイクをLinux上で作成したため）。
  Windows + Microsoft Store版Pythonでビルド・実行して同様に動作するかは別途確認が必要
  （`PYO3_PYTHON` をStore版Pythonの `python.exe` に向けてビルドし直す想定）。

## 検証結果（Windows実機）

開発機（Windows 11、Microsoft Store版Python 3.10）で実際にビルド・実行して検証した。

### ビルド時: Store版Pythonが必要

PyO3はビルド時にPythonの開発用インポートライブラリ（`.lib`）を必要とするが、
[viewer-csharp](../viewer-csharp/)で使っている組込版Python（embeddable package）には
`.lib`が同梱されていない。Microsoft Store版Pythonには
`libs/python310.lib`が存在するため、`PYO3_PYTHON`をStore版の`python.exe`に向けることで
ビルド自体は成功した（`Runtime.PythonDLL`のような実行時のDLLパス上書きAPIがpythonnetには
あるがPyO3にはないため、ビルド時に使うPythonと実行時に使うPythonが別でも問題ない）。

### 実行時: そのままではStore版のDLLロードに失敗する

ビルドしたexeをそのまま実行すると、`STATUS_DLL_NOT_FOUND`（exit code -1073741515）で
失敗した。Store版Pythonの`python310.dll`は`C:\Program Files\WindowsApps\...`配下にあり、
実行ファイルのフォルダにもPATHにも含まれないため、Windowsの標準DLL検索順序では
見つからない（[viewer-csharp](../viewer-csharp/)で確認した「Store版DLLはアクセス拒否で
ロードできない」問題とは別に、そもそも見つからないという問題がまず先に起きる）。

### 解決策: 組込版Pythonをexeと同じフォルダに配置

[viewer-csharp](../viewer-csharp/)で使った組込版Python一式（`python310.dll`,
`python310.zip`, `site-packages`等）を、**実行ファイルと同じフォルダに直接展開**した
ところ、Store版のアクセス拒否問題を回避しつつ正常動作した。

- C#版（pythonnet）は`Runtime.PythonDLL`にフルパスを渡せるため、`python-embed/`という
  独立したサブフォルダに隔離して配置できた。
- Rust版（PyO3）にはそのような実行時のDLLパス指定APIがなく、`python310.dll`自体が
  Windowsの標準DLL検索順序（実行ファイルと同じフォルダが最優先）でロードされるため、
  **組込版Pythonの中身を実行ファイルと同じフォルダに直接展開する必要がある**（サブ
  フォルダには隔離できない）。
- `PYTHONHOME`をこの展開先ディレクトリに向けることで、標準ライブラリ（`python310.zip`）
  やsite-packagesが正しく解決された。`PYTHONHOME`未指定のままだと、実行ファイルの
  ディレクトリを基準に`<exe_dir>/pythonXY.zip`を探そうとして見つからず、
  `ModuleNotFoundError: No module named 'encodings'`で初期化に失敗した。

### 環境変数なしでの実行（exeからの自動検出）

[src/main.rs](src/main.rs)に、`PYTHONHOME`が未指定なら実行ファイルと同じフォルダを
自動検出するロジック（`set_default_python_home_if_unset`）を追加した。これにより、
環境変数を一切設定せずに`.\target\debug\viewer-rust.exe`を実行するだけで動作するように
なった。2回連続で正常終了（exit code 0、プロセスの残留なし）を確認済み。

**結論**: Rust版もWindows実機でMicrosoft Store版Pythonの制約を回避して動作させられる
ことを確認した。ただしC#版と異なり、ビルド時（Store版Pythonの`.lib`が必要）と実行時
（組込版Pythonのdll一式が必要、exeと同じフォルダに直接展開）で異なるPython配置を
使う点、およびC#版のような「exeの隣にpython-embed/サブフォルダ」という統一的な配置が
そのままでは使えない点が、C#版との構成上の違いとして分かった。

## 次のステップ（本issueの範囲外）

Issue #99本文の「次のステップ」を参照。
