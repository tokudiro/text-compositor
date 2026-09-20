"""`:::`のレイアウトブロック（layout-right・layout-left・layout-compare・layout-feature・layout-columns・layout-takahashi・align）。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import re
import sys


class LayoutMixin:
    """`:::`のレイアウトブロック（layout-right・layout-left・layout-compare・layout-feature・layout-columns・layout-takahashi・align）。"""

    # ::: layout-right / layout-left / layout-compare / layout-feature / layout-columns /
    # layout-takahashi / align ... ::: ブロック。ブロック名の後ろに`{key=value ...}`という
    # Pandoc風の中括弧属性を書ける（#83）。
    # - layout-right: 中の図（mermaid/plantuml/dot/graphvizフェンス、または単独行のMarkdown画像）
    #   を右、それ以外のテキストを左に配置する。`{left=30 right=70}`のように左:右の比率
    #   （Typstのfr単位。合計100である必要はない）を指定できる。省略時は35:65（#81）。
    # - layout-left: layout-rightの左右反転版（図を左、テキストを右）。比率記法は同じで、省略時は
    #   65:35（#81）。
    # - layout-compare: 中の2つの図を左右に並べる（横長の図同士の比較用）。図の種類は混在可（例:
    #   片方mermaid・もう片方は写真）。
    # - layout-feature: 写真（または図）をフルブリードで敷き、下部にキャッチコピーを重ねる（#78）。
    # - layout-columns: 中身（任意のMarkdown）を`{n=N}`で指定した列数（省略時2列）のcolumns()に
    #   流し込む（#78）。
    # - layout-takahashi: 中身（任意のMarkdown）を画面の上下左右中央・大きな文字で表示する
    #   （高橋メソッド、#95）。`{size=...}`で既定の文字サイズ（TAKAHASHI_DEFAULT_SIZE）を
    #   上書きできる。
    # - align: 中身（任意のMarkdown、複数段落可）を`{align=center}`/`{align=right}`で指定した
    #   寄せでラップする。画像のalign属性（#75）と同じく、指定しない場合の既定の見た目（左寄せ）
    #   は変わらない（#87）。
    # markdown-it の通常のASTフローでは「直前・直後のテキストと図をまとめて2カラム化する」表現が
    # 難しいため、通常のトークン処理に入る前の生テキスト段階で切り出して個別に処理する（#11）。
    # 対応する図の種類をmermaidだけに限らず一般化したもの（#77）。
    LAYOUT_BLOCK_RE = re.compile(
        r'^::: *(layout-right|layout-left|layout-compare|layout-feature|layout-columns|'
        r'layout-takahashi|align)'
        r'(?: +\{([^}\r\n]*)\})? *\r?\n(.*?)\r?\n::: *\r?$',
        re.MULTILINE | re.DOTALL)

    # フェンス（mermaid/plantuml/dot/graphviz/svg/d2）か、単独行のMarkdown画像（`![alt](src)`のみの行）の
    # いずれかにマッチする。画像側は行全体にアンカーし、文中に埋め込まれたインライン画像を誤って
    # 抜き出さないようにする（テキストの前後を単純に連結する都合上、行の一部だけを抜くと文が壊れる）。
    # 言語名の後ろに`{width=50%}`のようなPandoc風のサイズ指定属性を書ける（#82）。
    # svgはmermaid/plantumlと異なりレンダリング不要（コードそのものが既に完成した画像）だが、
    # 「図/画像を1つ含む」という抽出対象としては同列に扱える（#91）。
    DIAGRAM_OR_IMAGE_RE = re.compile(
        r'```(?P<lang>mermaid|plantuml|dot|graphviz|svg|d2)(?P<attrs>[ \t]+\{[^}\r\n]*\})?[ \t]*\r?\n(?P<code>.*?)\r?\n```'
        r'|^[ \t]*(?P<image>!\[[^\]]*\]\([^)\n]+\))[ \t]*\r?$',
        re.MULTILINE | re.DOTALL)

    # フェンスのinfo string（'mermaid'や'{width=50% height=8cm}'の中身）からwidth=/height=を
    # 取り出す。値に空白は使えない前提（Typstの寸法値・パーセントはいずれも空白を含まないため）。
    FENCE_ATTR_RE = re.compile(r'(\w+)=([^\s{}]+)')

    def _parse_layout_ratio(self, attrs_str, default):
        """'{left=30 right=70}'の中身からleft/rightのfr比率を取り出す（#83）。属性ブロックが
        無ければdefaultをそのまま返す。`width`/`height`ではなく`left`/`right`という属性名なのは、
        #82の画像サイズ指定（Typst寸法値としてのwidth/height）と意味が衝突しないようにするため。
        片方だけ指定された場合はもう片方をdefault側の値で補う。数値の妥当性チェックは行わない
        （layout-columnsのnと同様、バリデーションは追加しない方針）。"""
        if not attrs_str:
            return default
        attrs = dict(self.FENCE_ATTR_RE.findall(attrs_str))
        left = attrs.get('left')
        right = attrs.get('right')
        if left is None and right is None:
            return default
        return (int(left) if left is not None else default[0],
                int(right) if right is not None else default[1])

    def _render_layout_block(self, inner_text, flip=False, ratio=(35, 65)):
        """::: layout-right / layout-left ... ::: ブロックを、テキストと図（mermaid/plantuml/dot/
        graphviz/svgまたはMarkdown画像）の2カラムgridへ変換する。flip=Trueならlayout-leftとして
        図を左・テキストを右に配置する（#81）。ratioは(左, 右)のfr比率"""
        block_name = 'layout-left' if flip else 'layout-right'
        match = self._search_outside_fences(self.DIAGRAM_OR_IMAGE_RE, inner_text)
        if not match:
            self._error_here(f"'{block_name}' block in {self.current_file} must contain exactly one "
                  "```mermaid/```plantuml/```dot/```graphviz/```svg/```d2 fence or a standalone image.")
            sys.exit(1)
        surrounding_md = (inner_text[:match.start()] + inner_text[match.end():]).strip()
        text_typst = self._render_markdown_segment(surrounding_md, False).strip()
        image_typst = self._render_diagram_or_image_match(match).strip()
        left_fr, right_fr = ratio
        cells = [image_typst, text_typst] if flip else [text_typst, image_typst]
        align = "(center + horizon, left + top)" if flip else "(left + top, center + horizon)"
        return (
            "#grid(\n"
            f"  columns: ({left_fr}fr, {right_fr}fr),\n"
            "  column-gutter: 1.5em,\n"
            f"  align: {align},\n"
            f"  [{cells[0]}],\n"
            f"  [{cells[1]}],\n"
            ")\n\n"
        )

    def _render_compare_block(self, inner_text):
        """::: layout-compare ... ::: ブロックを、2つの図（mermaid/plantuml/dot/graphviz/svg/d2または
        Markdown画像。種類は混在可）を左右に並べた2カラムgridへ変換する。
        各図の直前にあるテキスト（キャプション）は、その図と同じ列にまとめて配置する。"""
        matches = self._finditer_outside_fences(self.DIAGRAM_OR_IMAGE_RE, inner_text)
        if len(matches) != 2:
            self._error_here(f"'layout-compare' block in {self.current_file} must contain exactly two "
                  f"```mermaid/```plantuml/```dot/```graphviz/```svg/```d2 fences or images (found {len(matches)}).")
            sys.exit(1)
        cells = []
        prev_end = 0
        for i, m in enumerate(matches):
            caption_md = inner_text[prev_end:m.start()].strip()
            # 2番目以降の図の後ろに残ったテキストは、最後の列にまとめて含める
            trailing_md = inner_text[matches[-1].end():].strip() if i == len(matches) - 1 else ""
            caption_typst = self._render_markdown_segment(caption_md, False).strip() if caption_md else ""
            image_typst = self._render_diagram_or_image_match(m).strip()
            trailing_typst = self._render_markdown_segment(trailing_md, False).strip() if trailing_md else ""
            cell = "\n\n".join(t for t in [caption_typst, image_typst, trailing_typst] if t)
            cells.append(cell)
            prev_end = m.end()
        columns_typst = ",\n".join(f"  [{cell}]" for cell in cells)
        return (
            "#grid(\n"
            "  columns: (1fr, 1fr),\n"
            "  column-gutter: 1.5em,\n"
            "  align: (left + top, left + top),\n"
            f"{columns_typst},\n"
            ")\n\n"
        )

    def _render_feature_image(self, match):
        """layout-feature内の図/画像を、フルブリード表示用のTypstコードへ変換する（#78）。
        「写真が主役」という趣旨に合わせ、Markdown画像はalt側のwidth/height指定（あれば）を
        無視してwidth/height: 100%・fit: "cover"で枠いっぱいに敷き詰める（枠の高さ自体は
        FEATURE_IMG_HEIGHTで固定するため、はみ出しはfit:coverのトリミングで吸収される）。
        mermaid/plantuml/dot/graphviz/svg/d2フェンスは想定外の使い方だが、#77の汎用抽出をそのまま通し、
        既存のfit-image表示（高さ上限あり・cover表示ではない）に委ねる。フェンス側のwidth/height
        属性（#82）はcover化の対象外（画像と同じ強制はしない）なので、他のブロックと同様に
        そのまま反映する。"""
        if match.group('lang'):
            width, height = self._parse_size_attrs(match.group('attrs'))
            return self._render_diagram_fence(match.group('lang'), match.group('code'), width, height).strip()
        src_match = re.match(r'!\[[^\]]*\]\(([^)]+)\)', match.group('image'))
        return f'#image("{self._resolve_asset(src_match.group(1))}", width: 100%, height: 100%, fit: "cover")'

    def _render_feature_block(self, inner_text):
        """::: layout-feature ... ::: ブロックを、写真（または図）をフルブリードで敷き、
        下部に半透明の帯とキャッチコピーを重ねるレイアウトへ変換する（#78）。
        図/画像の抽出はlayout-right/layout-compareと同じDIAGRAM_OR_IMAGE_REを再利用する（#77）。"""
        match = self._search_outside_fences(self.DIAGRAM_OR_IMAGE_RE, inner_text)
        if not match:
            self._error_here(f"'layout-feature' block in {self.current_file} must contain exactly one "
                  "```mermaid/```plantuml/```dot/```graphviz/```svg/```d2 fence or a standalone image.")
            sys.exit(1)
        catchcopy_md = (inner_text[:match.start()] + inner_text[match.end():]).strip()
        catchcopy_typst = self._render_markdown_segment(catchcopy_md, False).strip()
        image_typst = self._render_feature_image(match)
        return (
            f'#box(width: 100%, height: {self.FEATURE_IMG_HEIGHT})[\n'
            f"  {image_typst}\n"
            "  #place(bottom + left)[\n"
            "    #block(width: 100%, inset: (x: 1.5em, y: 1em), "
            "fill: gradient.linear(rgb(\"#00000000\"), rgb(\"#000000B3\"), angle: 90deg))[\n"
            f"      #text(fill: white, size: 24pt, weight: \"bold\")[{catchcopy_typst}]\n"
            "    ]\n"
            "  ]\n"
            "]\n\n"
        )

    def _render_columns_block(self, attrs_str, inner_text):
        """::: layout-columns ... ::: (または ::: layout-columns {n=N} ... :::) ブロックを、
        TypstのN列columns()コンテナへ流し込む（省略時2列、#78）。layout-right/layout-compareと
        違い中身の種類を判別する必要がなく「N列に流し込む」という見た目の指定に過ぎないため、
        Fail-fastのバリデーションは設けず任意のMarkdownを許す。
        columns()はコンテナの高さを超えて初めて次列へあふれる仕組みのため、スライドのように
        本文が短く1列の高さに収まってしまう場合は素朴に#columns(N)[...]と書いても分割されない
        （実機確認で判明）。measure()で中身の自然な高さを測り、その1/N（+わずかな余裕）を
        コンテナの高さとして明示することで、あふれを強制してN列に均等分割する。"""
        attrs = dict(self.FENCE_ATTR_RE.findall(attrs_str)) if attrs_str else {}
        count = int(attrs['n']) if 'n' in attrs else 2
        content_typst = self._render_markdown_segment(inner_text, False).strip()
        return (
            f'#let _columns_content = [{content_typst}]\n'
            "#layout(size => {\n"
            "  let h = measure(_columns_content, width: size.width).height\n"
            f"  block(height: h / {count} + 1pt)[\n"
            f"    #columns({count}, gutter: 1.5em, _columns_content)\n"
            "  ]\n"
            "})\n\n"
        )

    def _render_takahashi_block(self, attrs_str, inner_text):
        """::: layout-takahashi ... ::: ブロックを、中身（任意のMarkdown）を画面の上下左右中央に
        大きな文字で表示するレイアウトへ変換する（高橋メソッド、#95）。`{size=...}`で
        TAKAHASHI_DEFAULT_SIZEを上書きできる。layout-right の left=/right= 等と同じく、
        size の値自体の妥当性チェックは行わない（不正値はTypst側の#text()呼び出しが
        コンパイルエラーになる）。"""
        attrs = dict(self.FENCE_ATTR_RE.findall(attrs_str)) if attrs_str else {}
        size = attrs.get('size', self.TAKAHASHI_DEFAULT_SIZE)
        content_typst = self._render_markdown_segment(inner_text, False).strip()
        return f'#align(center + horizon)[#text(size: {size})[{content_typst}]]\n\n'

    def _render_align_block(self, attrs_str, inner_text):
        """::: align {align=center} / ::: align {align=right} ... ::: ブロックを、中身
        （任意のMarkdown、複数行・複数段落可）を#align()でラップして中央寄せ・右寄せにする
        （#87）。画像のalign属性（#75）と同じく、著者が明示的に指定できるオプションとして
        追加したもので、`{align=...}`を省略した場合は既定の左寄せのまま変わらない。
        layout-columnsと同様、中身の種類を判別する必要が無いためFail-fastのバリデーションは
        設けない。`align=`に`left`/`center`/`right`以外の値を指定した場合の妥当性チェックも
        行わない（他の独自属性と同じ無検証方針。不正な値はTypst側の#align()呼び出しが
        コンパイルエラーになる）。"""
        attrs = dict(self.FENCE_ATTR_RE.findall(attrs_str)) if attrs_str else {}
        align = attrs.get('align', 'left')
        content_typst = self._render_markdown_segment(inner_text, False).strip()
        return f'#align({align})[{content_typst}]\n\n'
