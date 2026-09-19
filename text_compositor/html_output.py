"""HTML出力（#161、実験的）: 単一のMarkdownファイルを、HTMLと図の画像にする。

GUI版Viewer（#165）の表示の材料と、ドキュメントのWeb公開の土台にする。PDF（Typst）とは別の変換処理で、
Markdownの解釈（属性・alert・`:::`ブロック・フェンスの属性）は、`TypstRenderer`の部品をそのまま使う。

- 図（Mermaid・PlantUML・D2・svg）は、PDFと同じ仕組みでSVGにし（キャッシュも共通）、`<img src>`で参照する。
- 出力するHTMLは、外部のCSS・JavaScriptを使わない、1ファイルで完結した文書である。
- レイアウトブロック（`:::`）は、CSS 2.1の表・`position`と、`column-count`だけで近似する。表示側のエンジンが
  対応しない場合は、見た目が崩れる（#180で確認する）。
- 対象外（別issue）: Graphviz（#181）、`typst-exec`（#182）、数式（#183）、生のHTML（#184）。
  これらは内容を消さず、コードブロックにして、警告を出す。
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.utils import OptionsDict

from text_compositor import diagnostics
from text_compositor.build import TypstRenderer

# CSSに、そのまま書いてよい値だけを通す（原稿の値が、CSSの構文を壊したり、別の宣言を足したりしないように）。
_CSS_COLOR_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9-]*|#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}))$')
_CSS_LENGTH_RE = re.compile(r'^\d+(?:\.\d+)?(?:%|pt|px|cm|mm|in|em)$')
_URL_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*:')

# HTMLには意味がない、ページ由来のfront-matterのキー。PDFのために正しく書かれているので、警告にはしない。
PAGE_ONLY_KEYS = ('paper_size', 'landscape', 'header', 'footer', 'paginate', 'font_size')

ALERT_TITLES = {'note': 'Note', 'tip': 'Tip', 'important': 'Important', 'warning': 'Warning', 'caution': 'Caution'}

# 図として表示するフェンスの言語。dot・graphvizは、Typst側で描画しているため、HTMLでは未対応（#181）。
_DIAGRAM_LANGS = ('mermaid', 'plantuml', 'd2', 'svg')
_UNSUPPORTED_FENCES = {
    'dot': "Graphviz is not supported in HTML output yet (#181)",
    'graphviz': "Graphviz is not supported in HTML output yet (#181)",
    'typst-exec': "'typst-exec' is not supported in HTML output yet (#182)",
}

# Markdown・図のほかに、開けるファイル（#196）: `.txt`（等幅の素のテキスト）・`.csv`（表）・`.svg`（画像）。
# それ以外（`.yaml`・`.json`・ソースコード・拡張子なし・未知の拡張子・バイナリ）は、案内つきのエラーにする
# （`.yaml`・`.json`・ソースコードのハイライト表示は、別のissue #218）。
TEXT_FILE_EXT = '.txt'
CSV_FILE_EXT = '.csv'
SVG_FILE_EXT = '.svg'
# 大きなファイルは、先頭のこの大きさだけを読む（表示が、固まらないように。1 MBで約2秒、2 MBで約10秒かかった）。
TEXT_MAX_BYTES = 512 * 1024
# 中身がバイナリか判断する範囲。この範囲にNUL文字があれば、バイナリとする。
_SNIFF_BYTES = 8192

# 出力するHTMLは、スクリプトを含まない（原稿の文字は、すべてエスケープする）。念のため、スクリプトとプラグインを、
# ブラウザ側でも禁止する。Viewerは、この文書を、JavaScriptを有効にしたビューで開く（ドロップの受け口のため。#190）。
CONTENT_SECURITY_POLICY = "script-src 'none'; object-src 'none'; base-uri 'none'"

DOCUMENT_CSS = """\
:root { color-scheme: light dark; --fg: #1f2328; --bg: #ffffff; --muted: #59636e; --line: #d1d9e0; --code-bg: #f6f8fa; --link: #0969da; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --bg: #0d1117; --muted: #9198a1; --line: #3d444d; --code-bg: #151b23; --link: #4493f8; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 "Noto Sans JP", "Segoe UI", "Hiragino Sans", "Yu Gothic UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 28px 64px; }
h1, h2, h3, h4, h5, h6 { line-height: 1.3; margin: 1.6em 0 0.6em; }
h1 { font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid var(--line); }
h2 { font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid var(--line); }
h3 { font-size: 1.25em; }
a { color: var(--link); }
p, ul, ol, table, pre, blockquote { margin: 0 0 1em; }
ul, ol { padding-left: 2em; }
li > p { margin: 0.25em 0; }
ul.contains-task-list { list-style: none; padding-left: 1em; }
code { font: 0.9em/1.4 "Cascadia Mono", Consolas, Menlo, monospace; background: var(--code-bg); padding: 0.15em 0.35em; border-radius: 4px; }
pre { background: var(--code-bg); padding: 12px 16px; border-radius: 6px; overflow: auto; }
pre code { background: none; padding: 0; font-size: 0.875em; }
table.csv td, table.csv th { overflow-wrap: anywhere; }
pre.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.5 "Cascadia Mono", Consolas, Menlo, monospace; tab-size: 4; }
.text-note { color: var(--muted); border-left: 4px solid var(--line); padding: 0.25em 1em; margin: 0 0 1em; }blockquote { margin-left: 0; padding: 0 1em; color: var(--muted); border-left: 4px solid var(--line); }
table { border-collapse: collapse; }
th, td { border: 1px solid var(--line); padding: 6px 12px; vertical-align: top; }
th { background: var(--code-bg); }
hr { border: 0; border-top: 1px solid var(--line); margin: 1.5em 0; }
img { max-width: 100%; }
.diagram { text-align: center; margin: 1em 0; }
.alert { margin: 0 0 1em; padding: 0.5em 1em; border-left: 4px solid var(--alert, #0969da); background: var(--code-bg); }
.alert p { margin: 0.4em 0; }
.alert-title { font-weight: bold; color: var(--alert, #0969da); }
.alert-note { --alert: #0969da; } .alert-tip { --alert: #1a7f37; } .alert-important { --alert: #8250df; }
.alert-warning { --alert: #9a6700; } .alert-caution { --alert: #d1242f; }
@media (prefers-color-scheme: dark) {
  .alert-note { --alert: #4493f8; } .alert-tip { --alert: #3fb950; } .alert-important { --alert: #ab7df8; }
  .alert-warning { --alert: #d29922; } .alert-caution { --alert: #f85149; }
}
table.layout, table.layout td { border: 0; padding: 0 8px 0 0; width: auto; }
table.layout { width: 100%; table-layout: fixed; }
.feature { position: relative; margin: 1em 0; }
.feature img { display: block; width: 100%; }
.feature-caption { position: absolute; left: 0; right: 0; bottom: 0; padding: 1em 1.5em; color: #fff; font-size: 1.5em; font-weight: bold; background: rgba(0, 0, 0, 0.6); }
.feature-caption p { margin: 0; }
.columns { column-gap: 1.5em; margin-bottom: 1em; }
.takahashi { text-align: center; padding: 1.5em 0; line-height: 1.2; }
"""


class _TokenRenderer(RendererHTML):
    """markdown-itのトークンを、HTMLにする。標準の変換に、このツールの拡張（属性・alert・図・画像の属性・
    セル装飾）を加える。トークンの種類と同名のメソッドが、その種類の変換ルールになる（markdown-it-pyの規約）。
    ルールでない補助メソッドは、名前を`_`で始める。"""

    def __init__(self, owner: "HtmlRenderer") -> None:
        super().__init__()
        self.owner = owner

    # -- 全体 ------------------------------------------------------------

    def render(self, tokens, options, env):
        result = ""
        for i, token in enumerate(tokens):
            if token.map:
                self.owner._block_line = self.owner._abs_line(token)  # 警告の行番号に使う（インラインは、直近のブロックで近似）
            if token.type == "inline":
                result += self.renderInline(token.children or [], options, env)
            elif token.type in self.rules:
                result += self.rules[token.type](tokens, i, options, env)
            else:
                result += self.renderToken(tokens, i, options, env)
        return result

    def renderInline(self, tokens, options, env):
        env["span_stack"] = []        # [text]{...}の、開きごとに、<span>を出したか
        env["html_span_stack"] = []   # <span style="color:...">の、開きごとに、<span>を出したか
        result = super().renderInline(tokens, options, env)
        unclosed = sum(1 for emitted in env["html_span_stack"] if emitted)
        if env["html_span_stack"]:
            self.owner._warn_here(f"Unclosed <span style=\"color:...\"> in {self.owner.current_file}; closing it automatically.")
            result += "</span>" * unclosed
        return result

    # -- ブロック ----------------------------------------------------------

    def heading_open(self, tokens, idx, options, env):
        if self.owner._title is None and idx + 1 < len(tokens) and tokens[idx + 1].type == "inline":
            self.owner._title = tokens[idx + 1].content
        return self.renderToken(tokens, idx, options, env)

    def blockquote_open(self, tokens, idx, options, env):
        kind = self.owner._detect_alert_kind(tokens, idx)
        env.setdefault("blockquote_stack", []).append(kind)
        if kind:
            return f'<div class="alert alert-{kind}">\n<p class="alert-title">{ALERT_TITLES[kind]}</p>\n'
        return self.renderToken(tokens, idx, options, env)

    def blockquote_close(self, tokens, idx, options, env):
        stack = env.get("blockquote_stack") or []
        kind = stack.pop() if stack else None
        return "</div>\n" if kind else self.renderToken(tokens, idx, options, env)

    def fence(self, tokens, idx, options, env):
        return self.owner._fence_html(tokens[idx])

    def html_block(self, tokens, idx, options, env):
        return self.owner._html_block(tokens[idx])

    def td_open(self, tokens, idx, options, env):
        self.owner._style_cell(tokens, idx)
        return self.renderToken(tokens, idx, options, env)

    def th_open(self, tokens, idx, options, env):
        self.owner._style_cell(tokens, idx)
        return self.renderToken(tokens, idx, options, env)

    # -- インライン ----------------------------------------------------------

    def image(self, tokens, idx, options, env):
        return self.owner._image_html(tokens[idx])

    def span_open(self, tokens, idx, options, env):
        span = tokens[idx]
        style = self.owner._span_style(span)
        env["span_stack"].append(bool(style))
        return f'<span style="{escapeHtml(style)}">' if style else ""

    def span_close(self, tokens, idx, options, env):
        stack = env["span_stack"]
        return "</span>" if stack and stack.pop() else ""

    def html_inline(self, tokens, idx, options, env):
        return self.owner._html_inline(tokens[idx], env)


class HtmlRenderer(TypstRenderer):
    """Markdown（と、図の単体ファイル）をHTMLにする。`TypstRenderer`の、Markdownの解釈・図のSVG生成・
    キャッシュ・診断の部品を引き継ぎ、出力だけを、HTMLにする（#161）。Typstを出力する側のメソッドは、使わない。
    共通の部分を、基底クラスへ切り出す整理は、#157で扱う。"""

    def __init__(self, base_dir=None, **kwargs) -> None:
        super().__init__(base_dir, **kwargs)
        self._tokens = _TokenRenderer(self)
        # 生成するHTMLの置き場所。画像・図の`src`は、ここからの相対パスにする。
        self.html_dir = self.base_dir
        self._title: Optional[str] = None
        self._pagebreaks = 0
        # 今変換している断片が、原稿の何行目から始まるか（0始まりの行数）。`:::`ブロックで原稿を区切って
        # 断片ごとにパースするため、トークンの行番号（断片の中の相対値）に足して、原稿の行番号にする。
        self._line_base = 0
        # 原稿が参照している、ローカルのファイル（画像など）の絶対パス。Viewerが、変更を検知して自動で更新するために
        # 使う（#170）。存在しないファイルも含める（あとから作られたときに、更新できるように）。
        self.dependencies: set = set()

    def _abs_line(self, token) -> Optional[int]:
        """トークンの、原稿での行番号（1始まり）。行を持たないトークンは、None。"""
        return token.map[0] + 1 + self._line_base if token.map else None

    # -- 入口 ------------------------------------------------------------

    def render_file(self, md_path: str, html_path: str) -> str:
        """1つのファイルを、完結したHTML文書（文字列）にする。対象は、Markdownと、図の単体ファイル。"""
        md_path = os.path.abspath(md_path)
        self.html_dir = os.path.dirname(os.path.abspath(html_path))
        self.current_file = md_path
        self.current_dir = os.path.dirname(md_path)
        self.front_matter = {}
        self._title = None
        self._pagebreaks = 0
        self._line_base = 0
        self.dependencies = set()
        ext = os.path.splitext(md_path)[1].lower()
        if ext in ('.md', '.markdown', *self.DIAGRAM_FILE_EXTS):
            with open(md_path, "r", encoding="utf-8") as f:
                text = f.read()
            if ext in ('.md', '.markdown'):
                if self.variables is not None:
                    text = self._substitute_variables(text, md_path)
                body = self._render_markdown(text)
            else:
                body = self._diagram_source_html(self.DIAGRAM_FILE_EXTS[ext], text)
        elif ext == TEXT_FILE_EXT:
            body = self._plain_text_html(md_path)
        elif ext == CSV_FILE_EXT:
            body = self._csv_html(md_path)
        elif ext == SVG_FILE_EXT:
            body = self._svg_file_html(md_path)
        else:
            self._unsupported_file(md_path, ext)
        if self._pagebreaks:
            diagnostics.info(f"Ignored {self._pagebreaks} '<!-- pagebreak -->' in HTML output.", file=md_path)

        title = (self._title or os.path.splitext(os.path.basename(md_path))[0]).strip()
        return (
            "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{CONTENT_SECURITY_POLICY}\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{escapeHtml(title)}</title>\n<style>\n{DOCUMENT_CSS}</style>\n</head>\n"
            f"<body>\n<main>\n{body}</main>\n</body>\n</html>\n"
        )

    # -- Markdown・図以外のファイル（#196） -------------------------------------------

    SUPPORTED_FILES_GUIDE = ("Obunzuで開けるのは、Markdown（.md）・図（.mmd・.puml・.d2・.dot など）・"
                             "テキスト（.txt）・CSV（.csv）・SVG（.svg）です。")

    def _unsupported_file(self, path: str, ext: str) -> None:
        name = os.path.basename(path)
        detail = self.SUPPORTED_FILES_GUIDE
        if ext in ('.yaml', '.yml', '.json') or ext in ('.py', '.js', '.ts', '.toml', '.xml', '.ini', '.sh', '.css'):
            detail += "設定ファイル・ソースコードの表示は、今後対応する予定です（#218）。"
        elif ext in ('.html', '.htm'):
            detail += "HTMLは、スクリプトを実行しないため、開きません。"
        diagnostics.error(f"'{name}' cannot be opened: the file type '{ext or '(no extension)'}' is not supported.",
                          file=path, detail=detail)
        sys.exit(1)

    def _read_utf8(self, path: str) -> tuple:
        """UTF-8（BOMなし）のテキストとして読む。(文字列, 切ったか, ファイルの大きさ)。テキストでない・UTF-8でなければ、
        案内つきのエラー。大きなファイルは、先頭の`TEXT_MAX_BYTES`だけを読み、切れた末尾の1文字は、捨てる。"""
        import codecs
        name = os.path.basename(path)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read(TEXT_MAX_BYTES + 1)
        truncated = len(data) > TEXT_MAX_BYTES
        data = data[:TEXT_MAX_BYTES]

        reason = None
        if data.startswith(b"\xef\xbb\xbf"):
            reason = "BOMつきのUTF-8です。"
        elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
            reason = "UTF-16です。"
        elif b"\x00" in data[:_SNIFF_BYTES]:
            diagnostics.error(f"'{name}' is a binary file, not text, so it cannot be shown.", file=path,
                              detail="バイナリのファイル（画像・PDFなど）は、開けません。" + self.SUPPORTED_FILES_GUIDE)
            sys.exit(1)
        else:
            try:
                return codecs.getincrementaldecoder("utf-8")("strict").decode(data, final=not truncated), truncated, size
            except UnicodeDecodeError:
                reason = "UTF-8として読めない文字があります（Shift_JISなどの可能性があります）。"
        diagnostics.error(f"'{name}' is not UTF-8 (without BOM), so it cannot be shown.", file=path,
                          detail=f"{reason}文字コードは、UTF-8（BOMなし）だけに対応しています。UTF-8（BOMなし）で保存し直してください。")
        sys.exit(1)

    def _truncation_note(self, path: str, size: int, what: str) -> str:
        """大きなファイルを、途中で切ったときの、ページの先頭の案内。警告の診断も出す。"""
        name = os.path.basename(path)
        limit = f"{TEXT_MAX_BYTES // 1024} KB"
        diagnostics.warning(f"'{name}' is large ({size} bytes); only the first {limit} is shown.", file=path)
        return (f'<p class="text-note">ファイルが大きいため、先頭の約{limit}（{what}）だけを表示しています'
                f'（全体は、約{size / 1024 / 1024:.1f} MB）。</p>\n')

    def _plain_text_html(self, path: str) -> str:
        """`.txt`を、等幅の素のテキストにする。Markdownとしては、解釈しない（`#`や`-`が、見出しやリストに化けないように）。"""
        text, truncated, size = self._read_utf8(path)
        note = self._truncation_note(path, size, "文字数で約" + f"{len(text):,}" + "文字") if truncated else ""
        return f'{note}<pre class="plain-text">{escapeHtml(text)}</pre>\n'

    def _csv_html(self, path: str) -> str:
        """`.csv`を、表にする。1行目は、見出し行（PDF出力と同じ）。列の数が足りない行は、空のセルで、そろえる。"""
        import csv
        import io
        text, truncated, size = self._read_utf8(path)
        if truncated:
            text = text[:text.rfind("\n") + 1] if "\n" in text else text   # 途中で切れた最後の行は、捨てる
        rows = [row for row in csv.reader(io.StringIO(text, newline="")) if row]
        note = self._truncation_note(path, size, f"{len(rows):,}行") if truncated else ""
        if not rows:
            return f'{note}<p class="text-note">空のCSVファイルです。</p>\n'
        width = max(len(row) for row in rows)
        cells = lambda row, tag: "".join(f"<{tag}>{escapeHtml(cell)}</{tag}>" for cell in row + [""] * (width - len(row)))
        head = f"<thead><tr>{cells(rows[0], 'th')}</tr></thead>"
        body = "".join(f"<tr>{cells(row, 'td')}</tr>\n" for row in rows[1:])
        return f'{note}<table class="csv">\n{head}\n<tbody>\n{body}</tbody>\n</table>\n'

    def _svg_file_html(self, path: str) -> str:
        """`.svg`を、画像として表示する。ファイルそのものを`<img>`で参照するため、スクリプトは、実行されず、
        ファイルを保存し直すと、自動で更新される（`dependencies`）。"""
        self.dependencies.add(os.path.abspath(path))
        name = os.path.basename(path)
        return f'<div class="diagram diagram-svg"><img src="{escapeHtml(self._url_for(os.path.abspath(path)))}" alt="{escapeHtml(name)}"></div>\n'

    def _diagram_source_html(self, kind: str, code: str) -> str:
        """図の単体ファイル（.mmd・.puml・.d2）の中身を、図1つのページにする。"""
        return self._fenced_html(kind, code, None, None)

    # -- Markdown -----------------------------------------------------------

    def _render_markdown(self, text: str) -> str:
        text, self.front_matter = self.strip_front_matter(text)
        ignored = [k for k in PAGE_ONLY_KEYS if k in self.front_matter]
        if ignored:
            diagnostics.info(f"Ignored page settings in HTML output: {', '.join(ignored)}.", file=self.current_file)

        output = []
        pos = 0
        for m in self._finditer_outside_fences(self.LAYOUT_BLOCK_RE, text):
            before = text[pos:m.start()]
            if before.strip():
                self._line_base = text.count('\n', 0, pos)
                output.append(self._segment_html(before))
            # ブロックの中身は、さらに区切って変換するため、行番号は、ブロックの中身の先頭で近似する
            self._line_base = text.count('\n', 0, m.start(3))
            output.append(self._layout_html(m.group(1), m.group(2), m.group(3)))
            pos = m.end()
        rest = text[pos:]
        if rest.strip() or not output:
            self._line_base = text.count('\n', 0, pos)
            output.append(self._segment_html(rest))
        return "".join(output)

    def _segment_html(self, text: str) -> str:
        """通常のMarkdown断片を、HTMLにする（`:::`ブロックの前後や、ブロックの中身）。"""
        tokens = self.md.parse(text)
        options = OptionsDict(dict(self.md.options))
        options.breaks = True  # PDFと同じく、原稿の改行を、そのまま改行にする
        return self._tokens.render(tokens, options, {})

    # -- 警告の共通部 -------------------------------------------------------------

    def _warn_line(self, message: str, line: Optional[int] = None) -> None:
        self._warn_here(message, line=line if line is not None else self._block_line)

    # -- フェンス・図 ----------------------------------------------------------

    def _fence_html(self, t) -> str:
        info = t.info.strip()
        parts = info.split(None, 1)
        lang = parts[0] if parts else ''
        attrs = parts[1] if len(parts) > 1 else ''
        if info == 'typst-exec':
            lang = 'typst-exec'
        width, height = self._parse_size_attrs(attrs)
        return self._fenced_html(lang, t.content, width, height, line=self._abs_line(t))

    def _fenced_html(self, lang: str, code: str, width, height, line=None) -> str:
        """フェンス1つ分。図は`<img>`に、それ以外（未対応・無効な図を含む）は、コードブロックにする。"""
        if lang in _DIAGRAM_LANGS:
            svg_path = self._diagram_svg_path(lang, code, line)
            if svg_path is not None:
                return self._diagram_html(lang, svg_path, width, height)
        elif lang in _UNSUPPORTED_FENCES:
            self._warn_line(f"{_UNSUPPORTED_FENCES[lang]}; showing the source as a code block.", line)
        return self._code_block(code, lang)

    def _diagram_svg_path(self, lang: str, code: str, line=None) -> Optional[str]:
        """図のSVGファイルのパス。無効なプラグインの図は、Noneを返す（呼び出し側が、コード表示にする）。
        line: 描画に失敗したとき、診断に付ける、原稿でのフェンスの行。"""
        if lang == 'mermaid':
            return self._mermaid_svg_path(code, line)
        if lang == 'plantuml':
            return self._plantuml_svg_path(code, line)
        if lang == 'd2':
            return self._d2_svg_path(code, line)
        return self._svg_fence_path(code)

    def _diagram_html(self, lang: str, svg_path: str, width, height) -> str:
        return (f'<div class="diagram diagram-{lang}"><img src="{escapeHtml(self._url_for(svg_path))}" '
                f'alt="{lang} diagram"{self._size_attr(width, height)}></div>\n')

    @staticmethod
    def _code_block(code: str, lang: str = '') -> str:
        cls = f' class="language-{escapeHtml(lang)}"' if lang else ''
        return f'<pre><code{cls}>{escapeHtml(code)}</code></pre>\n'

    def _diagram_or_image_html(self, match) -> str:
        """DIAGRAM_OR_IMAGE_REの1マッチ（図のフェンス、または、単独行のMarkdown画像）を、HTMLにする。"""
        if match.group('lang'):
            width, height = self._parse_size_attrs(match.group('attrs'))
            return self._fenced_html(match.group('lang'), match.group('code'), width, height)
        return self._segment_html(match.group('image')).strip() + "\n"

    # -- 画像・URL --------------------------------------------------------------

    def _url_for(self, abs_path: str) -> str:
        """HTMLの置き場所からの、相対URL。別のドライブ等で、相対にできないときは、file URL。"""
        try:
            rel = os.path.relpath(abs_path, self.html_dir)
        except ValueError:
            return Path(abs_path).as_uri()
        return urllib.parse.quote(rel.replace(os.sep, '/'))

    def _asset_url(self, src: str) -> str:
        """画像の`src`を、HTMLからたどれるURLにする。相対パスは、Markdownファイルの場所が基準。"""
        if not src or src.startswith('//') or _URL_SCHEME_RE.match(src):
            return src
        raw = urllib.parse.unquote(src.split('#', 1)[0].split('?', 1)[0])
        if raw.startswith('/'):
            abs_path = os.path.normpath(os.path.join(self.base_dir, raw.lstrip('/')))
        else:
            abs_path = os.path.normpath(os.path.join(self.current_dir, raw))
        self.dependencies.add(abs_path)
        if not os.path.exists(abs_path):
            # PDFは、画像が無いとFail-fastで止める。HTMLは、確認用の表示なので、警告にとどめ、他の部分は表示する。
            self._warn_line(f"Image not found: {abs_path} (referenced from {self.current_file})")
        return self._url_for(abs_path)

    def _size_attr(self, width, height) -> str:
        """`width=`・`height=`（Typstの寸法値）を、検証して、style属性にする。CSSにない単位は、無視する。"""
        styles = []
        for name, value in (('width', width), ('height', height)):
            if value is None:
                continue
            if _CSS_LENGTH_RE.match(value):
                styles.append(f'{name}:{value}')
            else:
                self._warn_line(f"Ignoring invalid {name} {value!r} in {self.current_file}; expected e.g. '50%' or '8cm'.")
        return f' style="{";".join(styles)}"' if styles else ''

    def _image_html(self, t) -> str:
        """Markdownの画像。altに`|`区切りで書く`width=`・`height=`・`align=`を解釈する（#69・#75・#82）。"""
        attrs = dict(t.attrs)
        parts = (t.content or '').split('|')
        alt = parts[0]
        width = height = align = None
        for p in parts[1:]:
            p = p.strip()
            if p.startswith('width='):
                width = p.split('=', 1)[1].strip()
            elif p.startswith('height='):
                height = p.split('=', 1)[1].strip()
            elif p.startswith('align='):
                align = p.split('=', 1)[1].strip()
        styles = []
        size = self._size_attr(width, height)
        if size:
            styles.append(size[len(' style="'):-1])
        if align in ('center', 'right'):
            styles.append('display:block;margin-left:auto;' + ('margin-right:auto' if align == 'center' else 'margin-right:0'))
        elif align == 'left':
            styles.append('display:block;margin-right:auto')
        elif align:
            self._warn_line(f"Ignoring invalid align {align!r} in {self.current_file}; expected left, center or right.")
        title = f' title="{escapeHtml(attrs["title"])}"' if attrs.get('title') else ''
        style = f' style="{";".join(styles)}"' if styles else ''
        return f'<img src="{escapeHtml(self._asset_url(attrs.get("src", "")))}" alt="{escapeHtml(alt)}"{title}{style}>'

    # -- 文字装飾・セル ----------------------------------------------------------

    def _span_style(self, span) -> str:
        """`[text]{color=... size=...}`のspanを、style属性の値にする。何も無ければ、空文字列（spanを出さない）。"""
        if span.meta.get('cell_style'):
            return ''  # セル全体を包むspanは、セルの装飾（_style_cell）になっている
        attrs = dict(span.attrs)
        if 'bg' in attrs or 'border' in attrs:
            self._warn_line(f"Ignoring bg/border in {self.current_file}: they apply only to a span that wraps the "
                            f"entire table cell, e.g. | [text]{{bg=\"#eeeeee\"}} |.")
        styles = []
        color = attrs.get('color')
        if color:
            if _CSS_COLOR_RE.match(str(color).strip()):
                styles.append(f'color:{str(color).strip()}')
            else:
                self._warn_line(f"Ignoring invalid color {color!r} in {self.current_file}.")
        size = attrs.get('size')
        if size is not None:
            if self.FONT_SIZE_RE.match(str(size)):
                styles.append(f'font-size:{size}')
            else:
                self._warn_line(f"Ignoring invalid size {size!r} in {self.current_file}; expected e.g. '10pt'.")
        return ';'.join(styles)

    # セル単位のborderの値（#89）と、CSSの`border`。太さと色は、PDFの表の既定（1pt・黒）に揃えた。
    _CELL_BORDERS = {
        'solid': '1px solid currentColor', 'dashed': '1px dashed currentColor',
        'dotted': '1px dotted currentColor', 'none': 'none',
    }

    def _style_cell(self, tokens, idx) -> None:
        """セルの中身全体が、`[text]{bg=... border=...}`のとき、セルのstyleにする（#89）。"""
        span = self._whole_cell_span(tokens, idx)
        if span is None:
            return
        span.meta['cell_style'] = True
        attrs = dict(span.attrs)
        styles = []
        bg = attrs.get('bg')
        if bg:
            if _CSS_COLOR_RE.match(str(bg).strip()):
                styles.append(f'background:{str(bg).strip()}')
            else:
                self._warn_line(f"Ignoring invalid bg {bg!r} in {self.current_file}.")
        border = attrs.get('border')
        if border:
            css = self._CELL_BORDERS.get(str(border).lower())
            if css is None:
                self._warn_line(f"Ignoring invalid border {border!r} in {self.current_file}; "
                                f"expected one of {', '.join(self._CELL_BORDERS)}.")
            else:
                styles.append(f'border:{css}')
        if styles:
            cell = tokens[idx]
            existing = cell.attrGet('style')
            cell.attrSet('style', (f'{existing};' if existing else '') + ';'.join(styles))

    # -- 生のHTML -------------------------------------------------------------

    def _html_block(self, t) -> str:
        content = t.content.strip()
        if self.PAGEBREAK_DIRECTIVE_RE.match(content):
            self._pagebreaks += 1
            return ''
        if self.DIRECTIVE_RE.match(content):
            return ''
        self._warn_html_ignored(t)
        return ''

    def _html_inline(self, t, env) -> str:
        content = t.content.strip()
        stack = env["html_span_stack"]
        m = self.HTML_SPAN_COLOR_OPEN_RE.match(content)
        if m:
            color = m.group(1).strip()
            if _CSS_COLOR_RE.match(color):
                stack.append(True)
                return f'<span style="color:{color}">'
            self._warn_line(f"Ignoring invalid color {color!r} in {self.current_file}.")
            stack.append(False)
            return ''
        if self.HTML_SPAN_CLOSE_RE.match(content) and stack:
            return '</span>' if stack.pop() else ''
        checkbox = self._task_checkbox_glyph(t.content)
        if checkbox is not None:
            return '<input type="checkbox" disabled' + (' checked' if checkbox == '☑' else '') + '>'
        self._warn_html_ignored(t)
        return ''

    def _warn_html_ignored(self, t) -> None:
        line_no = self._abs_line(t) or self._block_line
        self._warn_here(f"HTML tag detected at {self.current_file}:{line_no if line_no else '?'} : {t.content.strip()}. "
                        "HTML is not supported and will be ignored in HTML output.", line=line_no)

    # -- レイアウトブロック（:::） ---------------------------------------------------

    def _layout_html(self, kind: str, attrs_str, body: str) -> str:
        if kind in ('layout-right', 'layout-left'):
            flip = kind == 'layout-left'
            ratio = self._parse_layout_ratio(attrs_str, (65, 35) if flip else (35, 65))
            return self._side_html(kind, body, flip, ratio)
        if kind == 'layout-compare':
            return self._compare_html(body)
        if kind == 'layout-feature':
            return self._feature_html(body)
        attrs = dict(self.FENCE_ATTR_RE.findall(attrs_str)) if attrs_str else {}
        if kind == 'layout-columns':
            count = attrs.get('n', '2')
            if not count.isdigit() or int(count) < 1:
                self._warn_here(f"Ignoring invalid n {count!r} of layout-columns in {self.current_file}.")
                count = '2'
            return f'<div class="columns" style="column-count:{int(count)}">\n{self._segment_html(body)}</div>\n'
        if kind == 'layout-takahashi':
            size = attrs.get('size', self.TAKAHASHI_DEFAULT_SIZE)
            if not _CSS_LENGTH_RE.match(size):
                self._warn_here(f"Ignoring invalid size {size!r} of layout-takahashi in {self.current_file}.")
                size = self.TAKAHASHI_DEFAULT_SIZE
            return f'<div class="takahashi" style="font-size:{size}">\n{self._segment_html(body)}</div>\n'
        align = attrs.get('align', 'left')  # kind == 'align'
        if align not in ('left', 'center', 'right'):
            self._warn_here(f"Ignoring invalid align {align!r} in {self.current_file}; expected left, center or right.")
            align = 'left'
        return f'<div style="text-align:{align}">\n{self._segment_html(body)}</div>\n'

    def _require_one_diagram(self, name: str, body: str):
        match = self._search_outside_fences(self.DIAGRAM_OR_IMAGE_RE, body)
        if not match:
            self._error_here(f"'{name}' block in {self.current_file} must contain exactly one "
                             "```mermaid/```plantuml/```dot/```graphviz/```svg/```d2 fence or a standalone image.")
            sys.exit(1)
        return match

    def _side_html(self, name: str, body: str, flip: bool, ratio) -> str:
        """layout-right・layout-left: テキストと図を、2つのセルに並べる。"""
        match = self._require_one_diagram(name, body)
        surrounding = (body[:match.start()] + body[match.end():]).strip()
        text_html = self._segment_html(surrounding) if surrounding else ''
        image_html = self._diagram_or_image_html(match)
        cells = [image_html, text_html] if flip else [text_html, image_html]
        left, right = ratio
        total = (left + right) or 1
        return (f'<table class="layout {name}"><tbody><tr>'
                f'<td style="width:{left * 100 / total:.1f}%">\n{cells[0]}</td>'
                f'<td style="width:{right * 100 / total:.1f}%">\n{cells[1]}</td>'
                '</tr></tbody></table>\n')

    def _compare_html(self, body: str) -> str:
        """layout-compare: 2つの図を、左右に並べる。各図の直前のテキストは、同じ列のキャプションにする。"""
        matches = self._finditer_outside_fences(self.DIAGRAM_OR_IMAGE_RE, body)
        if len(matches) != 2:
            self._error_here(f"'layout-compare' block in {self.current_file} must contain exactly two "
                             f"```mermaid/```plantuml/```dot/```graphviz/```svg/```d2 fences or images (found {len(matches)}).")
            sys.exit(1)
        cells = []
        prev_end = 0
        for i, m in enumerate(matches):
            caption = body[prev_end:m.start()].strip()
            trailing = body[matches[-1].end():].strip() if i == len(matches) - 1 else ''
            cells.append((self._segment_html(caption) if caption else '')
                         + self._diagram_or_image_html(m)
                         + (self._segment_html(trailing) if trailing else ''))
            prev_end = m.end()
        return ('<table class="layout layout-compare"><tbody><tr>'
                f'<td style="width:50%">\n{cells[0]}</td><td style="width:50%">\n{cells[1]}</td>'
                '</tr></tbody></table>\n')

    def _feature_html(self, body: str) -> str:
        """layout-feature: 写真（または図）の下部に、キャッチコピーを重ねる。"""
        match = self._require_one_diagram('layout-feature', body)
        caption = (body[:match.start()] + body[match.end():]).strip()
        if match.group('lang'):
            image_html = self._diagram_or_image_html(match)
        else:
            m = re.match(r'!\[[^\]]*\]\(([^)]+)\)', match.group('image'))
            image_html = f'<img src="{escapeHtml(self._asset_url(m.group(1)))}" alt="">\n'
        caption_html = f'<div class="feature-caption">\n{self._segment_html(caption)}</div>\n' if caption else ''
        return f'<div class="feature">\n{image_html}{caption_html}</div>\n'
