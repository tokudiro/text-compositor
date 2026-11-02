"""表（Markdownの表・`.csv`）のTypst化。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import sys
import csv
import io

from text_compositor.table_fence import TableFenceError, parse_table_fence


class TableMixin:
    """表（Markdownの表・`.csv`）のTypst化。"""

    def _render_csv_table(self, text):
        """.csvファイルをTypstの#table()へ変換する（#36）。区切り文字はカンマ固定（sniffingは
        しない。このツールが一貫して採る「明示性優先・魔法をしない」方針に合わせる）。RFC 4180の
        クォート処理（セル内カンマ・改行、""によるクォート文字自体のエスケープ）は標準ライブラリの
        csvモジュールにそのまま委譲する。1行目をヘッダーとして扱い、既存のMarkdownテーブルと同じ
        table_headerスタイル（bold/background/color）を適用する（10章のaggregateとは別の、任意の
        表形式データ向けの汎用機能という位置づけ）。列数が不揃いな行は、他の描画失敗（mermaid等）と
        同様にフォールバックせずFail-fastで即エラー終了する（9章の方針）。"""
        # splitlines()で先に行分割すると、クォートされたセル内の改行（RFC 4180で許容される
        # マルチライン値）まで失われる（csv.readerが行をまたいだクォートを復元する前に、
        # 改行文字自体が消えてしまうため）。StringIOで生テキストのまま渡し、行分割自体を
        # csv.readerに任せる。
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            self._error_here(f"{self.current_file} is an empty CSV file.")
            sys.exit(1)

        # csv_header（#220）: trueなら1行目をヘッダー行にする（既定）。falseなら、すべての行がデータ行で、
        # 列数は、1行目が決める。
        if self.csv_header:
            header, *body = rows
        else:
            header, body = None, rows
        cols = len(rows[0])
        for row_no, row in enumerate(rows[1:], start=2):
            if len(row) != cols:
                self._error_here(f"{self.current_file}:{row_no}: expected {cols} columns (from the "
                                 f"{'header' if self.csv_header else 'first'} row), got {len(row)}.", line=row_no)
                sys.exit(1)

        if header is None:
            result = [f'#table(\n  columns: {cols},\n  ']
        else:
            open_wrap, close_wrap = self._table_header_open_close()
            result = [f'#table(\n  columns: {cols}{self._table_header_fill_arg()},\n  table.header(\n  ']
            for cell in header:
                result.append('[' + open_wrap + self.escape_typst(cell, at_line_start=True) + close_wrap + '], ')
            # table.header()はデフォルトでrepeat: trueのため、表がページを跨いだ次ページ以降にも
            # ヘッダー行が自動的に再掲される（#70。Markdownテーブル側と同じ仕組み）。
            result.append('\n  ),\n  ')
        for row in body:
            for cell in row:
                result.append('[' + self.escape_typst(cell, at_line_start=True) + '], ')
            result.append('\n  ')
        result.append('\n)\n\n')
        return ''.join(result)

    def _render_table_fence(self, content, attrs_str, fence_line=None):
        """`table`フェンス（#554）をTypstの#table()へ変換する。本文はCSV（解析はtable_fence.py）。
        セルの中身は、Markdownの表のセルと同じく、インライン記法として解釈する。クォート内の改行は、
        `<br>`にして、改行として扱う（#489と同じ見え方）。見出し行・見出し列のセルには、table_headerの
        スタイル（太字・文字色）を付け、背景色はfill:の条件（行・列）で付ける。
        誤りは、.csvの章や他の描画失敗と同じく、Fail-fastで即エラー終了する。"""
        try:
            spec = parse_table_fence(content, attrs_str)
        except TableFenceError as e:
            # e.lineは本文の行（1始まり）。フェンスの開始行の次が、本文の1行目。
            line = fence_line + e.line if fence_line and e.line else fence_line
            self._error_here(f"{self.current_file}: {e}", line=line)
            sys.exit(1)

        open_wrap, close_wrap = self._table_header_open_close()

        def cell(text, is_header):
            inline = self.md.parseInline(text.replace('\r\n', '\n').replace('\n', '<br>'), {})[0]
            opening = self._table_cell_open([None, inline], 0)
            body = self.render_inline(inline.children)
            if is_header:
                return opening + open_wrap + body + close_wrap + '], '
            return opening + body + '], '

        fill = self._table_header_fill_arg(spec.header_rows, spec.header_cols)
        result = [f'#table(\n  columns: {spec.cols}{fill},\n  ']
        for r, row in enumerate(spec.rows):
            if r == 0 and spec.header_rows > 0:
                result.append('table.header(\n  ')
            result.extend(cell(text, r < spec.header_rows or c < spec.header_cols)
                          for c, text in enumerate(row))
            result.append('\n  ')
            if spec.header_rows > 0 and r == spec.header_rows - 1:
                # table.header()はrepeat: trueが既定で、ページを跨いだ次ページ以降にも再掲される（#70）。
                result.append('),\n  ')
        result.append('\n)\n\n')
        return ''.join(result)

    def _count_table_cols(self, tokens, start_idx):
        cols = 0
        for i in range(start_idx, len(tokens)):
            if tokens[i].type in ['th_open', 'td_open']:
                cols += 1
            if tokens[i].type == 'tr_close':
                break
        return max(1, cols)

    def _table_cell_open(self, tokens, i):
        """th_open/td_open（tokens[i]）に対する、セルの開きの文字列を返す（#89）。
        セルの中身全体が`[text]{bg="#eeeeee" border=dashed}`のような1つのspanで、bg/borderを
        持つときだけ、セル自体の背景色・枠線として`table.cell(fill:, stroke:)[`を出力する。
        テキストの一部だけを包むspanでは、セルの装飾か文字の装飾か曖昧になるため対象にしない
        （render_inline側で警告して無視する）。それ以外は従来どおり`[`のみ。
        セルのbg/border以外の属性（color/size）は、通常どおりセル内のテキストに適用される。"""
        span = self._whole_cell_span(tokens, i)
        if span is None:
            return '['
        span.meta['cell_style'] = True
        attrs = dict(span.attrs)
        args = []
        bg = attrs.get('bg')
        if bg:
            args.append(f'fill: {self._color_to_typst(bg)}')
        border = attrs.get('border')
        if border:
            stroke = self.CELL_BORDER_STROKES.get(str(border).lower())
            if stroke is None:
                self._warn_here(f"Ignoring invalid border {border!r} in {self.current_file}; "
                      f"expected one of {', '.join(self.CELL_BORDER_STROKES)}.")
            else:
                args.append(f'stroke: {stroke}')
        return f'table.cell({", ".join(args)})[' if args else '['

    @staticmethod
    def _whole_cell_span(tokens, i):
        """セル（tokens[i]のth_open/td_open）の中身全体を包む、bg/borderを持つspan_openを返す。
        該当しなければNone。"""
        if i + 1 >= len(tokens) or tokens[i + 1].type != 'inline':
            return None
        children = tokens[i + 1].children or []
        if not children or children[0].type != 'span_open':
            return None
        attrs = dict(children[0].attrs)
        if 'bg' not in attrs and 'border' not in attrs:
            return None
        depth = 0
        for k, child in enumerate(children):
            if child.type == 'span_open':
                depth += 1
            elif child.type == 'span_close':
                depth -= 1
                if depth == 0:
                    return children[0] if k == len(children) - 1 else None
        return None

    def _table_header_fill_arg(self, header_rows=1, header_cols=0):
        """table_header.backgroundが指定されていれば、#table()のfill:引数（見出し行・見出し列のみ着色）を返す。
        既定（見出し行1・見出し列0）は、従来どおり1行目のみ。未指定なら空文字列（従来どおり無装飾）。"""
        background = self.table_header_style.get('background')
        if not background:
            return ''
        conds = []
        if header_rows == 1:
            conds.append('row == 0')
        elif header_rows > 1:
            conds.append(f'row < {header_rows}')
        if header_cols > 0:
            conds.append(f'col < {header_cols}')
        if not conds:
            return ''
        return f',\n  fill: (col, row) => if {" or ".join(conds)} {{ {self._color_to_typst(background)} }} else {{ none }}'

    def _table_header_open_close(self):
        """table_header.bold/colorに応じた、ヘッダセルの開き/閉じラッパー文字列のペアを返す。
        いずれも未指定なら空文字列（従来どおり無装飾）。スタイルはセル内で変化しないため、
        th_open/th_closeそれぞれで独立に呼び出しても一貫した結果になる。"""
        open_parts = []
        close_parts = []
        if self.table_header_style.get('bold'):
            open_parts.append('#strong[')
            close_parts.append(']')
        color = self.table_header_style.get('color')
        if color:
            open_parts.append(f'#text(fill: {self._color_to_typst(color)})[')
            close_parts.append(']')
        return ''.join(open_parts), ''.join(reversed(close_parts))
