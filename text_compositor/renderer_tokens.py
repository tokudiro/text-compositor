"""markdown-itのトークン列（ブロック要素）を、Typstにする処理と、その補助（行番号・警告・HTMLトークン・ソース位置の対応づけ）。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import re
import sys
from text_compositor.emphasis_lint import find_unapplied_bold, unapplied_bold_message
from text_compositor.log import _error, _log_info, _warn


class TokenMixin:
    """markdown-itのトークン列（ブロック要素）を、Typstにする処理と、その補助（行番号・警告・HTMLトークン・ソース位置の対応づけ）。"""

    # Marpディレクティブコメント。7章の要件（Marp原稿との共用）を満たすため認識はするが、
    # 何も反映しない（#41、_handle_html_tokenを参照）。#42でheader/footer/paginateがfront-matter/
    # chapters[]経由では適用対象になったが、このインラインHTMLコメント形式は意図的に対象外のまま
    # （ファイル内の任意の位置から「以降に持続する」という#16と同種の危険な性質を持つため）。
    DIRECTIVE_RE = re.compile(r'^<!--\s*(header|footer|paginate)\s*:.*-->\s*$')

    # 改ページを明示する記法（#92）。document.marp_compat: falseのとき、hr（---等）が単なる
    # 水平線になる代わりに使う。header/footer/paginateと違い「その場1回だけ効くアクション」で
    # 状態を持ち越さないため、#41の懸念（章をまたいで持続する設計は並べ替えと衝突する）には
    # 抵触しない。marp_compatの値に関わらず常に有効（hrの挙動と独立した明示的な記法のため）。
    PAGEBREAK_DIRECTIVE_RE = re.compile(r'^<!--\s*pagebreak\s*-->\s*$')

    # GitHub形式のalert記法（#61）。`> [!NOTE]`のように、blockquoteの最初の行がこのマーカーだけの
    # ときだけ発動する。テンプレート側は@preview/note-me（MIT、#63でライセンス確認済み）が持つ
    # note/tip/important/warning/cautionをcallout()でラップして呼び出す。
    ALERT_MARKER_RE = re.compile(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$')

    def _consume_heading(self, tokens, pos):
        """posがheading_open（H1/H2まで）ならそのブロックを読み飛ばし、(次の位置, 見出しテキスト)を返す。
        該当しなければ (pos, None)。"""
        if pos >= len(tokens) or tokens[pos].type != 'heading_open' or int(tokens[pos].tag[1:]) > 2:
            return pos, None
        j = pos
        text_parts = []
        while j < len(tokens) and tokens[j].type != 'heading_close':
            if tokens[j].type == 'inline':
                text_parts.append(tokens[j].content)
            j += 1
        return j + 1, ' '.join(text_parts)

    def _consume_lead_image(self, tokens, pos):
        """posが「画像1個だけの段落」（タイトルスライドの図版）ならそのブロックを読み飛ばし、
        次の位置を返す。該当しなければposをそのまま返す。"""
        if (pos + 2 >= len(tokens)
                or tokens[pos].type != 'paragraph_open'
                or tokens[pos + 1].type != 'inline'
                or tokens[pos + 2].type != 'paragraph_close'):
            return pos
        children = tokens[pos + 1].children or []
        if len(children) == 1 and children[0].type == 'image':
            return pos + 3
        return pos

    def _skip_leading_title(self, tokens):
        """cover: replace/none 用に、先頭のタイトルブロック（画像1枚 + H1/H2と直後の区切り線）を読み飛ばす"""
        i = 0
        dropped = []
        # 先頭のHTMLコメント（Marpのディレクティブ等）は読み飛ばす。ただし警告は従来どおり出す
        while i < len(tokens) and tokens[i].type in ['html_block', 'html_inline']:
            self._handle_html_token(tokens[i])
            i += 1

        # タイトルの前に図版が1枚だけ置かれているタイトルスライド（画像 + H1 + H2）に対応する。
        # ただしこの時点では見出しが続くかどうか未確定なので、実際に見出しが見つかったときだけ
        # 画像も含めて読み飛ばす（見出しが無ければ画像はそのまま本文として残す）。
        image_end = self._consume_lead_image(tokens, i)
        title_start, title = self._consume_heading(tokens, image_end)
        if title is None:
            return 0
        i = title_start
        dropped.append(title)

        # 直後がさらに見出し(H1/H2)の場合、それをサブタイトルとして一緒に読み飛ばすのは、
        # そのすぐ後にhr（---）が続くか、そこでこのチャプター（ファイル）が終わっているとき
        # に限る。それ以外（続けて本文の段落が来る等）は、本文側の実見出し（例: "## 1. はじめに"）
        # であり、タイトルスライドの一部ではないため触らない。
        next_pos, subtitle = self._consume_heading(tokens, i)
        if subtitle is not None and (next_pos >= len(tokens) or tokens[next_pos].type == 'hr'):
            dropped.append(subtitle)
            i = next_pos
            if i < len(tokens) and tokens[i].type == 'hr':
                i += 1
            _log_info(f"Cover: replaced the leading title slide of {self.current_file} ({' / '.join(dropped)})")
            return i

        if i < len(tokens) and tokens[i].type == 'hr':
            i += 1
        # サイレントに本文を捨てないよう、取り除いた内容は必ずログに出す
        _log_info(f"Cover: replaced the leading title slide of {self.current_file} ({' / '.join(dropped)})")
        return i

    def _detect_alert_kind(self, tokens, i):
        """tokens[i]がblockquote_openのとき、直後の段落が`[!NOTE]`等のマーカーだけの行なら
        種別（小文字）を返す。マッチした場合、マーカーのテキストトークン（と直後のsoftbreak）を
        その場で取り除く（以降のinlineレンダリングに影響しないようにするため）。"""
        if i + 2 >= len(tokens):
            return None
        if tokens[i + 1].type != 'paragraph_open' or tokens[i + 2].type != 'inline':
            return None
        children = tokens[i + 2].children
        if not children or children[0].type != 'text':
            return None
        m = self.ALERT_MARKER_RE.match(children[0].content.strip())
        if not m:
            return None
        children.pop(0)
        if children and children[0].type == 'softbreak':
            children.pop(0)
        return m.group(1).lower()

    def render_tokens(self, tokens, start=0):
        result = []
        i = start
        while i < len(tokens):
            t = tokens[i]
            if t.map:
                self._block_line = t.map[0] + 1
            if t.type == 'heading_open':
                self._emit_srcmap(result, t)
                level = int(t.tag[1:]) + self.heading_offset
                result.append('=' * level + ' ')
            elif t.type == 'heading_close':
                result.append('\n\n')
            elif t.type == 'paragraph_open':
                self._emit_srcmap(result, t)
            elif t.type == 'paragraph_close':
                # 【修正】タイトなリスト内の暗黙段落(hidden)で空行を出さない（loose化防止）
                if not t.hidden:
                    result.append('\n\n')
            elif t.type == 'blockquote_open':
                self._emit_srcmap(result, t)
                alert_kind = self._detect_alert_kind(tokens, i)
                if alert_kind:
                    result.append(f'#callout(kind: "{alert_kind}")[\n')
                else:
                    result.append('#quote(block: true)[\n')
            elif t.type == 'blockquote_close':
                result.append(']\n\n')
            elif t.type == 'inline':
                self._warn_unapplied_bold(t, self._line_of(t))
                result.append(self.render_inline(t.children))
            # 【修正】ネストしたリストを階層のままインデント付きで出力する
            elif t.type in ['bullet_list_open', 'ordered_list_open']:
                self._emit_srcmap(result, t)
                if self.list_stack and not self._ends_with_newline(result):
                    result.append('\n')
                self.list_stack.append('ordered' if t.type == 'ordered_list_open' else 'bullet')
            elif t.type in ['bullet_list_close', 'ordered_list_close']:
                if self.list_stack:
                    self.list_stack.pop()
                if not self.list_stack:
                    result.append('\n')
            elif t.type == 'list_item_open':
                indent = '  ' * max(0, len(self.list_stack) - 1)
                marker = '+ ' if self.list_stack and self.list_stack[-1] == 'ordered' else '- '
                result.append(indent + marker)
            elif t.type == 'list_item_close':
                if not self._ends_with_newline(result):
                    result.append('\n')
            elif t.type == 'table_open':
                self._emit_srcmap(result, t)
                cols = self._count_table_cols(tokens, i)
                result.append(f'#table(\n  columns: {cols}{self._table_header_fill_arg()},\n  table.header(\n  ')
            elif t.type == 'thead_close':
                # table.header()呼び出しを閉じ、以降のtd_open/td_closeはtable()本体への
                # 通常の位置引数として続く（#70）。table.header()はデフォルトでrepeat: trueの
                # ため、表がページを跨いだ次ページ以降にもヘッダー行が自動的に再掲される。
                result.append('\n  ),\n  ')
            elif t.type == 'table_close':
                result.append('\n)\n\n')
            elif t.type == 'hr':
                self._emit_srcmap(result, t)
                if self.marp_compat:
                    # 見出し直前の自動改ページと二重に効いて空ページが発生する既知の不具合を
                    # 避けるため、原則通りweak: trueを使う（doc/spec.md、#92で修正）。
                    result.append('#pagebreak(weak: true)\n\n')
                else:
                    result.append('#line(length: 100%)\n\n')
            elif t.type == 'fence':
                self._emit_srcmap(result, t)
                info = t.info.strip()
                if info == 'typst-exec':
                    if not self.allow_exec:
                        self._error_here(f"Security: 'typst-exec' is allowed only under a 'reviewed/' directory ({self.current_file}).")
                        sys.exit(1)
                    result.append(f"{t.content}\n\n")
                else:
                    # info stringは'mermaid'や'mermaid {width=50% height=8cm}'のように、言語名の
                    # 後ろへ空白区切りでサイズ指定属性を書ける（#82）。
                    parts = info.split(None, 1)
                    lang = parts[0] if parts else ''
                    if lang in ('mermaid', 'plantuml', 'dot', 'graphviz', 'svg', 'd2'):
                        width, height = self._parse_size_attrs(parts[1] if len(parts) > 1 else '')
                        result.append(self._render_diagram_fence(lang, t.content, width, height))
                    else:
                        # ```` ``` ````フェンス構文で直接組み立てると、コード内容自体に```が
                        # 含まれる場合にTypst側のフェンスが早期に閉じて壊れる。文字列リテラルとして
                        # 渡すraw()なら安全（#15の_render_raw_textと同じ理由）。
                        result.append(self._render_raw_text(t.content, lang or None))
            elif t.type in ['html_inline', 'html_block']:
                result.append(self._handle_html_token(t))
            elif t.type == 'th_open':
                open_wrap, _ = self._table_header_open_close()
                result.append(self._table_cell_open(tokens, i) + open_wrap)
            elif t.type == 'th_close':
                _, close_wrap = self._table_header_open_close()
                result.append(close_wrap + '], ')
            elif t.type == 'td_open':
                result.append(self._table_cell_open(tokens, i))
            elif t.type == 'td_close':
                result.append('], ')
            elif t.type == 'tr_close':
                result.append('\n  ')
            i += 1
        return "".join(result)

    def _line_of(self, t):
        """トークンtの、原稿での行番号（1始まり）。インライントークンは行を持たないため、直近のブロックの
        開始行で近似する。分からなければNone。"""
        if t is not None and t.map:
            return t.map[0] + 1
        return self._block_line

    def _warn_unapplied_bold(self, inline_token, first_line):
        """効かずに、そのまま文字として残った太字（`**「重要」**です`など）を、警告する（#215）。PDFとHTML出力で共通。
        first_line: 段落の1行目の、原稿での行（分からなければNone）。段落の中の行のずれは、ここで足す。"""
        for offset, snippet in find_unapplied_bold(inline_token.children, inline_token.content):
            self._warn_here(unapplied_bold_message(snippet), line=first_line + offset if first_line else None)

    def _warn_here(self, message, line=None):
        """現在処理中の原稿（current_file）の位置つきで警告を出す（Python APIの診断のfile/line、#167）。"""
        _warn(message, file=self.current_file or None, line=line)

    def _error_here(self, message, line=None, **kwargs):
        """現在処理中の原稿（current_file）の位置つきでエラーを出す（呼び出し側が、sys.exitで止める）。"""
        _error(message, file=self.current_file or None, line=line, **kwargs)

    def _warn_html(self, t):
        line_no = self._line_of(t)
        self._warn_here(f"HTML tag detected at {self.current_file}:{line_no if line_no else '?'} : {t.content.strip()}. HTML is not supported and will be ignored in Typst output.", line=line_no)

    def _task_checkbox_glyph(self, html):
        """tasklists_pluginが出力する<input class="task-list-item-checkbox" ...>だけを認識し、
        Unicodeのチェックボックス記号を返す（PDFは非対話的なので実際のcheckboxウィジェットは不要）。
        該当しなければNone（呼び出し側で通常のHTML警告にフォールバックする）。"""
        if 'task-list-item-checkbox' not in html:
            return None
        return '☑' if 'checked="checked"' in html else '☐'

    def _handle_html_token(self, t):
        """Marpのディレクティブコメント（<!-- header: X -->等）は、Marp原稿との共用時に不要な
        警告が出ないよう認識はするが、何も反映しない（値を読み捨てる）。実際に反映する機能は
        一度実装した（#16）が、チャプター（ファイル）をまたいで状態が持続する設計が、この
        ツールの売りである「章の並べ替え」と衝突する（並べ替えると意図しないヘッダーが
        混入しうる）ため撤回した（#41）。<!-- pagebreak -->（#92）はその場1回だけ効くアクション
        で状態を持ち越さないため、この制約の対象外として実際に反映する。それ以外（未対応の
        ディレクティブ・生のHTMLタグ）は従来どおり警告のみでビルドを継続する。"""
        content = t.content.strip()
        if self.PAGEBREAK_DIRECTIVE_RE.match(content):
            return '#pagebreak(weak: true)\n\n'
        if self.DIRECTIVE_RE.match(content):
            return ""
        self._warn_html(t)
        return ""

    def _ends_with_newline(self, result):
        for s in reversed(result):
            if s:
                return s.endswith('\n')
        return True

    def _emit_srcmap(self, result, t):
        """document.diagnostics.line_mapping: "block"（既定）のとき、トップレベルのブロック
        （見出し・段落・引用・リスト全体・テーブル全体・hr・fence）の開始点で、生成Typst
        コードへ行コメントの目印を挿し込む。リストの中（self.list_stackが非空）は対象外
        （リスト項目・テーブル行単位まで踏み込む"fine"は、Typstのリスト継続判定への影響を
        実機検証してから対応する将来課題）。"off"時は何もしない（従来どおりTypst側の生の
        行番号のみになる）。"""
        if self.line_mapping != "block" or t.map is None or self.list_stack:
            return
        if result and not self._ends_with_newline(result):
            result.append('\n')
        result.append(f'{self.SRCMAP_PREFIX}{self.current_file}:{t.map[0] + 1}\n')
