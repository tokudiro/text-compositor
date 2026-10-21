"""PDFのコードブロックの装飾（#511）。

コードブロック（Typstの`raw`の`block: true`）を、背景つきの枠で包む。包む処理は、テンプレートのshowルールではなく、
ここ（Pythonが、Typstのコードを出すとき）で行う。理由: Typstのshowルールは、重ねがけされる（外側と内側の
`show raw.where(block: true)`が、両方効く。実測）。章ごとの上書きを、章の中のshowルールで実現すると、テンプレートの
ルールと重なって、背景が二重になる。Pythonで包めば、どのテンプレート（独自テンプレートを含む）でも、同じに動く。
"""

# コードの等幅フォント。Noto Sans Mono CJK JP（deps.pyが取得する）は、コードの中の日本語も、半角の2倍の幅に揃える。
# 取得できなかったときのために、Typst内蔵のDejaVu Sans Monoを、2番目に置く。
# 同梱テンプレートの`_common.typ`の`code-font`と、同じ値（tests/test_code_block_style.pyが確かめる）。
CODE_FONTS = ("Noto Sans Mono CJK JP", "DejaVu Sans Mono")

# 背景は、HTML出力の`--code-bg`（ライトテーマ）と同じ。枠線は、既定では付けない（HTML出力と同じ）。
BACKGROUND = "#f6f8fa"
INSET = "0.6em"
RADIUS = "3pt"


def wrap_code_block(raw_typst):
    """`#raw(..., block: true)`のTypstコードを、背景つきの枠と、等幅フォントで包んだコードにする。
    `raw`の既定のフォントは、要素の組み込みの指定のため、外側の`text(font: ...)`では上書きできない。
    そのため、`show raw: set text(font: ...)`を置く（`set`は、重ねがけの問題がない）。
    枠は、`block(...)`でrawを包むのではなく、内容のブロックの中の、局所のshowルールで付ける。`block`で包むと、
    枠の高さが2.5 pt大きくなる（実測）ため。局所のshowルールは、同梱テンプレートに、同じルールがないため、重ならない
    （独自テンプレートが、`raw`のブロックにshowルールを持つときは、重なる。その場合は、`code_block: false`で無効にする）。"""
    fonts = ", ".join(f'"{name}"' for name in CODE_FONTS)
    return (
        f'#[\n'
        f'#show raw: set text(font: ({fonts}))\n'
        f'#show raw.where(block: true): it => block(width: 100%, fill: rgb("{BACKGROUND}"), inset: {INSET}, radius: {RADIUS}, it)\n'
        f'{raw_typst}\n'
        f']\n\n'
    )
