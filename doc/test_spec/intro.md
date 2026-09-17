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

# 対象外の範囲

以下は実機・外部プロセスへの依存が強く、モック化のコストが見合わないため、意図的にテスト対象外としている。

- Mermaid/PlantUML/Graphviz/D2の実際のレンダリング結果そのもの（ヘッドレスブラウザ・Java・`dot`コマンド・D2 CLIが必要なため）。
- Typstコンパイル自体を要する統合テスト（`typst`パッケージがある環境でのみ実行可能なため）。

# 今後の課題

CI（GitHub Actions）への組み込みは、本書が対象とする範囲には含めない。#96で別issueとして切り出す方針にしている。
