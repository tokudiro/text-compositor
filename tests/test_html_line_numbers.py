"""HTML出力の、ブロック要素の`data-line`（原稿の行番号。Viewerが、ツールバーに出す。#328・#357）のテスト。"""
import re

import pytest

from text_compositor.api import render_html
from text_compositor.html_output import DOCUMENT_CSS, _with_data_line

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}

DOC = """# 見出し

段落その1です。
続きの行。

- 項目A
- 項目B
  - 入れ子B1

1. 番号1

   ゆるい段落

> 引用の段落

| a | b |
| - | - |
| 1 | 2 |

```python
print(1)
```

$$
a=b
$$

最後の段落。
"""


def lines_by_tag(tmp_path, markdown):
    md = tmp_path / "doc.md"
    md.write_text(markdown, encoding="utf-8")
    result = render_html(str(md), plugins=PLAIN)
    assert result.ok, result.diagnostics
    html = open(result.html_path, encoding="utf-8").read()
    body = html[html.index("<body"):]
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r'<(\w+)[^>]*\sdata-line="(\d+)"', body)], body


def test_block_elements_carry_their_manuscript_line(tmp_path):
    found, _ = lines_by_tag(tmp_path, DOC)
    assert found == [
        ("h1", 1), ("p", 3),
        ("li", 6), ("li", 7), ("li", 8),      # 緊密なリスト: 項目が持つ（中の段落は、隠れている）
        ("p", 10), ("p", 12),                 # ゆるいリスト: 項目ではなく、中の段落が持つ
        ("p", 14),                            # 引用: 中の段落が持つ
        ("table", 16), ("pre", 20), ("div", 24),   # 表・フェンス・数式
        ("p", 28),
    ]


def test_a_diagram_fence_carries_the_line_on_its_wrapper(tmp_path):
    svg = tmp_path / "x.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>', encoding="utf-8")
    found, body = lines_by_tag(tmp_path, "# T\n\n```svg\n" + svg.read_text(encoding="utf-8") + "\n```\n")
    assert ("div", 3) in found and '<div data-line="3" class="diagram diagram-svg">' in body


def test_a_line_is_not_added_twice_or_to_the_wrong_element(tmp_path):
    _, body = lines_by_tag(tmp_path, DOC)
    assert len(re.findall(r'data-line="10"', body)) == 1 and len(re.findall(r'data-line="6"', body)) == 1
    assert "<hr" not in body or 'hr data-line' not in body


class TestWithDataLine:
    def test_it_adds_the_line_to_the_first_tag_only(self):
        assert _with_data_line('<div class="a"><p>x</p></div>\n', 7) == '<div data-line="7" class="a"><p>x</p></div>\n'

    @pytest.mark.parametrize("html,line", [('<pre>x</pre>', None), ('<pre>x</pre>', 0), ('text', 3), ('', 3)])
    def test_it_leaves_html_without_a_line_or_a_leading_tag_alone(self, html, line):
        assert _with_data_line(html, line) == html


class TestNoBadgeCss:
    """行番号は、ツールバーに出す（#357）。文書のCSSには、バッジ（疑似要素）を、持たせない。"""

    def test_the_document_css_has_no_badge(self):
        assert "data-line-badge" not in DOCUMENT_CSS and "attr(data-line)" not in DOCUMENT_CSS

    def test_the_document_still_has_no_script(self, tmp_path):
        _, body = lines_by_tag(tmp_path, DOC)
        assert "<script" not in body
