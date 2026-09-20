"""markdown-it-pyのASTを、Typst構文へ変換するレンダラー（`TypstRenderer`）。"""
import os
import re
import sys
from pathlib import Path
from markdown_it import MarkdownIt
# タスクリスト(- [ ]/- [x])はGFM拡張のためcommonmarkプリセットに含まれず、mdit-py-pluginsの
# プラグインとして追加する（#48）。
from mdit_py_plugins.tasklists import tasklists_plugin
# 文字色指定（#46）。[text]{color=red}というPandoc由来のブラケット+属性記法をパースする
# （spans=Trueでspan_open/span_closeトークンとして出力される。既定では無効なので明示的に有効化）。
from mdit_py_plugins.attrs import attrs_plugin
from text_compositor.config import yaml
from text_compositor.log import _error
from text_compositor.mermaid import MermaidBrowser
from text_compositor.typst_literal import escape_string_literal
# 責務ごとに、ミックスインへ分けてある（#225）。状態（self._mermaidなど）は、TypstRendererが持ち、全ミックスインで共有する。
#   DiagramMixin: 図のフェンスの描画と、SVGのキャッシュ / LayoutMixin: `:::`のレイアウトブロック / InlineMixin: インライン要素
#   TableMixin: 表・CSV / TokenMixin: markdown-itのトークン列の走査（ブロック要素）
# _diagram_cache_keyは、ここから読む側（テスト）があるため、再エクスポートする。
from text_compositor.renderer_diagrams import DiagramMixin, _diagram_cache_key  # noqa: F401
from text_compositor.renderer_inline import InlineMixin
from text_compositor.renderer_layout import LayoutMixin
from text_compositor.renderer_tables import TableMixin
from text_compositor.renderer_tokens import TokenMixin


class TypstRenderer(DiagramMixin, LayoutMixin, InlineMixin, TableMixin, TokenMixin):
    """
    markdown-it-py が生成したAST（構文木）を走査し、
    安全かつ正確にTypst構文へ変換するカスタムレンダラー
    """

    # 冒頭のfront-matter（Marp/Jekyll形式）。CommonMarkでは水平線+段落に見えてしまうため先に切り離す
    FRONT_MATTER_RE = re.compile(
        r'\A﻿?---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)', re.DOTALL)

    # front-matter のうちMarp固有で本ツールでは意味を持たないキー。
    # header/footer/paginateは#42でlandscape/paper_sizeと同じ弱い優先順位で適用する対象に昇格した
    # （chapters[]の明示指定が無い場合のみ使われる）ため、ここには含めない。
    MARP_ONLY_KEYS = {'marp', 'theme', 'size', 'class', 'style', 'backgroundColor'}

    def _fenced_char_ranges(self, text):
        """LAYOUT_BLOCK_RE/DIAGRAM_OR_IMAGE_REは、markdown-itの通常のASTフローを経由しない、生テキスト
        段階での正規表現マッチである（#11、#77）。そのため、使い方説明用のサンプルコードのように
        外側の```/````フェンスで囲まれた範囲の中にたまたま`:::`ブロックや図表フェンス・画像参照と
        同じ見た目の文字列があると、本物のレイアウトブロック/図表として誤検出してしまう（#85）。
        textをmarkdown-itで一度パースし、最上位のfenceトークンが占める行範囲を文字オフセット範囲へ
        変換して返す。ネストした```はCommonMarkの仕様上、外側フェンスの中身の一部として扱われ、
        個別のfenceトークンとしては現れないため、この範囲を「保護区間」として使える。"""
        tokens = self.md.parse(text)
        fence_line_maps = [t.map for t in tokens if t.type == 'fence' and t.map]
        if not fence_line_maps:
            return []
        line_starts = [0]
        for line in text.splitlines(keepends=True):
            line_starts.append(line_starts[-1] + len(line))
        ranges = []
        for start_line, end_line in fence_line_maps:
            start_off = line_starts[start_line] if start_line < len(line_starts) else len(text)
            end_off = line_starts[end_line] if end_line < len(line_starts) else len(text)
            ranges.append((start_off, end_off))
        return ranges

    @staticmethod
    def _in_ranges(offset, ranges):
        # 厳密な不等号(start <)にしているのは、探している対象そのもの（layout-right等の中に
        # 実際に置かれた図表フェンス自身）と、外側フェンスに包まれた説明用サンプルの中に
        # ネストして現れる同じ見た目の文字列とを区別するため（#127）。ネストした場合、実際の
        # マッチ開始位置は必ず外側フェンス（保護区間）の開始位置より後ろに来る。一方、探している
        # 対象自身が最上位のfenceトークンである場合、マッチ開始位置は保護区間の開始位置と
        # 完全に一致する。start<=だと後者まで誤って除外してしまい、layout-right等の中に本物の
        # 図表フェンスを置くという主目的そのものが常に失敗していた。
        return any(start < offset < end for start, end in ranges)

    def _finditer_outside_fences(self, regex, text):
        """regex.finditer(text)のうち、_fenced_char_rangesで求めた保護区間（外側フェンスの中）に
        あるマッチを除外して返す（#85）。"""
        ranges = self._fenced_char_ranges(text)
        return [m for m in regex.finditer(text) if not self._in_ranges(m.start(), ranges)]

    def _search_outside_fences(self, regex, text):
        """_finditer_outside_fencesの最初の1件版（.search()相当、#85）。"""
        matches = self._finditer_outside_fences(regex, text)
        return matches[0] if matches else None

    def __init__(self, base_dir=None, typst_root=None, mermaid_enabled=True, mermaid_auto_download=False,
                 plantuml_enabled=True, plantuml_auto_download=True, d2_enabled=True, d2_auto_download=True,
                 glossary_enabled=False, line_mapping="block", marp_compat=False, variables=None,
                 mermaid_browser=None, csv_header=True, graphviz_enabled=True, cache_dir=None, pikchr_enabled=True):
        # 図のSVGのキャッシュの置き場所。既定は、原稿の隣の.text-compositor/cache/（PDFもHTMLも、共有する）。
        # ViewerのHTML出力は、原稿のフォルダを汚さないため、アプリの領域を渡す（#258）。
        self.cache_dir = os.path.abspath(cache_dir) if cache_dir else None
        # plugins.graphviz（既定true）。PDFでは、Typst側のプリアンブルが使う。HTML出力では、falseなら、Graphvizの
        # フェンスを、素のコードのまま表示する（他の図の、無効のときと同じ。#181）。
        self.graphviz_enabled = graphviz_enabled
        # plugins.pikchr（既定true。#213）。falseなら、```pikchrフェンスを、素のコードのまま表示する（他の図の、無効のときと同じ）。
        self.pikchr_enabled = pikchr_enabled
        # .csvの1行目を、ヘッダー行にするか（#220）。document.csv_header（既定true）が、csv_header引数。
        # chapters[].csv_headerが、章ごとに、self.csv_headerを上書きする（_render_markdown_chapter）。
        self.csv_header_default = csv_header
        self.csv_header = csv_header
        # 見出しレベルのオフセット（#68）。section配下の章で、Markdown本来のH1をH2以下へずらし、
        # sectionの章見出し（H1）の配下に入れるために使う。章ごとに_render_markdown_chapterが設定する。
        self.heading_offset = 0
        # variables: {{KEY}}プレースホルダの置換表（#72）。Noneなら置換機構自体を無効にし、
        # 本文中の{{...}}には一切触れない（configに`variables:`が無い既存プロジェクトの互換性維持）。
        self.variables = variables
        # 対応するMarkdown記法のスコープはGFM + GitHub Wiki（#48）。table/strikethroughはGFM拡張だが
        # commonmarkプリセットにコアルールとして同梱されており、enable()するだけで使える。
        self.md = (MarkdownIt("commonmark").enable("table").enable("strikethrough")
                   .use(tasklists_plugin)
                   .use(attrs_plugin, spans=True, span_after="link", allowed=["color", "size", "bg", "border"]))
        self.list_stack = []
        self._block_line = None
        self.current_file = ""
        self.current_dir = ""
        # base_dir: プロジェクト側の基準ディレクトリ（画像・mermaidキャッシュの相対パス解決に使う）
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        # typst_root: typst compile の --root と同じ値。base_dirとツール本体(templates/)の
        # 両方を跨いでも解決できるよう、image()呼び出しはこれを起点にルート絶対パスで組み立てる
        self.typst_root = typst_root or os.path.dirname(self.base_dir)
        self.allow_exec = False
        self.front_matter = {}
        # plugins.mermaid: false（6章、#21）。falseなら```mermaidフェンスをヘッドレスブラウザで
        # 描画せず、他の未対応言語と同じく素のコード表示にフォールバックする。
        self.mermaid_enabled = mermaid_enabled
        self._mermaid_disabled_warned = False
        # plugins.mermaid_auto_download: false（既定。#22の設計議論を踏まえて追加）。システムに
        # Chrome/Edgeが無い場合、falseならFail-fast（従来どおり）、trueならPlaywright自身の
        # Chromiumをダウンロードして使う（実測約700MB。#34/#35で避けた重いダウンロードそのものなので
        # 既定はfalseのまま。手元にどうしても持っていない場合の最後の手段として明示的に選ばせる）。
        self.mermaid_auto_download = mermaid_auto_download
        # Mermaidレンダリング用ヘッドレスブラウザのライフサイクル状態。最初のmermaid図を描画する
        # ときに遅延起動し、ビルド終了時にclose()で片付ける（複数の図で1つのブラウザ・ページを
        # 使い回し、図ごとに起動し直さない）。
        self._mermaid = mermaid_browser if mermaid_browser is not None else MermaidBrowser()
        self._owns_mermaid = mermaid_browser is None
        # document.table_header / chapters[].table_headerのマージ結果（#45）。
        # _render_markdown_chapterが章ごとに設定する。bold/background/colorいずれも
        # 未指定なら従来どおり無装飾（キーが無ければ何もしない）。
        self.table_header_style = {}
        # document.glossary: false（既定。#47）。falseなら[[用語]]は素の文字列としてそのまま通す
        # （trueの場合のみWIKILINK_REで検出・登録する）。用語ごとの出現ラベルID一覧を、全チャプター
        # を跨いで蓄積する（dict、Python 3.7+で挿入順を保持。ビルド末尾で巻末索引の生成に使う）。
        self.glossary_enabled = glossary_enabled
        self.glossary_terms = {}
        # document.marp_compat: false（既定、#92）。falseならCommonMark準拠で、hr（---/***/___の
        # いずれも）は単なる水平線として描画し、改ページは<!-- pagebreak -->で明示する。trueなら
        # 実際のMarpit（---/***/___のいずれもスライド区切りとして扱う）に忠実に、hrを一律
        # 改ページとして描画する（従来の挙動）。
        self.marp_compat = marp_compat
        self._glossary_label_counter = 0
        # plugins.plantuml: true（既定。#22）。falseなら```plantumlフェンスをローカルのjava+
        # plantuml.jarで描画せず、他の未対応言語と同じく素のコード表示にフォールバックする。
        self.plantuml_enabled = plantuml_enabled
        self._plantuml_disabled_warned = False
        # plugins.plantuml_auto_download: true（既定）。システムにJava 11+が無い場合、trueなら
        # Eclipse Temurin JREを自動取得（実測約49.7MB。Chromiumの約700MBと違い許容できる規模）、
        # falseならFail-fast。mermaidと非対称な既定値なのは意図的（ダウンロードされる実体の
        # サイズが1桁違うため。#22の設計議論を参照）。
        self.plantuml_auto_download = plantuml_auto_download
        # java実行ファイル・plantuml.jarのパスは初回の```plantuml描画時に遅延解決する
        # （mermaidのヘッドレスブラウザと異なり常駐プロセスではないため、都度subprocessで起動する）。
        self._plantuml_java_bin = None
        self._plantuml_jar_path = None
        # plugins.d2: true（既定。#90）。falseなら```d2フェンスをローカルのD2 CLIバイナリで
        # 描画せず、他の未対応言語と同じく素のコード表示にフォールバックする。
        self.d2_enabled = d2_enabled
        self._d2_disabled_warned = False
        # plugins.d2_auto_download: true（既定）。システムにdコマンドが無い場合、trueならD2公式
        # CLIバイナリを自動取得（実測約13MB。plantumlのJRE(約49.7MB)よりさらに小さいため、
        # plantuml_auto_downloadと同じくtrueを既定にする。#22の設計議論を参照）、falseならFail-fast。
        self.d2_auto_download = d2_auto_download
        # d2実行ファイルのパスは初回の```d2描画時に遅延解決する（plantumlのjava/jarと同様）。
        self._d2_bin = None
        # キャッシュキー用のd2バージョン（#26）。キャッシュヒット時にバイナリの自動取得を
        # 起こさないよう、_d2_binの解決とは別に遅延評価する。
        self._d2_version_cache = None
        # document.diagnostics.line_mapping: "block"（既定、#27）。Typstコンパイルエラーの行番号を
        # 元のMarkdownの行番号へ逆引きするための行コメント（`// @srcmap ...`）を生成コードに
        # 挿し込むかどうかの精度。"off"なら挿し込まず、従来どおりTypst側の生の行番号のみになる。
        # リスト項目・テーブル行単位まで踏み込む"fine"は将来課題（Typstのリスト継続判定への
        # 影響を実機検証してから対応する）。
        self.line_mapping = line_mapping

    # 拡張子ごとの構造化データ言語（Typstのraw()に渡すシンタックスハイライト名）。
    # 入力となるテキストファイルはMarkdownに限らない（1章、#15）。
    STRUCTURED_TEXT_LANGS = {'.yaml': 'yaml', '.yml': 'yaml', '.json': 'json'}

    # 図表ソースファイルそのものをchaptersに直接指定できる拡張子（#53）。Markdown内の
    # フェンスコードブロックと同じ描画機構をそのまま流用する（新しい描画ロジックは書かない）。
    # .iumlはPlantUMLの!includeで取り込む断片ファイル用の慣習であり、単体の図として
    # 使われないため対象外。
    DIAGRAM_FILE_EXTS = {
        '.dot': 'graphviz', '.gv': 'graphviz',
        '.mmd': 'mermaid',
        '.puml': 'plantuml', '.plantuml': 'plantuml', '.pu': 'plantuml',
        '.d2': 'd2',
        '.pikchr': 'pikchr',
    }

    def render_chapter(self, text, filepath="", drop_leading_title=False):
        """chaptersの1ファイルを拡張子に応じて変換する（1章、#15）。
        .md/.markdown以外はmarkdown-itに一切通さない。素のテキストやYAML/JSON中の
        行頭記号（#, -, [ 等）がMarkdown構文として誤解釈され、静かに壊れるのを防ぐため。"""
        ext = os.path.splitext(filepath)[1].lower()
        if ext in ('.md', '.markdown'):
            # 置換はMarkdownのパース前に文字列として行う。見出し・表・コードフェンス・図の中まで
            # 一律に効き、front-matterの値にも及ぶ。素のコードやCSV（Markdown以外）は、{{...}}が
            # 構文として現れうるため対象にしない。
            if self.variables is not None:
                text = self._substitute_variables(text, filepath)
            return self.render(text, filepath=filepath, drop_leading_title=drop_leading_title)

        self.current_file = filepath
        self.current_dir = os.path.dirname(os.path.abspath(filepath)) if filepath else self.base_dir
        self.front_matter = {}

        diagram_kind = self.DIAGRAM_FILE_EXTS.get(ext)
        if diagram_kind == 'graphviz':
            return self._render_raw_text(text, 'dot')
        elif diagram_kind == 'mermaid':
            return self._render_mermaid(text)
        elif diagram_kind == 'plantuml':
            return self._render_plantuml(text)
        elif diagram_kind == 'd2':
            return self._render_d2(text)
        elif diagram_kind == 'pikchr':
            return self._render_pikchr(text)
        elif ext == '.csv':
            return self._render_csv_table(text)

        return self._render_raw_text(text, self.STRUCTURED_TEXT_LANGS.get(ext))

    # {{KEY}}プレースホルダ（#72）。KEYは識別子の形（英数字とアンダースコア、先頭は数字不可）に
    # 限る。{{ message }}のように空白を含む形（Vue/Jinja等のテンプレート記法）は対象外にして、
    # 文書中にそのまま書けるようにする。先頭の\は「置換せず{{KEY}}をそのまま出力する」エスケープ。
    PLACEHOLDER_RE = re.compile(r'(\\)?\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}')

    def _substitute_variables(self, text, filepath):
        """本文中の{{KEY}}をself.variablesの値に置換する。未定義のKEYは、9章のFail-fast方針に
        従い黙って残さずエラー終了する（綴りミスのまま「{{VERSON}}」がPDFに載る事故を防ぐ）。
        同じファイル内の未定義キーはまとめて報告する。"""
        undefined = []

        def replace(m):
            key = m.group(2)
            if m.group(1):
                return '{{' + key + '}}'
            if key not in self.variables:
                lineno = text.count('\n', 0, m.start()) + 1
                undefined.append(f"{filepath}:{lineno}: {{{{{key}}}}}")
                return m.group(0)
            return self.variables[key]

        result = self.PLACEHOLDER_RE.sub(replace, text)
        if undefined:
            _error("Undefined placeholder(s); define them under 'variables:' in the config, "
                  "or write \\{{KEY}} to output the text literally:")
            for entry in undefined:
                print(f"  {entry}")
            sys.exit(1)
        return result

    def _render_raw_text(self, text, lang=None):
        """Markdown以外のテキスト（プレーンテキスト・コード・YAML/JSON等）を、markdown-itを一切
        通さずTypstのraw()で等幅表示する。通常の段落として流し込むとTypstのテキストモードが
        連続する空白を折りたたみ、コードのインデント等が失われるため、raw()で改行・空白とも
        そのまま保持する。lang未指定時（プレーンテキスト・未知拡張子）はシンタックスハイライトなし。
        ```` ``` ````フェンス構文だと本文中に```が含まれた場合に壊れるため、文字列リテラルとして渡す。"""
        escaped = (text.replace('\\', '\\\\').replace('"', '\\"')
                       .replace('\r\n', '\n').replace('\n', '\\n'))
        lang_arg = f'lang: "{lang}", ' if lang else ''
        return f'#raw("{escaped}", {lang_arg}block: true)\n\n'

    def render(self, text, filepath="", drop_leading_title=False):
        self.current_file = filepath
        self.current_dir = os.path.dirname(os.path.abspath(filepath)) if filepath else self.base_dir
        # 【修正】typst-exec は「人間レビュー済み (reviewed/)」配下のみ許可するホワイトリスト方式
        self.allow_exec = "reviewed" in Path(os.path.abspath(filepath)).parts if filepath else False
        text, self.front_matter = self.strip_front_matter(text)

        output = []
        pos = 0
        first_segment = True
        for m in self._finditer_outside_fences(self.LAYOUT_BLOCK_RE, text):
            md_before = text[pos:m.start()]
            if md_before.strip() or first_segment:
                output.append(self._render_markdown_segment(md_before, drop_leading_title and first_segment))
                first_segment = False
            block_kind, attrs_str, block_body = m.group(1), m.group(2), m.group(3)
            if block_kind == 'layout-right':
                output.append(self._render_layout_block(block_body, flip=False,
                                                          ratio=self._parse_layout_ratio(attrs_str, (35, 65))))
            elif block_kind == 'layout-left':
                output.append(self._render_layout_block(block_body, flip=True,
                                                          ratio=self._parse_layout_ratio(attrs_str, (65, 35))))
            elif block_kind == 'layout-compare':
                output.append(self._render_compare_block(block_body))
            elif block_kind == 'layout-feature':
                output.append(self._render_feature_block(block_body))
            elif block_kind == 'layout-takahashi':
                output.append(self._render_takahashi_block(attrs_str, block_body))
            elif block_kind == 'align':
                output.append(self._render_align_block(attrs_str, block_body))
            else:
                output.append(self._render_columns_block(attrs_str, block_body))
            pos = m.end()
        md_after = text[pos:]
        if md_after.strip() or first_segment:
            output.append(self._render_markdown_segment(md_after, drop_leading_title and first_segment))
        return "".join(output)

    def _render_markdown_segment(self, text, drop_leading_title):
        """通常のMarkdown断片をASTベースでTypstへ変換する（layout-rightブロックの前後の地の文用）"""
        self.list_stack = []
        tokens = self.md.parse(text)
        start = self._skip_leading_title(tokens) if drop_leading_title else 0
        return self.render_tokens(tokens, start)

    def _parse_size_attrs(self, attrs_str):
        """フェンスのinfo string中の属性部分（例: '{width=50% height=8cm}'）からwidth/heightを
        取り出す。未指定のキーはNoneのまま返す（#82）。"""
        width = height = None
        if attrs_str:
            for key, val in self.FENCE_ATTR_RE.findall(attrs_str):
                if key == 'width':
                    width = val
                elif key == 'height':
                    height = val
        return width, height

    # layout-featureの写真枠の高さ（スライド本文領域に対する割合）。#78の実機確認で判明した通り、
    # width:100%だけだと縦長写真が大幅にはみ出す（枠の高さが写真任せになるため）。CSSの
    # background-size:coverと同じ考え方で、高さを固定しfit:"cover"で余分をトリミングすることで、
    # 縦長・横長どちらの写真でも枠からはみ出さないようにする。
    FEATURE_IMG_HEIGHT = "70%"

    # layout-takahashiの既定の文字サイズ（#95）。本文既定の10.5pt（templates/template.typ）に
    # 対し、高橋メソッド的な「大きな文字を1つだけ見せる」用途として十分大きい値を採用した。
    # 内容の長さに合わない場合は`{size=...}`属性で上書きできる。
    TAKAHASHI_DEFAULT_SIZE = "96pt"

    def strip_front_matter(self, text):
        """冒頭のfront-matterを本文から除去し、設定として返す。行番号は空行で維持する"""
        m = self.FRONT_MATTER_RE.match(text)
        if not m:
            return text, {}
        meta = {}
        if yaml is None:
            self._warn_here(f"PyYAML is not installed; front-matter in {self.current_file} is ignored.")
        else:
            try:
                loaded = yaml.safe_load(m.group(1))
                if isinstance(loaded, dict):
                    meta = loaded
                else:
                    self._warn_here(f"Front-matter in {self.current_file} is not a mapping; ignored.")
            except Exception as e:
                self._warn_here(f"Failed to parse front-matter in {self.current_file}: {e}")
        for key in meta:
            if key not in self.MARP_ONLY_KEYS and key not in ('title', 'subtitle', 'author', 'date',
                                                              'paper_size', 'landscape', 'font_size',
                                                              'header', 'footer', 'paginate'):
                self._warn_here(f"Unknown front-matter key '{key}' in {self.current_file}")
        if 'font_size' in meta and not self.FONT_SIZE_RE.match(str(meta['font_size'])):
            self._warn_here(f"front-matter 'font_size' in {self.current_file} should look like '16pt'; got {meta['font_size']!r}. Ignoring.")
            del meta['font_size']
        # 除去した行数ぶん改行を残し、以降の警告メッセージの行番号がずれないようにする
        return '\n' * m.group(0).count('\n') + text[m.end():], meta

    # Typstコンパイルエラーの行番号を元のMarkdownの行番号へ逆引きするための目印（#27）。
    # _resolve_project_dirs後の_compile_and_cleanupがtemp_build.typ全体からこの行を
    # 一度スキャンし、「Typstの行番号→(Markdownファイル, 行番号)」の対応表を作る。
    SRCMAP_PREFIX = '// @srcmap '

    def _resolve_asset(self, src):
        """画像の相対パスをMarkdownファイル基準から、typst_root起点のルート絶対パスへ変換する。
        temp_build.typ の実際の置き場所（.text-compositor/ 配下）に依存させないため。"""
        if not src or src.startswith('/') or re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', src):
            return escape_string_literal(src)
        abs_path = os.path.normpath(os.path.join(self.current_dir, src))
        # 仕様9章: 画像パス欠損はフォールバックせず即エラー (Fail-fast)
        if not os.path.exists(abs_path):
            self._error_here(f"Image not found: {abs_path} (referenced from {self.current_file})")
            sys.exit(1)
        root_rel_path = "/" + os.path.relpath(abs_path, self.typst_root).replace(os.sep, '/')
        return escape_string_literal(root_rel_path)

    # 単純な英数字+ハイフンの識別子（例: "red"）のみ、Typstの色定数名として安全に生コード注入できる
    # と判断する。それ以外（"#eeeeee"のようなhex形式や、記号を含む不正な値）はrgb()の文字列引数
    # として渡す（Typstのコンパイルエラーとして安全に失敗する。文字列リテラル内なのでコード注入の
    # 心配もない）。
    COLOR_IDENTIFIER_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9\-]*$')

    # セル単位のborder属性（#89）が取れる値と、対応するTypstのstroke式。太さと色は、Typstの表の
    # 既定の枠線（1pt・黒）に揃える。実線（solid）を明示できるのは、隣のセルの破線と並べたときに
    # 「そのセルだけ実線」を表すため。
    CELL_BORDER_STROKES = {
        'solid': '1pt + black',
        'dashed': '(paint: black, thickness: 1pt, dash: "dashed")',
        'dotted': '(paint: black, thickness: 1pt, dash: "dotted")',
        'none': 'none',
    }
