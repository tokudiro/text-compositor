# 目的・範囲

本書は、`tests/`配下にあるリグレッションテストの仕様書である。何を、どの範囲まで、どのような方針でテストしているかを記録する。テスト対象となるコードの詳細な設計・実装意図は`doc/spec.md`を参照する。

これまで本プロジェクトには自動テストが一切なかった。行番号マッピング機能（[#27](https://github.com/tokudiro/text-compositor/issues/27)）の実装で、初めて`tests/`・pytest・`requirements-dev.txt`という土台を作った。その後、主要機能全体へテストを広げる作業（[#96](https://github.com/tokudiro/text-compositor/issues/96)）を行い、本書もそのときに作成した。

実装時の想定と実機での挙動がずれることは珍しくない。実際、#27の実装では実機で動かして初めて気づいたバグが2件あった。#96の作業でも、テストを書く過程で新たなバグを1件見つけた（layout-right等のレイアウトブロック内で実際の図表フェンスが常に検出失敗する不具合、[#127](https://github.com/tokudiro/text-compositor/issues/127)）。次章のテストケース一覧は、こうしたズレを機械的に検知するためのものである。

# 実行方法

開発時専用の依存関係（`requirements-dev.txt`）をインストールしたうえで、`tests/`配下のテストを実行する。

```bash
pip install -r requirements-dev.txt
pytest tests/
```

# 実施結果の作り方

テストケース一覧の表は、仕様（`testcases/`）と、実施結果（`testresults/`）を、`id`で突き合わせた1つの表である（`aggregate`の`join`、[#66](https://github.com/tokudiro/text-compositor/issues/66)）。表の下に、結果ごとの件数と、優先度別の合格率を出す。

結果ファイルは、次のスクリプトが、pytestの実行結果から作る。ケースごとに1ファイルを上書きし、履歴はGitに任せる。

```bash
python doc/test_spec/make_results.py
```

各ケースの`tests`に書いたpytestのクラスを集計して、全て成功なら`OK`、1つでも失敗なら`NG`、対応するテストが無い（全てskipを含む）なら`未実施`とする。実行済みのJUnit XMLから作るときは、`--junit`を使う。

ケースの手順や期待結果を変えたときは、そのケースの`rev`を1つ上げる。結果の`spec_rev`が仕様の`rev`と違うと、表の「結果」が「要再実施」になる。`make_results.py`を実行し直せば、結果の`spec_rev`が更新される。

# 対象外の範囲

以下は実機・外部プロセスへの依存が強く、モック化のコストが見合わないため、意図的にテスト対象外としている。

- PlantUML/D2の実際のレンダリング結果そのもの（Java・D2 CLIが必要なため）。
- 実際のブラウザで描く図（Mermaid・Vega・WaveDrom・Bytefield）のテストは、`playwright`がある環境でのみ実行し、無ければ飛ばす。CIでは、`ubuntu-latest`標準搭載のChromeを使って、毎回実行する。
- Typstコンパイル自体を要する統合テスト（`typst`パッケージがある環境でのみ実行可能なため）。

# CIでの実行

`.github/workflows/test.yml`が、`text_compositor/`・`tests/`・依存関係を変更したpush・PRで、`pytest tests/`を実行する（#97）。`doc/`や`sample/`だけの変更では、起動しない。
