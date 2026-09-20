"""インライン要素（文字のエスケープ・強調・リンク・画像・用語索引・文字色）のTypst化。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import re
from text_compositor.typst_literal import escape_string_literal


class InlineMixin:
    """インライン要素（文字のエスケープ・強調・リンク・画像・用語索引・文字色）のTypst化。"""

    # 行頭に来るとTypstのブロック記法（見出し/リスト/用語リスト）として解釈される記号
    BLOCK_HEAD_RE = re.compile(r'^([ \t]*)(=+|[-+/]|[0-9]+[.)])(?=\s|$)')

    # GitHub Wiki拡張の用語索引記法（#47、#48）。[[用語]]の素の形のみ対応し、区切り記法
    # （[[表示|ページ]]）は使い方が分かりにくいとして不採用（#48）。[[/]]は空にならないよう
    # 中身を1文字以上必須にし、ネストした角括弧（通常の[link]記法との衝突）は対象外にする。
    WIKILINK_RE = re.compile(r'\[\[([^\[\]]+)\]\]')

    # 文字色指定（#46）。<span style="color:...">は「閉じた許可リスト」への1パターン追加として
    # 狭く特別扱いする（それ以外のHTMLタグは従来どおり非対応・警告のまま）。もう1つの記法
    # （[text]{color=red}、Pandoc由来）はmdit_py_plugins.attrsのspan機能で処理する。
    HTML_SPAN_COLOR_OPEN_RE = re.compile(r'^<span\s+style\s*=\s*["\']color\s*:\s*([^;"\']+?)\s*;?\s*["\']\s*>$', re.IGNORECASE)

    HTML_SPAN_CLOSE_RE = re.compile(r'^</span\s*>$', re.IGNORECASE)

    # フォントサイズ指定（#93）。[text]{size=10pt}のsize属性、front-matterのfont_sizeの両方で使う
    # 共通フォーマット。Typstの#text(size: ...)にそのまま渡せる"10pt"/"10.5pt"のような値のみ許可する。
    FONT_SIZE_RE = re.compile(r'^\d+(\.\d+)?pt$')

    def escape_typst(self, text, at_line_start=False):
        text = text.replace('\\', '\\\\')
        # 【修正】テーブルセル破壊等のサイレントバグを防ぐため [ および ] もエスケープ対象に追加
        for c in ['#', '$', '<', '>', '@', '*', '_', '`', '~', '[', ']']:
            text = text.replace(c, '\\' + c)
        # 【修正】行頭の = - + / 1. がTypstの見出し・リスト記法に化けるのを防ぐ
        if at_line_start:
            text = self.BLOCK_HEAD_RE.sub(lambda m: m.group(1) + '\\' + m.group(2), text)
        return text

    def _register_glossary_term(self, term):
        """[[用語]]の1出現を登録し、Typstの#metadata(none)<gloss-N>ラベルを埋め込むコード片を
        返す（#47）。metadata()は見た目に影響しない不可視要素で、目次のoutline()と同じ
        「context+query()でレイアウト後にページ番号を取得する」パターンで巻末索引を組み立てる。"""
        label_id = f"gloss-{self._glossary_label_counter}"
        self._glossary_label_counter += 1
        self.glossary_terms.setdefault(term, []).append(label_id)
        return f'{self.escape_typst(term)}#metadata(none)<{label_id}>'

    def _render_text_with_glossary(self, content, at_line_start):
        """textトークンの中身から[[用語]]を検出して登録しつつ、それ以外は通常どおりエスケープする。
        code_inline/fence等はrender_inlineに来ないtextトークンとして独立に処理されるため、
        ここで正規表現置換してもコードブロックの中身を巻き込む心配はない。"""
        parts = []
        last_end = 0
        first_segment = True
        for m in self.WIKILINK_RE.finditer(content):
            plain = content[last_end:m.start()]
            if plain:
                parts.append(self.escape_typst(plain, at_line_start=(at_line_start and first_segment)))
                first_segment = False
            term = m.group(1).strip()
            parts.append(self._register_glossary_term(term))
            first_segment = False
            last_end = m.end()
        remaining = content[last_end:]
        if remaining or not parts:
            parts.append(self.escape_typst(remaining, at_line_start=(at_line_start and first_segment)))
        return "".join(parts)

    def render_inline(self, tokens):
        res = []
        at_line_start = True
        # 文字色指定（#46）。<span style="color:...">はhtml_inlineの開き/閉じが独立したトークン
        # として出てくるため、段落内でスタック管理して対応させる。閉じずに段落が終わった場合は
        # 壊れたTypstコードを生成しないよう自動で閉じ、警告を出す。
        html_span_depth = 0
        # [text]{color=red}（attrs_pluginのspan_open/span_close）は既に開閉が対になった
        # トークンとして出てくるため、各span_openが実際にラップを出力したかどうかだけ
        # スタックで覚えておけばよい（span_close側は自分でattrsを持たないため）。
        span_wrap_stack = []
        for t in tokens:
            if t.type == 'text':
                if self.glossary_enabled and '[[' in t.content:
                    res.append(self._render_text_with_glossary(t.content, at_line_start))
                else:
                    res.append(self.escape_typst(t.content, at_line_start=at_line_start))
            elif t.type == 'strong_open':
                res.append('#strong[')
            elif t.type == 'strong_close':
                res.append(']')
            elif t.type == 'em_open':
                res.append('#emph[')
            elif t.type == 'em_close':
                res.append(']')
            elif t.type == 's_open':
                res.append('#strike[')
            elif t.type == 's_close':
                res.append(']')
            elif t.type == 'code_inline':
                # `` `text` ``のように直接バッククォートで組み立てると、text自体にバッククォートが
                # 含まれる場合（例: 4バッククォートのインラインコードスパンの中身が```を含む）に
                # Typst側のraw構文が早期に閉じて壊れる。文字列リテラルとして渡すraw()なら安全
                # （#15の_render_raw_text・フェンスのelse分岐と同じ理由。実測で発覚したバグ）。
                res.append(f'#raw("{escape_string_literal(t.content)}")')
            elif t.type in ['softbreak', 'hardbreak']:
                res.append('#linebreak()\n')
            elif t.type == 'image':
                src = dict(t.attrs).get('src', '')
                alt_text = t.content or ""
                width_opt = ""
                height_opt = ""
                align = None

                # alt_textからサイズ・配置指定 (例: alt|width=50%|height=30%|align=center) を解析
                if "|" in alt_text:
                    parts = alt_text.split("|")
                    for p in parts[1:]:
                        p = p.strip()
                        if p.startswith("width="):
                            w = p.split("=", 1)[1]
                            width_opt = f', width: {w}'
                        elif p.startswith("height="):
                            h = p.split("=", 1)[1]
                            height_opt = f', height: {h}'
                        elif p.startswith("align="):
                            align = p.split("=", 1)[1].strip()

                # width/height未指定ならfit-image()（実寸基準、はみ出す場合のみ自動縮小）を使う。
                # 明示指定時は自動縮小をバイパスして#image()へそのまま渡す（拡大も含めて指定値どおり
                # になる）。mermaid/plantuml等の事前レンダリング画像（_render_sized_image）と同じ
                # 方針（#69、#82で確立済みの優先順位をそのまま踏襲）。
                if width_opt or height_opt:
                    image_expr = f'#image("{self._resolve_asset(src)}"{width_opt}{height_opt})'
                else:
                    image_expr = f'#fit-image("{self._resolve_asset(src)}")'
                # align未指定時は従来通り（暗黙の左寄せ）のまま変更しない（#75）。他の独自属性
                # （layout-rightのleft=/right=比率等）と同様、align=の値自体の妥当性チェックは
                # 行わない（不正値はTypst側の#align()呼び出しでコンパイルエラーになる）。
                if align:
                    res.append(f'#align({align})[{image_expr}]')
                else:
                    res.append(image_expr)
            elif t.type == 'link_open':
                href = dict(t.attrs).get('href', '')
                res.append(f'#link("{escape_string_literal(href)}")[')
            elif t.type == 'link_close':
                res.append(']')
            elif t.type == 'span_open':
                # [text]{color=red}（#46）、[text]{size=10pt}（#93）。attrs_pluginに
                # allowed=["color", "size"]を指定しているため、それ以外の属性は既にパース段階で
                # 取り除かれている。color/sizeのどちらも無ければ何もラップしない。両方指定された
                # 場合は#text()呼び出し1つにfill/sizeをまとめる（2重にラップしない）。
                attrs = dict(t.attrs)
                if ('bg' in attrs or 'border' in attrs) and not t.meta.get('cell_style'):
                    # セル全体を包むspanは、_table_cell_openが既にtable.cell()へ変換して印を付けている
                    self._warn_here(f"Ignoring bg/border in {self.current_file}: they apply only to a span that "
                                    f"wraps the entire table cell, e.g. | [text]{{bg=\"#eeeeee\"}} |.",
                                    line=self._line_of(t))
                color = attrs.get('color')
                size = attrs.get('size')
                if size is not None and not self.FONT_SIZE_RE.match(str(size)):
                    line_no = self._line_of(t)
                    self._warn_here(f"Ignoring invalid size {size!r} in {self.current_file}:{line_no if line_no else '?'}; expected e.g. '10pt'.",
                                    line=line_no)
                    size = None
                text_args = []
                if color:
                    text_args.append(f'fill: {self._color_to_typst(color)}')
                if size:
                    text_args.append(f'size: {size}')
                if text_args:
                    res.append(f'#text({", ".join(text_args)})[')
                    span_wrap_stack.append(True)
                else:
                    span_wrap_stack.append(False)
            elif t.type == 'span_close':
                if span_wrap_stack and span_wrap_stack.pop():
                    res.append(']')
            elif t.type == 'html_inline':
                content = t.content.strip()
                span_color_match = self.HTML_SPAN_COLOR_OPEN_RE.match(content)
                # tasklists_pluginはチェックボックスを生HTML(<input class="task-list-item-checkbox" ...>)
                # として出力する。<span style="color:...">とあわせ、#46で決めた「閉じた許可リスト」の
                # 考え方に沿い、このパターンだけを特別扱いする（#48）。それ以外のHTMLは従来どおり警告。
                if span_color_match:
                    color = span_color_match.group(1).strip()
                    res.append(f'#text(fill: {self._color_to_typst(color)})[')
                    html_span_depth += 1
                elif self.HTML_SPAN_CLOSE_RE.match(content) and html_span_depth > 0:
                    res.append(']')
                    html_span_depth -= 1
                else:
                    checkbox = self._task_checkbox_glyph(t.content)
                    if checkbox is not None:
                        res.append(checkbox)
                    else:
                        self._warn_html(t)
            else:
                line_no = self._line_of(t)
                self._warn_here(f"Unhandled inline token '{t.type}' at {self.current_file}:{line_no if line_no else '?'}", line=line_no)
            # 改行直後のテキストのみ行頭エスケープの対象にする
            at_line_start = t.type in ['softbreak', 'hardbreak']
        if html_span_depth > 0:
            # 壊れたTypstコード（閉じ角括弧の不足）を生成しないよう自動で閉じ、書き忘れに気付けるよう警告する
            self._warn_here(f"Unclosed <span style=\"color:...\"> in {self.current_file}; closing it automatically.")
            res.append(']' * html_span_depth)
        return "".join(res)

    def _color_to_typst(self, value):
        """config.yamlやMarkdownの色文字列をTypstの色表現へ変換する（#45、#46）。
        Typstのrgb()は"red"のような色名文字列を受け付けないため（hex文字列のみ）、"#rrggbb"形式は
        rgb()に、"red"のような単純な識別子はTypstの色定数名としてそのまま渡す。"""
        value = str(value).strip()
        if self.COLOR_IDENTIFIER_RE.match(value):
            return value
        return f'rgb("{escape_string_literal(value)}")'
