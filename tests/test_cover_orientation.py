"""表紙の用紙と向きが、本文と同じになること（#636）のテスト。

以前は、template.typの表紙が、A4縦に固定されていて、A4横（`document.landscape: true`）の文書で、
表紙だけが縦になった。テンプレートを、Typstで実際にコンパイルして、ページの大きさを確かめる。"""
import os
import re
import shutil

import pytest
import typst

import text_compositor.build as build

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(build.__file__)), "templates")
A4 = (595.2756, 841.8898)
A3 = (841.8898, 1190.5512)
A5 = (419.5276, 595.2756)


def page_sizes(tmp_path, template, args, body_pages=1):
    """表紙つきで、本文のページを、body_pages枚、組んで、各ページの(幅, 高さ)をptで返す。"""
    for name in (template, "_common.typ"):
        shutil.copy(os.path.join(TEMPLATES, name), tmp_path / name)
    main = tmp_path / "main.typ"
    body = "\n#pagebreak()\n".join(["本文"] * body_pages)
    main.write_text(
        f'#import "{template}": conf\n#show: doc => conf(title: "T", subtitle: "S", author: "A", date: "D", cover: true, {args}doc)\n{body}\n',
        encoding="utf-8")
    sizes = []
    for svg in typst.compile(str(main), format="svg"):
        m = re.search(r'<svg[^>]*width="([\d.]+)pt" height="([\d.]+)pt"', svg.decode())
        sizes.append((float(m.group(1)), float(m.group(2))))
    return sizes


def approx(size, expected):
    return size == pytest.approx(expected, abs=0.5)


class TestCoverFollowsThePaper:
    def test_default_is_a4_portrait(self, tmp_path):
        cover, body = page_sizes(tmp_path, "template.typ", "")
        assert approx(cover, A4) and approx(body, A4)

    def test_landscape_makes_the_cover_landscape_too(self, tmp_path):
        cover, body = page_sizes(tmp_path, "template.typ", "landscape: true, ")
        assert approx(cover, A4[::-1])
        assert approx(body, A4[::-1])

    @pytest.mark.parametrize("paper, size", [("a3", A3), ("a5", A5)])
    def test_paper_size_applies_to_the_cover(self, tmp_path, paper, size):
        cover, body = page_sizes(tmp_path, "template.typ", f'paper_size: "{paper}", ')
        assert approx(cover, size) and approx(body, size)

    def test_paper_size_and_landscape_together(self, tmp_path):
        cover, body = page_sizes(tmp_path, "template.typ", 'paper_size: "a3", landscape: true, ')
        assert approx(cover, A3[::-1]) and approx(body, A3[::-1])

    def test_binding_margin_does_not_change_the_cover_size(self, tmp_path):
        cover, body = page_sizes(tmp_path, "template.typ", 'landscape: true, binding_margin: 1cm, binding_side: left, ')
        assert approx(cover, A4[::-1]) and approx(body, A4[::-1])


class TestSlideCoverStillFollowsThePaper:
    """スライド用テンプレートは、元から表紙も用紙・向きに従う（#18）。変わっていないことを確かめる。"""

    def test_slide_cover_and_body_have_the_same_size(self, tmp_path):
        cover, body = page_sizes(tmp_path, "slide.typ", "landscape: true, ")
        assert approx(cover, body)
