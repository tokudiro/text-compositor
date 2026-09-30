"""PDFのメタデータ（プロパティ）の検証（#317）。

`document:`のtitle・subtitle・author・dateが、PDFのTitle・Subject・Author・作成日に入ることを、3つのテンプレート
（template・paper・slide）で確かめる。TypstのPDFは、情報の辞書を平文で書くため、追加のツールなしで読める
（フォントの検証（test_pdf_fonts.py）と同じ方法）。
"""
import re
import sys

import pytest

import text_compositor.build as build_mod
from text_compositor import log

TEMPLATES = ["template", "paper", "slide"]


@pytest.fixture(autouse=True)
def _restore_verbosity():
    """`build()`は、-q/-vを、プロセスグローバルへ反映する。他のテストへ、残さない。"""
    yield
    log.set_verbosity(False, False)


def pdf_info(pdf: bytes) -> dict:
    """PDFの情報の辞書（`/Creator(Typst ...)`を持つ辞書）から、Title・Author・Subject・CreationDateを読む。
    文字列は、UTF-16BEの16進（`<FEFF...>`）か、括弧で囲んだ文字列。ブックマークの`/Title`とは、別の辞書のため、混ざらない。"""
    match = re.search(rb"<<(?:(?!>>).)*?/Creator\(Typst(?:(?!>>).)*?>>", pdf, re.S)
    assert match, "the document information dictionary is not found"
    body = match.group(0)
    info = {}
    for key in (b"Title", b"Author", b"Subject", b"CreationDate"):
        found = re.search(rb"/" + key + rb"(?:<FEFF([0-9A-Fa-f]*)>|\(([^)]*)\))", body)
        if found:
            info[key.decode()] = (bytes.fromhex(found.group(1).decode()).decode("utf-16-be") if found.group(1) is not None
                                  else found.group(2).decode("latin1"))
    return info


def build_pdf(tmp_path, monkeypatch, template, document):
    from text_compositor.deps import ensure_fonts
    try:
        ensure_fonts()
    except SystemExit:
        pytest.skip("fonts are not available")
    (tmp_path / "a.md").write_text("# 本文\n\nこんにちは。\n", encoding="utf-8")
    lines = ["document:"] + [f'  {key}: "{value}"' for key, value in document.items()]
    lines += ["output:", '  filename: "out.pdf"', '  dir: "."', "template:", f'  path: "{template}"',
              "inputs:", '  dir: "."', "chapters:", '  - "a.md"']
    config = tmp_path / "config.yaml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["text-compositor", "--config", str(config), "-q"])
    build_mod.build()
    return (tmp_path / "out.pdf").read_bytes()


def test_pdf_info_reads_hex_and_literal_strings():
    """読み取りの部品そのもの: UTF-16の16進の文字列と、括弧の文字列を読み、ブックマークの/Titleは、読まない。"""
    pdf = (b"2 0 obj\n<</Parent 3 0 R/Title<FEFF672C6587>/Dest 9 0 R>>\nendobj\n"
           b"20 0 obj\n<</Title(Plain)/Author<FEFF5C717530>/Creator(Typst 0.15.0)/CreationDate(D:20260814000000Z)>>\nendobj\n")
    assert pdf_info(pdf) == {"Title": "Plain", "Author": "山田", "CreationDate": "D:20260814000000Z"}


@pytest.mark.parametrize("template", TEMPLATES)
def test_document_values_are_written_to_the_pdf_properties(tmp_path, monkeypatch, template):
    pdf = build_pdf(tmp_path, monkeypatch, template,
                    {"title": "テスト文書", "subtitle": "副題です", "author": "山田 太郎", "date": "2026-08-14"})
    info = pdf_info(pdf)
    assert info["Title"] == "テスト文書"
    assert info["Subject"] == "副題です"
    assert info["Author"] == "山田 太郎"
    assert info["CreationDate"].startswith("D:20260814"), info


def test_a_free_form_date_keeps_the_build_time(tmp_path, monkeypatch):
    """dateが、YYYY-MM-DDでない（自由な文字列。例: 「2026年8月版」）とき、作成日は、従来どおり、ビルドの日時になる（表紙には、文字列のまま出る）。
    title・author・subtitleを書かないときは、設定の既定値（config.pyのDEFAULT_CONFIG。表紙と同じ値）が、そのまま入る。"""
    pdf = build_pdf(tmp_path, monkeypatch, "template", {"date": "2026年8月版"})
    info = pdf_info(pdf)
    assert "CreationDate" in info and not info["CreationDate"].startswith("D:20260814"), info
    assert info["Title"] == "System_Specification", info
