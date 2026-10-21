"""ギャラリー（doc/usage/*_gallery_*.md）の、図のコードの併記のテスト。

各図の直前に、同じコードを`text`のコードブロックで書き写している（読み手が、図を描くコードを見られるように）。
原稿の二重書きなので、片方だけ直して食い違わないことを、ここで確かめる。"""
import re
from pathlib import Path

USAGE = Path(__file__).resolve().parent.parent / "doc" / "usage"
GALLERIES = sorted(USAGE.glob("*_gallery_*.md"))

# 図のフェンス（3本）と、その直前の書き写し（4本の`text`）を、順に拾う
BLOCK = re.compile(r"^(`{3,4})(\S+)\n(.*?)^\1\n", re.S | re.M)


def _blocks(text):
    return [(m.group(2), m.group(3)) for m in BLOCK.finditer(text)]


def test_the_gallery_chapters_exist():
    assert len(GALLERIES) == 13


def test_every_figure_is_preceded_by_a_copy_of_its_code():
    for gallery in GALLERIES:
        blocks = _blocks(gallery.read_text(encoding="utf-8"))
        assert blocks, gallery.name
        assert len(blocks) % 2 == 0, f"{gallery.name}: unpaired block"
        for i in range(0, len(blocks), 2):
            (copy_lang, copy_code), (lang, code) = blocks[i], blocks[i + 1]
            assert copy_lang == "text", f"{gallery.name}: block {i // 2 + 1} is not a text copy"
            assert copy_code == code, f"{gallery.name}: block {i // 2 + 1} ({lang}) differs from its copy"
