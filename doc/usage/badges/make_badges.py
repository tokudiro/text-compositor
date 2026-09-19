"""ドキュメントの記法の種別を示す、GitHubのラベルのようなバッジ（SVG）を作る（#216）。

    python doc/usage/badges/make_badges.py

外部のサービス（shields.ioなど）に頼らず、リポジトリの中のSVGを、Markdownから参照する。GitHubでも、Obunzuでも、
そのまま表示される。使い方ガイドのPDF（Typst）も、--rootがdoc/usageのため、doc/usageの外の画像を読めない。そのため、このフォルダに置く。
文字は白で、背景色は、白い文字とのコントラスト比が4.5:1以上（WCAG 2.1のAA）になる色にする。
"""
import os
import sys

# (ファイル名, 表示する文字, 背景色, 意味)
BADGES = [
    ("commonmark", "CommonMark", "#57606a", "標準のMarkdown記法"),
    ("gfm", "GFM", "#953800", "GitHub Flavored Markdown記法"),
    ("text-compositor", "text-compositor", "#1a7f37", "text-compositorの拡張記法。または、上の記法のうち、PDF出力できるもの"),
    ("obunzu", "Obunzu", "#0078d4", "Obunzuの拡張記法。または、上の記法のうち、HTML出力（Obunzu）できるもの"),
    ("marp", "Marp", "#8250df", "Marp記法"),
]

HEIGHT = 22
PADDING = 10
CHAR_WIDTH = 7.4     # 12 pxの太字（sans-serif）の、1文字の幅の見積もり。textLengthで、実際の幅を、これに合わせる。


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(color):
    return 1.05 / (luminance(color) + 0.05)


def svg(text, color, meaning):
    text_width = round(len(text) * CHAR_WIDTH)
    width = text_width + PADDING * 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" viewBox="0 0 {width} {HEIGHT}" role="img" aria-label="{text}">\n'
        f'  <title>{text}: {meaning}</title>\n'
        f'  <rect width="{width}" height="{HEIGHT}" rx="{HEIGHT // 2}" fill="{color}"/>\n'
        f'  <text x="{width / 2:g}" y="15" fill="#ffffff" font-family="-apple-system, \'Segoe UI\', \'Noto Sans\', Helvetica, Arial, sans-serif" '
        f'font-size="12" font-weight="600" text-anchor="middle" textLength="{text_width}" lengthAdjust="spacingAndGlyphs">{text}</text>\n'
        f'</svg>\n'
    )


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    failed = False
    for name, text, color, meaning in BADGES:
        ratio = contrast_with_white(color)
        if ratio < 4.5:
            print(f"NG  {name}: {color} のコントラスト比が {ratio:.2f} で、4.5未満です")
            failed = True
            continue
        with open(os.path.join(here, f"{name}.svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(svg(text, color, meaning))
        print(f"OK  {name}.svg  {color}  コントラスト比 {ratio:.1f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
