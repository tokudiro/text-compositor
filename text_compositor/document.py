"""文書全体のTypstコード（プリアンブル・改訂履歴・概要・用語集・テンプレート）の組み立て。"""
import os
import sys
import shutil
from datetime import datetime
from text_compositor.config import _resolve_project_image_path, resolve_template_path
from text_compositor.log import _error
from text_compositor.typst_literal import _typst_multiline_literal, _typst_str_or_none, escape_string_literal

def _page_set_fragment(paper, landscape, header, footer, paginate, background, logo):
    """paper/landscape/header/footer/paginate/background/logoをまとめた#set page(...)断片を
    組み立てる（#42、#17、#55、#54）。headerがNone（chapters[]/front-matterで明示的にnullを
    指定した場合のみ起こりうる。グローバルの既定値は常にtitleへフォールバック済みでNoneにならない）
    ならheader自体を非表示にする（logoも一緒に消える。ヘッダーごと消す指定のため妥当）。
    footerはrender-footer()側でNone/paginateの組み合わせを判定するため、常にrender-footer()を
    呼ぶ。backgroundも同様にrender-background()側でNone判定する。"""
    header_expr = ("none" if header is None
                    else f'render-header({_typst_str_or_none(header)}, {_typst_str_or_none(logo)})')
    footer_expr = f'render-footer({_typst_str_or_none(footer)}, {str(paginate).lower()})'
    background_expr = f'render-background({_typst_str_or_none(background)})'
    return (f'#set page(paper: "{paper}", flipped: {str(landscape).lower()}, '
            f'header: {header_expr}, footer: {footer_expr}, background: {background_expr})\n')

def _build_glossary_section(glossary_terms):
    """document.glossary: trueの場合、全チャプター処理後にTypstRenderer.glossary_terms
    （term -> [label_id, ...]）から巻末の用語索引ページを組み立てる（#47）。文字コード順
    （Pythonのsorted()）で並べ、同じ用語の全出現ページ番号を重複除去のうえ昇順で列挙する。
    定義文は持たない索引型（本の巻末索引と同じ形）。"""
    entries = []
    for term in sorted(glossary_terms.keys()):
        label_ids = glossary_terms[term]
        label_list = ", ".join(f'"{escape_string_literal(lbl)}"' for lbl in label_ids)
        safe_term = escape_string_literal(term)
        entries.append(f'  ("{safe_term}", ({label_list},)),')
    entries_block = "\n".join(entries)

    static_part = """
#context {
  for (term, label_ids) in __glossary_entries {
    let pages = ()
    for lbl in label_ids {
      let found = query(label(lbl))
      if found.len() > 0 {
        pages.push(found.first().location().page())
      }
    }
    pages = pages.sorted().dedup()
    let page-str = pages.map(str).join(", ")
    [#term #box(width: 1fr, repeat[.]) #page-str]
    linebreak()
  }
}
"""
    return (
        "\n#pagebreak(weak: true)\n"
        "= 用語索引\n\n"
        "#let __glossary_entries = (\n"
        f"{entries_block}\n"
        ")\n"
        + static_part
    )

# 同梱テンプレート・アダプタが共有する補助関数のファイル名（templates/配下、work_dirへも同名でコピー）。
COMMON_TEMPLATE_NAME = "_common.typ"

def _common_template_path(tool_dir):
    return os.path.join(tool_dir, "templates", COMMON_TEMPLATE_NAME)

def _prepare_template(config, tool_dir, project_dir, work_dir, typst_root):
    """template.pathを解決してwork_dir配下へコピーし、(コピー先の絶対パス, --root起点の
    ルート絶対パス文字列)を返す。8章のセキュリティ要件（tool_dirを--rootにしない）を満たす
    ため、テンプレートは元の置き場所に関わらずwork_dir（--rootの内側）へコピーしてから参照する。"""
    template_abs_path = resolve_template_path(config["template"]["path"], tool_dir, project_dir)
    if not os.path.exists(template_abs_path):
        _error(f"Template not found: {template_abs_path}")
        sys.exit(1)
    template_copy_path = os.path.join(work_dir, "_template" + os.path.splitext(template_abs_path)[1])
    shutil.copyfile(template_abs_path, template_copy_path)
    # 共通の補助関数（#63）。同梱テンプレートと、外部テンプレートを包むアダプタが、
    # 相対パス（`#import "_common.typ"`）で読み込めるよう、テンプレートの隣へ常にコピーする。
    # 読み込まないテンプレート（従来の独自テンプレート）には影響しない。
    shutil.copyfile(_common_template_path(tool_dir), os.path.join(work_dir, COMMON_TEMPLATE_NAME))

    # 生成コード(temp_build.typ)の実際の置き場所に依存させないよう、typst_root起点の
    # ルート絶対パスに変換する（.text-compositor/等サブディレクトリに置いても解決できる）。
    template_root_rel_path = "/" + os.path.relpath(template_copy_path, typst_root).replace(os.sep, '/')
    return template_copy_path, template_root_rel_path

REVISION_HISTORY_KEYS = ("version", "date", "description", "author")

def _resolve_revision_history(doc_config):
    """document.revision_history（#56）を検証し、[{version, date, description, author}, ...]
    （値はすべて文字列、省略されたキーは空文字）を返す。キー自体が無い、または空リストならNone
    （改版履歴ページを出さない）。YAMLの日付（date: 2026-08-14）は文字列化してそのまま使う。
    未知のキーは綴りミス（例: `discription`）が黙って無視されるのを避けるためエラーにする。"""
    raw = doc_config.get("revision_history")
    if raw is None:
        return None
    if not isinstance(raw, list):
        _error("document.revision_history must be a list of mappings "
              "(version / date / description / author).")
        sys.exit(1)
    entries = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            _error(f"document.revision_history[{i}] must be a mapping "
                  f"(version / date / description / author), got {item!r}.")
            sys.exit(1)
        unknown = [k for k in item if k not in REVISION_HISTORY_KEYS]
        if unknown:
            _error(f"document.revision_history[{i}]: unknown key(s) {unknown} "
                  f"(allowed: {', '.join(REVISION_HISTORY_KEYS)}).")
            sys.exit(1)
        entry = {k: ("" if item.get(k) is None else str(item[k])) for k in REVISION_HISTORY_KEYS}
        if not any(v.strip() for v in entry.values()):
            _error(f"document.revision_history[{i}] is empty.")
            sys.exit(1)
        entries.append(entry)
    return entries or None

def _resolve_abstract(doc_config):
    """document.abstract（#64）を検証し、文字列（前後の空白を除く）を返す。未指定・空文字ならNone
    （概要を出さない）。文字列以外（リスト等）は、意図しない値が黙って文字列化されるのを避けるためエラーにする。"""
    raw = doc_config.get("abstract")
    if raw is None:
        return None
    if not isinstance(raw, str):
        _error(f"document.abstract must be a string (got {type(raw).__name__}).")
        sys.exit(1)
    return raw.strip() or None

def _abstract_typst_arg(abstract):
    """conf()へ渡す`abstract: "..."`引数行を返す。未指定なら引数自体を渡さない
    （tocやrevision_historyと同じく、この引数を持たない既存の独自テンプレートとの互換を保つため）。"""
    if abstract is None:
        return ''
    return f'  abstract: {_typst_multiline_literal(abstract)},\n'

def _revision_history_typst_arg(entries):
    """conf()へ渡す`revision_history: (...)`引数行を返す。entriesがNoneなら引数自体を渡さない
    （tocなどと同じく、この引数を持たない既存の独自テンプレートとの互換を保つため）。
    改行は文字列リテラル中の\\nとして渡し、テンプレート側がlinebreak()へ変換する。"""
    if entries is None:
        return ''

    rows = ", ".join(
        "(" + ", ".join(f"{k}: {_typst_multiline_literal(e[k])}" for k in REVISION_HISTORY_KEYS) + ")" for e in entries)
    # 要素が1つのときも配列になるよう、末尾のカンマを必ず付ける
    return f'  revision_history: ({rows},),\n'

def _build_document_preamble(config, template_root_rel_path, graphviz_enabled, project_dir, typst_root):
    """document:設定からtypst_codeの冒頭（テンプレートのimportとconf()呼び出し）を組み立てる。
    戻り値は (preamble文字列, global_landscape, global_paper, cover_mode, global_table_header,
    global_header, global_footer, global_paginate, global_background, global_logo)。"""
    doc_config = config.get("document", {})
    global_landscape = str(doc_config.get('landscape', False)).lower() == 'true'
    global_paper = doc_config.get('paper_size', 'a4')
    # 通常のMarkdownテーブルのヘッダ行スタイル（#45）。未指定なら従来どおり無装飾。
    global_table_header = doc_config.get('table_header') or {}
    # 本文ページのヘッダー・フッター・ページ番号表示（#42）。header/footerは未指定ならNone
    # （テンプレート側でheaderはtitleへフォールバックする。footerはページ番号のみの従来動作）。
    global_header = doc_config.get('header')
    global_footer = doc_config.get('footer')
    global_paginate = str(doc_config.get('paginate', True)).lower() == 'true'
    # 本文ページの背景画像（#55）。header/footerと同じ「常にconf()へ渡す必須引数」パターンで、
    # chapters[]単位の上書きにも対応する（_page_set_fragment）。
    global_background = _resolve_project_image_path(doc_config.get('background'), project_dir, typst_root, "Background")
    # ヘッダーのロゴ画像（#54）。backgroundと全く同じパターン。
    global_logo = _resolve_project_image_path(doc_config.get('logo'), project_dir, typst_root, "Logo")

    # 表紙の扱い: template=テンプレートの表紙のみ / replace=テンプレートの表紙でMarkdown先頭の
    # タイトルスライドを置き換える / markdown=Markdown側のみ / none=表紙なし。既定はnone（安定版前の
    # ため、表紙の要否を明示させる方針。#58の目次デフォルト変更と合わせた判断）
    cover_mode = doc_config.get('cover', 'none')
    if isinstance(cover_mode, bool):
        cover_mode = 'template' if cover_mode else 'none'
    cover_mode = str(cover_mode).lower()
    if cover_mode not in ('template', 'replace', 'markdown', 'none'):
        _error(f"Invalid document.cover: {cover_mode!r} (expected template / replace / markdown / none)")
        sys.exit(1)
    # template/replaceのときだけ引数を渡さず、cover引数を持たない既存テンプレートとの互換を保つ
    cover_arg = '' if cover_mode in ('template', 'replace') else '  cover: false,\n'

    # 表紙のページ番号表示。未指定ならテンプレート自身の既定値に任せ、引数自体を渡さない
    cover_page_number = doc_config.get('cover_page_number')
    cover_page_number_arg = (
        f'  cover_page_number: {str(bool(cover_page_number)).lower()},\n'
        if cover_page_number is not None else ''
    )

    # 目次の表示有無（#58）。未指定ならテンプレート自身の既定値（false）に任せ、引数自体を渡さない
    toc = doc_config.get('toc')
    toc_arg = f'  toc: {str(bool(toc)).lower()},\n' if toc is not None else ''

    # 改版履歴ページ（#56）。表紙と目次の間に独立したページとして挿入する。未指定なら引数自体を渡さない。
    revision_history_arg = _revision_history_typst_arg(_resolve_revision_history(doc_config))
    # 概要（#64）。論文形式のテンプレート（paper）がタイトルブロックの下に出す。未指定なら引数自体を渡さない。
    abstract_arg = _abstract_typst_arg(_resolve_abstract(doc_config))

    date_str = doc_config.get("date", "")
    if date_str == "auto":
        date_str = datetime.now().strftime("%Y-%m-%d")

    safe_title = escape_string_literal(doc_config.get('title', 'Untitled'))
    safe_subtitle = escape_string_literal(doc_config.get('subtitle', ''))
    safe_author = escape_string_literal(doc_config.get('author', ''))
    safe_date = escape_string_literal(date_str)

    preamble = f"""
#import "{template_root_rel_path.replace(os.sep, '/')}": conf, fit-image, render-graph, render-header, render-footer, render-background, callout
#show: doc => conf(
  title: "{safe_title}",
  subtitle: "{safe_subtitle}",
  author: "{safe_author}",
  date: "{safe_date}",
  paper_size: "{global_paper}",
  landscape: {str(global_landscape).lower()},
{cover_arg}{cover_page_number_arg}{toc_arg}{revision_history_arg}{abstract_arg}  graphviz: {str(graphviz_enabled).lower()},
  header: {_typst_str_or_none(global_header)},
  footer: {_typst_str_or_none(global_footer)},
  paginate: {str(global_paginate).lower()},
  background: {_typst_str_or_none(global_background)},
  logo: {_typst_str_or_none(global_logo)},
  doc,
)

"""
    return (preamble, global_landscape, global_paper, cover_mode, global_table_header,
            global_header, global_footer, global_paginate, global_background, global_logo)
