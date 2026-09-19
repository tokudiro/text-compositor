# Pythonから使う（API・常駐ワーカー）

単一のMarkdownファイルを、`config.yaml`なしでPDF（実験的にHTMLも）にするAPIがあります（[#167](https://github.com/tokudiro/text-compositor/issues/167)）。エディタやGUIのプレビューのように、同じ原稿を何度もビルドする用途を想定しています。

## 使い方

```python
from text_compositor import Session, build_markdown

# 1回だけ
result = build_markdown("doc.md", "out/doc.pdf")

# 繰り返す（Mermaidのブラウザなどを使い回すため、2回目以降が速い）
with Session() as session:
    result = session.build("doc.md", "out/doc.pdf")
    if result.ok:
        print("PDF:", result.pdf_path)
    for d in result.diagnostics:
        print(d.severity, d.message, d.file, d.line)
```

- **戻り値**（`BuildResult`）: `ok`（成否）・`pdf_path`・`diagnostics`（警告・エラー・ヒント・情報の一覧）・`timings_ms`（`total`・`render`・`compile`）。失敗しても、例外は出ず、`ok=False`で返ります。
- **診断**（`Diagnostic`）: `severity`（`error`・`warning`・`hint`・`info`）・`message`・`file`・`line`・`detail`。`file`と`line`は、元のMarkdownの位置で、分かる場合だけ入ります。Typstのコンパイルエラーは、Markdownの行に対応付けられます。
- **標準出力へは何も出ません**。診断は、戻り値で受け取ります。

## 引数

| 引数 | 説明 |
| --- | --- |
| `markdown_path` | 対象のMarkdownファイル。画像などの相対パスは、このファイルの場所が基準です。 |
| `output_pdf` | 出力先。省略すると、原稿の隣の`.text-compositor/preview.pdf`です。 |
| `template` | 同梱テンプレートの名前（`template`・`slide`・`paper`）、または`.typ`ファイルのパス。 |
| `plugins` | 図表プラグインの有効・無効。例: `{"mermaid": False, "plantuml": False}` |
| `document` | `document:`の上書き。例: `{"toc": True, "title": "仕様書"}` |
| `variables` | `{{KEY}}`の置換表 |
| `config` | config全体への上書き（上級者向け） |
| `keep_temp` | 成功時も、中間ファイルを残します（デバッグ用）。 |

既定の`document`は、`title`がファイル名、`cover`が`markdown`です（テンプレートの表紙を出さず、Markdownの先頭のH1もそのまま出します）。CLIの既定の`cover: none`は、先頭のタイトルを落とすため、プレビューには向きません。

## 注意

- 原稿の隣に、作業用の`.text-compositor/`（図表のキャッシュ・中間ファイル）を作ります。`outputs/`は作りません。
- PDFは、一時ファイルへ書いてから置き換えます。読んでいる側が、書きかけのPDFを見ることはありません。**Windowsでは、開いたままのPDFへは置き換えられません**。PDFを全体を読んで閉じるか、ビルドごとに別の出力先を指定してください。
- `Session`は、使い終わったら`close()`します（`with`を使うと自動です）。Mermaidのブラウザなどを片付けます。

## HTMLにする（実験的）

Markdownを、PDFではなく、HTMLと図の画像にすることもできます（[#161](https://github.com/tokudiro/text-compositor/issues/161)）。図（Mermaid・PlantUML・D2・`svg`）は、PDFと同じ仕組みで画像にして、HTMLから参照します。

```python
from text_compositor import Session, render_html

result = render_html("doc.md", "out/doc.html")    # 1回だけ
with Session() as session:                        # 繰り返す
    result = session.render_html("doc.md")        # 出力先の既定: 原稿の隣の .text-compositor/preview.html
    print(result.ok, result.html_path)
```

- 引数は、`output_html`（出力先）・`plugins`・`variables`・`config`です（`template`・`document`は、ありません）。戻り値は、`HtmlResult`（`ok`・`html_path`・`diagnostics`・`timings_ms`・`dependencies`）です。`dependencies`は、原稿が参照しているローカルのファイル（画像など）で、変更を検知して自動で更新する側が使います。
- 出力は、外部のCSSやJavaScriptを使わない、1ファイルのHTMLです。画像と図は、HTMLからの相対パスで参照します。
- **PDFとの違い**: 用紙サイズ・改ページ・ヘッダなど、ページにだけ意味を持つ指定は、無視します（診断は、警告ではなく`info`です）。画像が見つからなくても、警告にとどめて、続けます。`:::`のレイアウトブロックは、近い見た目のCSSで表示します。
- **未対応**: Graphviz（`dot`）・`typst-exec`・生のHTMLは、内容をコードブロックで表示して、警告します。数式と、複数ファイルの出力は、ありません。
- 実験的な機能です。HTMLの構造やAPIは、変わる可能性があります。詳しくは、仕様書（`doc/spec.md`）の「14. Python APIと常駐ワーカー」を参照してください。

## 常駐ワーカー

別のプロセス（GUIなど）から使う場合は、常駐ワーカーを起動します。標準入力へJSONを1行ずつ書くと、標準出力へ、JSONの応答が1行ずつ返ります（UTF-8）。

```bash
python -m text_compositor.worker
```

```json
{"event": "ready", "protocol": 1, "version": "0.3.0"}
```

依頼と応答の例です。

```json
{"id": 1, "method": "build", "params": {"path": "C:/docs/doc.md", "output": "C:/tmp/doc.pdf", "plugins": {"mermaid": false}}}
{"id": 1, "ok": true, "pdf": "C:/tmp/doc.pdf", "diagnostics": [], "timings_ms": {"render": 9.1, "compile": 31.4, "total": 42.0}}
```

- **メソッド**: `build`（`params`はAPIの引数と同じ。`path`は必須）・`render_html`（実験的。前節）・`ping`・`shutdown`。
- **ビルドの失敗**は、`"ok": false`と`diagnostics`で返ります。**プロトコルの誤り**（JSONでない、未知のメソッド、引数の不足）は、`error`キーで返り、その依頼は処理されていません。
- ビルド中の出力が、通信を壊すことはありません。詳しい仕様は、仕様書（`doc/spec.md`）の「14. Python APIと常駐ワーカー」を参照してください。
