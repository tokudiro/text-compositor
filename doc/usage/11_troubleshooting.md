# よくあるエラー

| メッセージ | 原因と対処 |
| --- | --- |
| `Config file not found` | `--config` のパスが誤っているか、カレントディレクトリに `text-compositor.config.yaml`/`.json` が無い |
| `Template not found` | `template.path` の値が同梱テンプレート名（`.typ`なし）でも独自テンプレートのパス（`.typ`あり）でも見つからない。綴りミスを確認 |
| `Chapter file not found` | `chapters` に書いたファイル名が `inputs.dir` 配下に存在しない |
| `Image not found` | Markdown内で参照している画像がそのMarkdownファイルからの相対パスで見つからない |
| `'typst-exec' is allowed only under a 'reviewed/' directory` | `typst-exec`ブロックを `reviewed/` 配下以外のファイルで使った |
| `The 'playwright' package is required for mermaid rendering` | Mermaid図があるのに`playwright`パッケージが未インストール（`pip install playwright==1.62.0`） |
| `No system Chrome/Edge found` | Mermaid図があるのにChrome/Edgeが未インストール |

## 詳しい状況を見たい場合

エラーメッセージだけでは原因が分からない場合、`-v`/`--verbose`を付けて再実行すると、処理中の章やキャッシュの再利用状況など詳しいログが出ます。生成されたTypstコード自体を確認したい場合は`--keep-temp`を付けると、ビルド成功時も`.text-compositor/temp_build.typ`（中間生成物）が削除されずに残ります（失敗時は元々常に残ります）。
