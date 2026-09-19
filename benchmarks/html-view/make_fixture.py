"""計測用の固定のHTML（fixture/index.html）を作る（#180）。

`fixture/fixture.md`を、`render_html`でHTMLにする。生成物（HTMLと、図・画像のファイル）は、リポジトリに
含める。計測する人が、Mermaid用のブラウザなどを用意しなくても、同じ入力で測れるようにするため。
`.text-compositor/cache/`は、gitの対象外なので、参照している図を、`fixture/assets/`へ写し、HTMLの参照先を直す。
あわせて、他のツール（Arto・Shiba・mo）に開かせる、標準のGFMだけの原稿（`fixture-gfm.md`）も作る。

    python benchmarks/html-view/make_fixture.py
"""
import os
import re
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixture")
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from text_compositor import render_html  # noqa: E402


def write_png(path, width=240, height=120):
    """標準ライブラリだけで作る、グラデーションのPNG。"""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row += bytes((40 + x * 200 // width, 90 + y * 120 // height, 200 - x * 120 // width))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def to_gfm(text):
    """他のツール（Arto・Shiba・mo）に開かせるため、text-compositor独自の記法を、標準のGFMに直す。
    `:::`ブロックの囲みと、`[text]{...}`の属性、画像の`|width=`等を取り除く。"""
    text = re.sub(r"^:::.*\n", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\{[^}]*\}", r"\1", text)
    text = re.sub(r"!\[([^|\]]*)\|[^\]]*\]", r"![\1]", text)
    return text


def main():
    with open(os.path.join(FIXTURE, "fixture.md"), encoding="utf-8") as f:
        gfm = to_gfm(f.read())
    with open(os.path.join(FIXTURE, "fixture-gfm.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(gfm)

    assets = os.path.join(FIXTURE, "assets")
    if os.path.isdir(assets):
        shutil.rmtree(assets)
    os.makedirs(assets)
    write_png(os.path.join(assets, "photo.png"))

    md = os.path.join(FIXTURE, "fixture.md")
    out = os.path.join(FIXTURE, "index.html")
    result = render_html(md, out, plugins={"plantuml": False, "d2": False})
    for d in result.diagnostics:
        if d.severity in ("error", "warning"):
            print(f"[{d.severity}] {d.file}:{d.line}: {d.message}")
    if not result.ok:
        sys.exit(1)

    with open(out, encoding="utf-8") as f:
        html = f.read()
    cache = os.path.join(FIXTURE, ".text-compositor", "cache")

    def move(match):
        name = os.path.basename(match.group(1))
        shutil.copy(os.path.join(cache, name), os.path.join(assets, name))
        return f'src="assets/{name}"'

    html = re.sub(r'src="\.text-compositor/cache/([^"]+)"', lambda m: move(m), html)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    shutil.rmtree(os.path.join(FIXTURE, ".text-compositor"))
    print(f"wrote {out} ({os.path.getsize(out)} bytes), assets: {sorted(os.listdir(assets))}")


if __name__ == "__main__":
    main()
