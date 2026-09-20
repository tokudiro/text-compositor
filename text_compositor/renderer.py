"""markdown-it-pyのASTを、Typst構文へ変換するレンダラー（`TypstRenderer`）。"""
import os
import re
import sys
import csv
import io
import subprocess
import hashlib
from pathlib import Path
from markdown_it import MarkdownIt
# タスクリスト(- [ ]/- [x])はGFM拡張のためcommonmarkプリセットに含まれず、mdit-py-pluginsの
# プラグインとして追加する（#48）。
from mdit_py_plugins.tasklists import tasklists_plugin
# 文字色指定（#46）。[text]{color=red}というPandoc由来のブラケット+属性記法をパースする
# （spans=Trueでspan_open/span_closeトークンとして出力される。既定では無効なので明示的に有効化）。
from mdit_py_plugins.attrs import attrs_plugin
from text_compositor import host_renderers
from text_compositor.config import yaml
from text_compositor.deps import D2_RELEASE, GRAPHVIZ_FIT_REVISION, MERMAID_JS_SHA256, PLANTUML_JAR_SHA256, VIZ_JS_SHA256, _system_d2_version, ensure_d2_binary, ensure_mermaid_js, ensure_plantuml_jar, ensure_temurin_jre, ensure_viz_js, find_system_d2, find_system_java
from text_compositor.env_check import _check_d2, _check_isolated_env, _check_plantuml
from text_compositor.log import _error, _hint, _log_info, _log_verbose, _warn
from text_compositor.mermaid import MermaidBrowser
from text_compositor.typst_literal import escape_string_literal

def _diagram_cache_key(kind, tool_version, code):
    """図のキャッシュキー（#26）。入力テキストだけでなく、種別とレンダラのバージョンも
    ハッシュに含める。レンダラを更新しても同じ入力の古いSVGが使い回される事故を防ぐため。
    各要素の境界に\\0を挟み、「要素の切れ目が違うだけで連結結果が同じ」衝突を避ける。"""
    h = hashlib.sha256()
    for part in (kind, tool_version, code):
        h.update(part.encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()[:16]

class TypstRenderer:
    """
    markdown-it-py が生成したAST（構文木）を走査し、
    安全かつ正確にTypst構文へ変換するカスタムレンダラー
    """
    # 行頭に来るとTypstのブロック記法（見出し/リスト/用語リスト）として解釈される記号
    BLOCK_HEAD_RE = re.compile(r'^([ \t]*)(=+|[-+/]|[0-9]+[.)])(?=\s|$)')

    # 冒頭のfront-matter（Marp/Jekyll形式）。CommonMarkでは水平線+段落に見えてしまうため先に切り離す
    FRONT_MATTER_RE = re.compile(
        r'\A﻿?---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)', re.DOTALL)

    # front-matter のうちMarp固有で本ツールでは意味を持たないキー。
    # header/footer/paginateは#42でlandscape/paper_sizeと同じ弱い優先順位で適用する対象に昇格した
    # （chapters[]の明示指定が無い場合のみ使われる）ため、ここには含めない。
    MARP_ONLY_KEYS = {'marp', 'theme', 'size', 'class', 'style', 'backgroundColor'}

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

    # GitHub形式のalert記法（#61）。`> [!NOTE]`のように、blockquoteの最初の行がこのマーカーだけの
    # ときだけ発動する。テンプレート側は@preview/note-me（MIT、#63でライセンス確認済み）が持つ
    # note/tip/important/warning/cautionをcallout()でラップして呼び出す。
    ALERT_MARKER_RE = re.compile(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$')

    def __init__(self, base_dir=None, typst_root=None, mermaid_enabled=True, mermaid_auto_download=False,
                 plantuml_enabled=True, plantuml_auto_download=True, d2_enabled=True, d2_auto_download=True,
                 glossary_enabled=False, line_mapping="block", marp_compat=False, variables=None,
                 mermaid_browser=None, csv_header=True, graphviz_enabled=True):
        # plugins.graphviz（既定true）。PDFでは、Typst側のプリアンブルが使う。HTML出力では、falseなら、Graphvizの
        # フェンスを、素のコードのまま表示する（他の図の、無効のときと同じ。#181）。
        self.graphviz_enabled = graphviz_enabled
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

    def _render_graphviz(self, lang, code, width=None, height=None):
        """```dot/```graphvizフェンスの内容をTypstコードへ変換する。width/height未指定時は
        raw()化するだけで、Typst側のshow raw.where(lang: "dot"/"graphviz")ショールール
        （テンプレート側のrender-graph、ページ幅超過時のみ自動縮小）に描画を委ねる。showルールは
        it.text（コード文字列）しか受け取れずwidth/heightを渡す経路が無いため、明示指定時は
        raw()経由をやめ、テンプレートが公開しているrender-graph()を直接呼び出すコードを生成する
        （#82）。"""
        if width is None and height is None:
            return self._render_raw_text(code, lang)
        escaped = (code.replace('\\', '\\\\').replace('"', '\\"')
                       .replace('\r\n', '\n').replace('\n', '\\n'))
        width_arg = f', width: {width}' if width else ''
        height_arg = f', height: {height}' if height else ''
        return f'#align(center)[#render-graph("{escaped}"{width_arg}{height_arg})]\n\n'

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

    def _render_diagram_fence(self, lang, code, width=None, height=None):
        """```mermaid/```plantuml/```dot/```graphviz/```svg/```d2フェンスの内容をTypstコードへ
        変換する。通常のMarkdownフロー（render_tokens）とlayout-right/layout-compareブロックの
        双方から共通で呼べるようにした処理（#77）。width/height（#82）が指定された場合、
        mermaid/plantuml/svg/d2は自動縮小（fit-image）をバイパスして直接そのサイズで埋め込み、
        dot/graphvizは_render_graphvizが同様にバイパスする。"""
        if lang == 'mermaid':
            return self._render_mermaid(code, width, height)
        elif lang == 'plantuml':
            return self._render_plantuml(code, width, height)
        elif lang == 'svg':
            return self._render_svg(code, width, height)
        elif lang == 'd2':
            return self._render_d2(code, width, height)
        return self._render_graphviz(lang, code, width, height)

    def _render_diagram_or_image_match(self, m):
        """DIAGRAM_OR_IMAGE_REの1マッチをTypstコードへ変換する。フェンスは_render_diagram_fenceへ、
        単独行のMarkdown画像は通常の画像処理（alt|width=/height=構文込み）をそのまま再利用するため
        _render_markdown_segmentに委譲する（#77）。"""
        if m.group('lang'):
            width, height = self._parse_size_attrs(m.group('attrs'))
            return self._render_diagram_fence(m.group('lang'), m.group('code'), width, height)
        return self._render_markdown_segment(m.group('image'), False).strip()

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

    # layout-featureの写真枠の高さ（スライド本文領域に対する割合）。#78の実機確認で判明した通り、
    # width:100%だけだと縦長写真が大幅にはみ出す（枠の高さが写真任せになるため）。CSSの
    # background-size:coverと同じ考え方で、高さを固定しfit:"cover"で余分をトリミングすることで、
    # 縦長・横長どちらの写真でも枠からはみ出さないようにする。
    FEATURE_IMG_HEIGHT = "70%"

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

    # layout-takahashiの既定の文字サイズ（#95）。本文既定の10.5pt（templates/template.typ）に
    # 対し、高橋メソッド的な「大きな文字を1つだけ見せる」用途として十分大きい値を採用した。
    # 内容の長さに合わない場合は`{size=...}`属性で上書きできる。
    TAKAHASHI_DEFAULT_SIZE = "96pt"

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

    def _warn_here(self, message, line=None):
        """現在処理中の原稿（current_file）の位置つきで警告を出す（Python APIの診断のfile/line、#167）。"""
        _warn(message, file=self.current_file or None, line=line)

    def _error_here(self, message, line=None, **kwargs):
        """現在処理中の原稿（current_file）の位置つきでエラーを出す（呼び出し側が、sys.exitで止める）。"""
        _error(message, file=self.current_file or None, line=line, **kwargs)

    def _diagram_error(self, tool, output, line=None):
        """図の描画の失敗を、エラーとして出す（呼び出し側が、sys.exitで止める）。
        messageは短い要約にし、ツールの出力は、detailへ入れる（Viewerが、帯には要約だけを出し、詳細を別に見せる。#202）。
        CLIの表示は、従来どおり（原稿のパスと、ツールの出力を、そのまま出す）。"""
        output = (output or "").strip()
        self._error_here(f"{tool} diagram failed to render", line=line, detail=output or None,
                         cli_text=f"{tool} rendering failed for {self.current_file}:\n{output}")

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

    # Typstコンパイルエラーの行番号を元のMarkdownの行番号へ逆引きするための目印（#27）。
    # _resolve_project_dirs後の_compile_and_cleanupがtemp_build.typ全体からこの行を
    # 一度スキャンし、「Typstの行番号→(Markdownファイル, 行番号)」の対応表を作る。
    SRCMAP_PREFIX = '// @srcmap '

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

    def _ensure_mermaid_page(self):
        """Mermaid描画用のブラウザ・ページを返す（初回のみ起動。詳細はMermaidBrowser.ensure_page）。"""
        return self._mermaid.ensure_page(self.mermaid_enabled, self.mermaid_auto_download)

    def close(self):
        """ビルド終了時に呼び出す。Mermaid用のブラウザは、このレンダラーが持つ場合だけ片付ける。
        外から渡された（api.Sessionが使い回す）ものは、渡した側が片付ける。"""
        if self._owns_mermaid:
            self._mermaid.close()

    def _render_sized_image(self, root_rel_path, width, height):
        """事前レンダリング済み画像（mermaid/plantumlのSVG）をTypstコードへ変換する。
        width/height未指定ならfit-image()（はみ出し防止の自動縮小のみ、拡大はしない）、
        明示指定時は自動縮小をバイパスして#image()へそのままwidth/heightを渡す
        （通常のMarkdown画像のalt|width=構文と同じ挙動。拡大も含めて指定値どおりになる、#82）。"""
        if width or height:
            width_arg = f', width: {width}' if width else ''
            height_arg = f', height: {height}' if height else ''
            return f'#align(center)[#image("{root_rel_path}"{width_arg}{height_arg})]\n\n'
        return f'#align(center)[#fit-image("{root_rel_path}")]\n\n'

    def _svg_fence_path(self, code):
        """```svgフェンスの内容を、キャッシュ用の.svgファイルへ書き出し、そのパスを返す。mermaid/plantumlと
        異なりSVGは既にテキストで完結したベクター画像フォーマットのため、外部レンダリングエンジンは
        呼ばず、コードをそのまま書き出すだけでよい（#91）。"""
        cache_dir = os.path.join(self.base_dir, ".text-compositor", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        digest = hashlib.sha256(code.encode('utf-8')).hexdigest()[:16]
        svg_path = os.path.join(cache_dir, f"svg_{digest}.svg")

        if not os.path.exists(svg_path):
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(code)
        return svg_path

    def _render_svg(self, code, width=None, height=None):
        """```svgフェンスの内容をTypstのimage呼び出しに変換する（#91）。"""
        svg_path = self._svg_fence_path(code)
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _diagram_cache_path(self, kind, tool_version, code):
        """図のSVGキャッシュのパスとキー（ハッシュ）を返す。キーの設計は_diagram_cache_key()参照（#26）。"""
        cache_dir = os.path.join(self.base_dir, ".text-compositor", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        digest = _diagram_cache_key(kind, tool_version, code)
        return os.path.join(cache_dir, f"{kind}_{digest}.svg"), digest

    def _d2_version(self):
        """キャッシュキーに使うd2のバージョン。システムのd2があればその実バージョン、無ければ
        自動取得の対象（D2_RELEASE）。どちらの場合も、ここではバイナリの取得は行わない。"""
        if self._d2_version_cache is None:
            system_d2 = find_system_d2()
            version = _system_d2_version(system_d2) if system_d2 else None
            self._d2_version_cache = version or D2_RELEASE
        return self._d2_version_cache

    def _render_mermaid(self, code, width=None, height=None):
        """mermaidブロックをヘッドレスブラウザ上のmermaid.render()でSVG化し、Typstのimage呼び出しに
        変換する。外部APIへの通信は行わず、ローカルのブラウザで完結させる（仕様書10章・11章、#35）。"""
        svg_path = self._mermaid_svg_path(code)
        if svg_path is None:
            return f"```mermaid\n{code}```\n\n"
        # fit-image() は templates/slide.typ 側で定義されているため、image() の相対パス解決基準は
        # base_dir ではなく templates/ になってしまう。ファイルの置き場所に依存しない
        # ルート絶対パス（--root 起点の "/..." 形式）にして、どこから呼んでも解決できるようにする。
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _mermaid_svg_path(self, code, line=None):
        """mermaidの図のSVG（キャッシュ）のパスを返す。無ければ、ヘッドレスブラウザで描画して作る。
        plugins.mermaid: falseなら、何も作らずNoneを返す（呼び出し側が、素のコード表示にフォールバックする）。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        if not self.mermaid_enabled:
            if not self._mermaid_disabled_warned:
                _log_info(f"plugins.mermaid is disabled; leaving ```mermaid fences as plain code (first seen in {self.current_file}).")
                self._mermaid_disabled_warned = True
            return None

        # 固定済みmermaid.min.jsのSHA256をバージョンとして使う（バンドルが変われば別キーになる）
        svg_path, digest = self._diagram_cache_path("mermaid", MERMAID_JS_SHA256, code)

        if not os.path.exists(svg_path):
            host = host_renderers._mermaid_host_renderer
            _log_info(f"Rendering mermaid diagram via {'the host application' if host else 'headless browser'} -> {os.path.basename(svg_path)}")
            try:
                if host:
                    # 描画は、呼び出し元（ViewerのElectron）が行う。mermaid.min.jsの取得・検証は、こちらで行い、パスを渡す
                    svg = host(f"mermaid-{digest}", code, ensure_mermaid_js())
                else:
                    page = self._ensure_mermaid_page()
                    svg = page.evaluate(
                        """async ([id, code]) => {
                            const { svg } = await mermaid.render(id, code);
                            return svg;
                        }""",
                        [f"mermaid-{digest}", code],
                    )
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                # ブラウザの例外に付く、mermaid.jsの内部のスタック（"    at ..."の行）は、原因の理解に役立たないため省く
                message = "\n".join(l for l in str(e).splitlines() if not re.match(r"\s+at ", l))
                self._diagram_error("mermaid", message, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached mermaid diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _graphviz_svg_path(self, code, line=None):
        """Graphvizの図のSVG（キャッシュ）のパスを返す。無ければ、呼び出し元（ViewerのElectronのChromium上のViz.js）で作る（#181）。
        呼び出し側が、_graphviz_host_rendererの有無を確かめてから、呼ぶこと。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        # キーには、Viz.jsのSHA256と、文字幅の補正（ホスト側）の版を入れる。どちらかが変われば、別のキーになる
        svg_path, digest = self._diagram_cache_path("graphviz", f"{VIZ_JS_SHA256}+fit{GRAPHVIZ_FIT_REVISION}", code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering Graphviz diagram via the host application -> {os.path.basename(svg_path)}")
            try:
                svg = host_renderers._graphviz_host_renderer(f"graphviz-{digest}", code, ensure_viz_js())
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                self._diagram_error("Graphviz", str(e), line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached Graphviz diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _ensure_plantuml_tools(self):
        """PlantUML実行に必要なjava実行ファイルとplantuml.jarを遅延解決する（初回のみ）。
        システムJava（11+）があればそのまま再利用する（2章の最小限のダウンロード）。無い場合、
        plugins.plantuml_auto_download（既定true）ならEclipse Temurin JREを自動取得し、falseなら
        Fail-fastでエラー終了する。mermaidのブラウザ自動取得（既定false）と非対称な既定値なのは、
        ダウンロードされる実体のサイズが一桁違うため（JRE約49.7MB対Chromium約700MB。#22の設計議論）。"""
        if self._plantuml_java_bin is None:
            java_bin = find_system_java()
            if java_bin:
                _log_info(f"Reusing system Java for PlantUML rendering: {java_bin}")
            elif self.plantuml_auto_download:
                java_bin = ensure_temurin_jre()
            else:
                _error("No local Java 11+ found; required to render PlantUML diagrams. "
                      "Install Java 11+, or set plugins.plantuml_auto_download: true "
                      "(downloads Eclipse Temurin JRE, approx. 50MB), or set plugins.plantuml: false.")
                sys.exit(1)
            self._plantuml_java_bin = java_bin
        if self._plantuml_jar_path is None:
            self._plantuml_jar_path = ensure_plantuml_jar()
        return self._plantuml_java_bin, self._plantuml_jar_path

    def _render_plantuml(self, code, width=None, height=None):
        """```plantumlブロックをローカルのjava+plantuml.jar（Smetanaレイアウトエンジン。dot等の
        外部バイナリに依存しない）でSVG化し、Typstのimage呼び出しに変換する。外部APIへの通信は
        行わない（仕様書10章・11章、#22）。コードは実際のPlantUML構文どおり@startuml/@enduml
        込みで書く必要がある（暗黙の補完はしない。9章の決定論的出力・明示性の方針に沿う）。"""
        svg_path = self._plantuml_svg_path(code)
        if svg_path is None:
            return f"```plantuml\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _plantuml_svg_path(self, code, line=None):
        """plantumlの図のSVG（キャッシュ）のパスを返す。無ければ、ローカルのjava+plantuml.jarで作る。
        plugins.plantuml: falseなら、何も作らずNoneを返す。line: 失敗時の診断に付ける行。"""
        if not self.plantuml_enabled:
            if not self._plantuml_disabled_warned:
                _log_info(f"plugins.plantuml is disabled; leaving ```plantuml fences as plain code (first seen in {self.current_file}).")
                self._plantuml_disabled_warned = True
            return None

        svg_path, _ = self._diagram_cache_path("plantuml", PLANTUML_JAR_SHA256, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering PlantUML diagram via local Java -> {os.path.basename(svg_path)}")
            java_bin, jar_path = self._ensure_plantuml_tools()
            try:
                result = subprocess.run(
                    [java_bin, "-jar", jar_path, "-tsvg", "-pipe", "-Playout=smetana"],
                    input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
            except OSError as e:
                self._error_here(f"Failed to run PlantUML for {self.current_file}:\n{e}")
                # 隔離環境（venv/pipx）外での実行が原因の可能性が高い（#113、ファイルが
                # 存在するように見えてもサブプロセスから見えない既知の問題）ため優先して案内する。
                for diag in (_check_isolated_env(), _check_plantuml(self.plantuml_enabled, self.plantuml_auto_download)):
                    if diag.status != "OK":
                        _hint(f"[{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
            if result.returncode != 0:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                self._diagram_error("PlantUML", result.stderr, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
        else:
            _log_verbose(f"Reusing cached PlantUML diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _ensure_d2_bin(self):
        """d2実行ファイルを遅延解決する（初回のみ）。システムのdコマンドがあればそのまま
        再利用する（2章の最小限のダウンロード）。無い場合、plugins.d2_auto_download（既定true）
        ならD2公式CLIバイナリを自動取得し、falseならFail-fastでエラー終了する（#90）。"""
        if self._d2_bin is None:
            d2_bin = find_system_d2()
            if d2_bin:
                _log_info(f"Reusing system D2 for d2 rendering: {d2_bin}")
            elif self.d2_auto_download:
                d2_bin = ensure_d2_binary()
            else:
                _error("No local D2 found; required to render d2 diagrams. "
                      "Install D2 (https://d2lang.com), or set plugins.d2_auto_download: true "
                      "(downloads the D2 CLI binary, approx. 13MB), or set plugins.d2: false.")
                sys.exit(1)
            self._d2_bin = d2_bin
        return self._d2_bin

    def _render_d2(self, code, width=None, height=None):
        """```d2```ブロックをローカルのD2公式CLIバイナリでSVG化し、Typstのimage呼び出しに変換する。
        外部APIへの通信は行わない（仕様書10章・11章、#90）。`d2 - -`で標準入力から読み、標準出力へ
        SVGを書く（D2公式のstdin/stdout規約。ステータスメッセージは標準エラーへ出るため混ざらない）。"""
        svg_path = self._d2_svg_path(code)
        if svg_path is None:
            return f"```d2\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _d2_svg_path(self, code, line=None):
        """d2の図のSVG（キャッシュ）のパスを返す。無ければ、ローカルのD2で作る。
        plugins.d2: falseなら、何も作らずNoneを返す。line: 失敗時の診断に付ける行。"""
        if not self.d2_enabled:
            if not self._d2_disabled_warned:
                _log_info(f"plugins.d2 is disabled; leaving ```d2 fences as plain code (first seen in {self.current_file}).")
                self._d2_disabled_warned = True
            return None

        svg_path, _ = self._diagram_cache_path("d2", self._d2_version(), code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering d2 diagram via local D2 -> {os.path.basename(svg_path)}")
            d2_bin = self._ensure_d2_bin()
            try:
                result = subprocess.run(
                    [d2_bin, "-", "-"],
                    input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
            except OSError as e:
                self._error_here(f"Failed to run D2 for {self.current_file}:\n{e}")
                # 隔離環境（venv/pipx）外での実行が原因の可能性が高い（#113、ファイルが
                # 存在するように見えてもサブプロセスから見えない既知の問題）ため優先して案内する。
                for diag in (_check_isolated_env(), _check_d2(self.d2_enabled, self.d2_auto_download)):
                    if diag.status != "OK":
                        _hint(f"[{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
            if result.returncode != 0:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                self._diagram_error("d2", result.stderr, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
        else:
            _log_verbose(f"Reusing cached d2 diagram: {os.path.basename(svg_path)}")
        return svg_path

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
        
    def _count_table_cols(self, tokens, start_idx):
        cols = 0
        for i in range(start_idx, len(tokens)):
            if tokens[i].type in ['th_open', 'td_open']:
                cols += 1
            if tokens[i].type == 'tr_close':
                break
        return max(1, cols)

    # 単純な英数字+ハイフンの識別子（例: "red"）のみ、Typstの色定数名として安全に生コード注入できる
    # と判断する。それ以外（"#eeeeee"のようなhex形式や、記号を含む不正な値）はrgb()の文字列引数
    # として渡す（Typstのコンパイルエラーとして安全に失敗する。文字列リテラル内なのでコード注入の
    # 心配もない）。
    COLOR_IDENTIFIER_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9\-]*$')

    def _color_to_typst(self, value):
        """config.yamlやMarkdownの色文字列をTypstの色表現へ変換する（#45、#46）。
        Typstのrgb()は"red"のような色名文字列を受け付けないため（hex文字列のみ）、"#rrggbb"形式は
        rgb()に、"red"のような単純な識別子はTypstの色定数名としてそのまま渡す。"""
        value = str(value).strip()
        if self.COLOR_IDENTIFIER_RE.match(value):
            return value
        return f'rgb("{escape_string_literal(value)}")'

    # セル単位のborder属性（#89）が取れる値と、対応するTypstのstroke式。太さと色は、Typstの表の
    # 既定の枠線（1pt・黒）に揃える。実線（solid）を明示できるのは、隣のセルの破線と並べたときに
    # 「そのセルだけ実線」を表すため。
    CELL_BORDER_STROKES = {
        'solid': '1pt + black',
        'dashed': '(paint: black, thickness: 1pt, dash: "dashed")',
        'dotted': '(paint: black, thickness: 1pt, dash: "dotted")',
        'none': 'none',
    }

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

    def _table_header_fill_arg(self):
        """table_header.backgroundが指定されていれば、#table()のfill:引数（1行目のみ着色）を返す。
        未指定なら空文字列（従来どおり無装飾）。"""
        background = self.table_header_style.get('background')
        if not background:
            return ''
        return f',\n  fill: (col, row) => if row == 0 {{ {self._color_to_typst(background)} }} else {{ none }}'

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
