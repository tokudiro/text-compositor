"""PDFのフォント埋め込みの検証（#320）。

生成したPDFの、すべてのフォントが、PDFの中に埋め込まれている（サブセット化されている）ことを確かめる。
埋め込まれていないフォントがあると、閲覧する環境に、そのフォントが無いとき、見た目が変わる（文字化け・字体の置き換え）。

TypstのPDFは、フォントの辞書を、平文（圧縮しない）で書くため、追加のツール（pdffonts等）なしで、読める。
フォントは、システムのものを使わず（`ignore_system_fonts=True`、#71）、同梱のNoto Sans JPと、Typst内蔵のフォントだけを使う。
"""
import re
import sys

import pytest

import text_compositor.build as build_mod
from text_compositor import log

@pytest.fixture(autouse=True)
def _restore_verbosity():
    """`build()`は、-q/-vを、プロセスグローバルへ反映する。他のテストへ、残さない（残すと、後の警告の検査が落ちる）。"""
    yield
    log.set_verbosity(False, False)


# 本文・見出し・太字・斜体・コード（等幅）・数式・表・Graphviz・SVGの文字を含む、1つの文書。
# Mermaid・PlantUML・D2は、ブラウザ・Java・外部の実行ファイルが要るため、含めない（PDFに入る文字は、同じ経路のため）。
DOCUMENT = """# フォント埋め込みの検証

## 本文と装飾

通常の本文です。**太字**、*斜体*、***太字の斜体***、`インラインコード（日本語）`。

記号: → ✓ ★ ① ≠ ∞ ± × ÷。ラテン: café。ギリシャ・キリル: αβγ Привет。

```python
# 日本語のコメント
def greet(name):
    return f"こんにちは、{name}"
```

数式: $E = mc^2$

| 名前 | 説明 |
| --- | --- |
| りんご | 赤い果物 |

```dot
digraph G { 開始 -> 処理 -> 終了; }
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="240" height="60"><text x="10" y="35" font-family="Arial" font-size="20">SVG text 日本語</text></svg>
```
"""

# フォントの辞書: `N 0 obj <</Type/FontDescriptor/FontName/ABCDEF+名前/.../FontFile3 N 0 R>>`
DESCRIPTOR = re.compile(rb"<<(?:(?!>>).)*?/Type\s*/FontDescriptor(?:(?!>>).)*?>>", re.S)
FONT_NAME = re.compile(rb"/FontName\s*/([^/\s>]+)")
FONT_FILE = re.compile(rb"/FontFile[23]?\s+\d+\s+\d+\s+R")
SUBSET_TAG = re.compile(rb"^[A-Z]{6}\+")


def font_descriptors(pdf: bytes):
    """PDFの、フォントの辞書ごとに、(フォント名, 埋め込まれているか)を返す。"""
    result = []
    for match in DESCRIPTOR.finditer(pdf):
        body = match.group(0)
        name = FONT_NAME.search(body)
        result.append((name.group(1) if name else b"(no name)", FONT_FILE.search(body) is not None))
    return result


def test_font_descriptors_reads_the_embedded_flag():
    """読み取りの部品そのもの: 埋め込みのあるものと、無いもの（標準14フォントの参照など）を、区別できる。"""
    embedded = b"5 0 obj\n<</Type/FontDescriptor/FontName/ABCDEF+NotoSansJP-Regular/Flags 4/FontFile3 9 0 R>>\nendobj\n"
    missing = b"6 0 obj\n<</Type/FontDescriptor/FontName/Helvetica/Flags 32>>\nendobj\n"
    other = b"7 0 obj\n<</Type/Font/Subtype/Type0/BaseFont/ABCDEF+X>>\nendobj\n"
    assert font_descriptors(embedded + missing + other) == [(b"ABCDEF+NotoSansJP-Regular", True), (b"Helvetica", False)]


def test_every_font_in_a_real_pdf_is_embedded_and_subset(tmp_path, monkeypatch):
    from text_compositor.deps import ensure_fonts
    try:
        ensure_fonts()
    except SystemExit:
        pytest.skip("fonts are not available")
    md = tmp_path / "fonts.md"
    md.write_text(DOCUMENT, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["text-compositor", str(md), "-q"])
    build_mod.build()
    pdf = (tmp_path / "fonts.pdf").read_bytes()

    fonts = font_descriptors(pdf)
    assert fonts, "no font is found in the PDF"
    names = [name.decode("latin1") for name, _ in fonts]
    not_embedded = [name for name, embedded in fonts if not embedded]
    assert not not_embedded, f"fonts that are not embedded: {not_embedded} (all: {names})"
    not_subset = [name for name, _ in fonts if not SUBSET_TAG.match(name)]
    assert not not_subset, f"fonts that are not subset (no ABCDEF+ tag): {not_subset} (all: {names})"
    # 日本語の本文・見出しは、同梱のNoto Sans JPで出る（システムのフォントに、置き換わらない）
    assert any(b"NotoSansJP" in name for name, _ in fonts), names
