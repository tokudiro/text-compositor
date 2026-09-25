"""`chapters`の展開と、章ごと（Markdown・集約・見出し）のTypstコード生成。"""
import os
import sys
import json
from collections import namedtuple
from text_compositor.config import _resolve_project_image_path, yaml
from text_compositor.document import _page_set_fragment
from text_compositor.log import _error, _warn
from text_compositor.typst_literal import insert_soft_break_hints

def extract_md_string(data, key):
    """YAMLからテキストを抽出。リスト形式の場合は改行で結合して単一文字列にする"""
    val = data.get(key, "")
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)

def _parse_chapter_entry(ch):
    """chaptersの1エントリを解析し、(ファイル/ディレクトリ名, 章固有設定のdict, 種別)を返す。
    種別は"file"（Markdown等の通常章）または"aggregate"（YAML/JSON集約）。"""
    if isinstance(ch, str):
        return ch, {}, "file"
    if not isinstance(ch, dict):
        _error(f"Invalid chapter entry (must be a string or a mapping): {ch!r}")
        sys.exit(1)
    if "aggregate" in ch:
        ch_file = ch["aggregate"]
        ch_type = "aggregate"
    else:
        ch_file = ch.get("file")
        ch_type = "file"
    if not ch_file:
        _error(f"Invalid chapter entry (no 'file' or 'aggregate' key): {ch!r}")
        sys.exit(1)
    return ch_file, ch, ch_type

# 章に効くページ設定・スタイルの「既定値」一式（#68）。最上位ではdocument.*の実効値、section配下では
# sectionの指定でそれを上書きしたもの。各章の解決は「章の指定 ＞ front-matter ＞ この既定値」の順。
ChapterDefaults = namedtuple("ChapterDefaults", [
    "landscape", "paper", "header", "footer", "paginate", "background", "logo", "table_header", "heading_offset"])

def _parse_csv_header(value, where):
    """.csvの1行目をヘッダー行にするか（csv_header、#220）を検証して返す。true/falseのみ。"""
    if not isinstance(value, bool):
        _error(f"{where}: csv_header must be true or false (got {value!r}).")
        sys.exit(1)
    return value

def _parse_heading_offset(value, where):
    """heading_offset（見出しレベルをずらす段数）を検証して返す。0以上の整数のみ。上限5は、
    MarkdownのH1〜H6を最大でH11相当まで下げても意味を成さないため、明らかな誤記を弾く目的。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        _error(f"{where}: heading_offset must be an integer from 0 to 5 (got {value!r}).")
        sys.exit(1)
    return value

def _expand_chapters(chapters, root_defaults, project_dir, typst_root):
    """chaptersを、描画順のフラットな[(種別, エントリ, ChapterDefaults), ...]へ展開する（#68）。
    種別は"section"（章見出しの出力。エントリは見出し文字列）または"chapter"（通常章・aggregate）。
    sectionは`- section: 見出し`と入れ子の`chapters:`で書き、配下の章はsectionの指定した
    header/footer/paginate/landscape/paper_size/background/logo/table_headerを既定値として
    継承する（各章で上書き可）。見出しレベルはheading_offset（既定1: H1→H2）だけ下がる。
    sectionの入れ子は2階層の目次に限る方針のため対応しない。展開時に検証するので、描画（重い処理）
    を始める前にFail-fastで設定ミスを報告できる。"""
    entries = []
    for ch in chapters:
        if isinstance(ch, dict) and "section" in ch:
            title = ch["section"]
            if not isinstance(title, str) or not title.strip():
                _error(f"Invalid section (the heading must be a non-empty string): {ch!r}")
                sys.exit(1)
            if "file" in ch or "aggregate" in ch:
                _error(f"section {title!r}: 'section' cannot be combined with 'file'/'aggregate'; "
                      f"list the files under 'chapters:'.")
                sys.exit(1)
            children = ch.get("chapters")
            if not isinstance(children, list) or not children:
                _error(f"section {title!r}: 'chapters' must be a non-empty list.")
                sys.exit(1)
            offset = _parse_heading_offset(ch.get("heading_offset", 1), f"section {title!r}")
            table_header = dict(root_defaults.table_header)
            table_header.update(ch.get("table_header") or {})
            defaults = ChapterDefaults(
                landscape=str(ch.get("landscape", root_defaults.landscape)).lower() == 'true',
                paper=ch.get("paper_size", root_defaults.paper),
                header=ch.get("header", root_defaults.header),
                footer=ch.get("footer", root_defaults.footer),
                paginate=str(ch.get("paginate", root_defaults.paginate)).lower() == 'true',
                background=(_resolve_project_image_path(ch["background"], project_dir, typst_root, "Background")
                            if "background" in ch else root_defaults.background),
                logo=(_resolve_project_image_path(ch["logo"], project_dir, typst_root, "Logo")
                      if "logo" in ch else root_defaults.logo),
                table_header=table_header,
                heading_offset=offset)
            entries.append(("section", title, defaults))
            for child in children:
                if isinstance(child, dict) and "section" in child:
                    _error(f"section {title!r}: nested sections are not supported "
                          f"(found section {child['section']!r} inside it).")
                    sys.exit(1)
                _check_chapter_heading_offset(child)
                entries.append(("chapter", child, defaults))
        else:
            _check_chapter_heading_offset(ch)
            entries.append(("chapter", ch, root_defaults))
    return entries

def _check_chapter_heading_offset(ch):
    if isinstance(ch, dict) and "heading_offset" in ch:
        _parse_heading_offset(ch["heading_offset"], f"chapter {ch.get('file') or ch.get('aggregate')!r}")

def _render_section_heading(title, renderer, defaults, current_landscape, current_paper,
                             current_header, current_footer, current_paginate, current_background, current_logo):
    """sectionの章見出し（H1）を出力する（#68）。見出しの前に、sectionのページ設定へ切り替える
    （最初の章より前にヘッダー・フッターが変わるため）。戻り値は_render_aggregate_chapterと同じ形式。"""
    typst_code = ""
    if (defaults.landscape, defaults.paper, defaults.header, defaults.footer, defaults.paginate,
            defaults.background, defaults.logo) != (
            current_landscape, current_paper, current_header, current_footer, current_paginate,
            current_background, current_logo):
        typst_code += _page_set_fragment(defaults.paper, defaults.landscape, defaults.header, defaults.footer,
                                          defaults.paginate, defaults.background, defaults.logo)
        current_landscape, current_paper = defaults.landscape, defaults.paper
        current_header, current_footer, current_paginate = defaults.header, defaults.footer, defaults.paginate
        current_background, current_logo = defaults.background, defaults.logo
    typst_code += f'= {renderer.escape_typst(title)}\n\n'
    return (typst_code, current_landscape, current_paper, current_header, current_footer,
            current_paginate, current_background, current_logo)

def _render_aggregate_chapter(ch_dict, ch_file, inputs_dir, renderer, current_landscape, current_paper,
                               global_landscape, global_paper, current_header, current_footer, current_paginate,
                               global_header, global_footer, global_paginate, current_background, global_background,
                               current_logo, global_logo, heading_offset=0):
    """aggregate: チャプター（YAML/JSONファイル群のテーブル集約）をTypstへ変換する。
    aggregateはYAML/JSONのテストケース集約であり、front-matter（Markdown固有の概念）は関係しない。
    戻り値は (typst断片, 更新後のcurrent_landscape, 更新後のcurrent_paper, 更新後のcurrent_header,
    更新後のcurrent_footer, 更新後のcurrent_paginate, 更新後のcurrent_background, 更新後のcurrent_logo)。"""
    typst_code = ""
    ch_landscape = str(ch_dict.get("landscape", global_landscape)).lower() == 'true'
    ch_paper = ch_dict.get("paper_size", global_paper)
    ch_header = ch_dict.get("header", global_header)
    ch_footer = ch_dict.get("footer", global_footer)
    ch_paginate = str(ch_dict.get("paginate", global_paginate)).lower() == 'true'
    ch_background = (_resolve_project_image_path(ch_dict["background"], renderer.base_dir, renderer.typst_root, "Background")
                      if "background" in ch_dict else global_background)
    ch_logo = (_resolve_project_image_path(ch_dict["logo"], renderer.base_dir, renderer.typst_root, "Logo")
               if "logo" in ch_dict else global_logo)
    if (ch_landscape, ch_paper, ch_header, ch_footer, ch_paginate, ch_background, ch_logo) != (
            current_landscape, current_paper, current_header, current_footer, current_paginate, current_background, current_logo):
        typst_code += _page_set_fragment(ch_paper, ch_landscape, ch_header, ch_footer, ch_paginate, ch_background, ch_logo)
        current_landscape, current_paper = ch_landscape, ch_paper
        current_header, current_footer, current_paginate = ch_header, ch_footer, ch_paginate
        current_background, current_logo = ch_background, ch_logo

    agg_path = os.path.join(inputs_dir, ch_file)
    agg_level = 1 + ch_dict.get("heading_offset", heading_offset)
    typst_code += f'{"=" * agg_level} {renderer.escape_typst(ch_dict.get("title", "Test Cases"))}\n\n'

    if os.path.exists(agg_path) and os.path.isdir(agg_path):
        # 【修正】YAMLだけでなくJSONファイルも読み込み対象に含める
        tc_files = sorted([f for f in os.listdir(agg_path) if f.endswith(('.yaml', '.yml', '.json'))])

        typst_code += '#table(\n  columns: (auto, 1fr, auto, 2fr, 2fr),\n'
        typst_code += '  align: (center, left, center, left, left),\n'
        typst_code += '  stroke: 0.5pt + luma(150),\n'
        typst_code += '  fill: (col, row) => if row == 0 { luma(240) } else { none },\n'
        typst_code += '  [*ID*], [*Title*], [*Priority*], [*Steps*], [*Expected*],\n'

        for tc_file in tc_files:
            tc_path = os.path.join(agg_path, tc_file)
            with open(tc_path, "r", encoding="utf-8") as f:
                try:
                    if tc_file.endswith('.json'):
                        tc_data = json.load(f) or {}
                    else:
                        tc_data = yaml.safe_load(f) or {}
                except Exception as e:
                    _warn(f"Failed to parse {tc_file}: {e}")
                    continue

            tc_id = renderer.escape_typst(str(tc_data.get("id", "")))
            # Titleにテストパス等の長い識別子（区切りがスペースでない）が入っても、
            # 表セル内で折り返せずはみ出さないようソフト改行点を挿入する（#269）。
            tc_title = renderer.escape_typst(insert_soft_break_hints(str(tc_data.get("title", ""))))
            tc_priority = renderer.escape_typst(str(tc_data.get("priority", "")))

            # 【修正】YAMLでリスト形式で書かれていた場合も結合して安全に処理する
            steps_md = extract_md_string(tc_data, "steps")
            expected_md = extract_md_string(tc_data, "expected")
            steps_typst = renderer.render(steps_md, filepath=tc_path).strip()
            expected_typst = renderer.render(expected_md, filepath=tc_path).strip()

            typst_code += f'  [{tc_id}], [{tc_title}], [{tc_priority}], [{steps_typst}], [{expected_typst}],\n'

        typst_code += ')\n\n#pagebreak(weak: true)\n'
    else:
        # 仕様9章: 入力欠損は黙って飛ばさず即エラー (Fail-fast)
        _error(f"Aggregate directory not found: {agg_path}")
        sys.exit(1)

    return typst_code, current_landscape, current_paper, current_header, current_footer, current_paginate, current_background, current_logo

def _render_markdown_chapter(ch_dict, ch_file, inputs_dir, renderer, current_landscape, current_paper,
                              global_landscape, global_paper, is_first_chapter, cover_mode, global_table_header,
                              current_header, current_footer, current_paginate,
                              global_header, global_footer, global_paginate, current_background, global_background,
                              current_logo, global_logo, heading_offset=0):
    """通常のチャプター（Markdown/YAML/JSON/プレーンテキスト等、#15の拡張子ディスパッチ対象）を
    Typstへ変換する。戻り値は (typst断片, 更新後のcurrent_landscape, 更新後のcurrent_paper,
    更新後のcurrent_header, 更新後のcurrent_footer, 更新後のcurrent_paginate, 更新後のcurrent_background,
    更新後のcurrent_logo)。"""
    md_path = os.path.join(inputs_dir, ch_file)
    if not os.path.exists(md_path):
        _error(f"Chapter file not found: {md_path}")
        sys.exit(1)

    # テーブルヘッダのスタイル（#45）。chapters[].table_headerはdocument.table_headerに対する
    # キー単位の上書き（chapters[].landscape/paper_sizeと同じ優先順位）。前後関係上、
    # front-matterはrender_chapter()実行後にしかわからないため、front-matterでの上書きは
    # サポートしない（#41以降、front-matterはlandscape/paper_size/font_sizeのみ反映する方針）。
    ch_table_header = dict(global_table_header)
    ch_table_header.update(ch_dict.get("table_header") or {})
    renderer.table_header_style = ch_table_header
    # 見出しのオフセット（#68）。章の明示指定 ＞ 所属sectionの値（引数）の順。
    renderer.heading_offset = ch_dict.get("heading_offset", heading_offset)
    # .csvの1行目をヘッダー行にするか（#220）。章の明示指定 ＞ document.csv_header（既定true）。
    renderer.csv_header = (_parse_csv_header(ch_dict["csv_header"], f"chapter {ch_file!r}")
                           if "csv_header" in ch_dict else renderer.csv_header_default)

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    chapter_typst = renderer.render_chapter(
        md_text, filepath=md_path,
        drop_leading_title=is_first_chapter and cover_mode in ('replace', 'none'))
    front_matter = renderer.front_matter

    # front-matterのpaper_size/landscapeは、config.yamlのチャプター個別設定より弱い
    # 優先順位で適用する（7章、#17）。config.yaml側に明示指定が無い場合のみ使う。
    # front-matterはファイルを読んで初めてわかるため、#set pageの要否判定もここで行う
    # （aggregateには front-matter の概念が無く、判定をchapters読み込み前に済ませられる）。
    ch_landscape = str(ch_dict.get("landscape", front_matter.get("landscape", global_landscape))).lower() == 'true'
    ch_paper = ch_dict.get("paper_size", front_matter.get("paper_size", global_paper))
    # header/footer/paginateも同じ優先順位（chapters[]の明示指定＞front-matter＞グローバル）で
    # 解決する（#42）。state()は使わず、landscape/paper_sizeと同じ「変化した時だけ#set pageを
    # 出し直す」パターンで、章の並べ替えに対して安全にする。
    ch_header = ch_dict.get("header", front_matter.get("header", global_header))
    ch_footer = ch_dict.get("footer", front_matter.get("footer", global_footer))
    ch_paginate = str(ch_dict.get("paginate", front_matter.get("paginate", global_paginate))).lower() == 'true'
    # 背景画像（#55）・ロゴ（#54）。パス値のためfront-matter経由の上書きはサポートしない
    # （table_headerと同じ判断）。
    ch_background = (_resolve_project_image_path(ch_dict["background"], renderer.base_dir, renderer.typst_root, "Background")
                      if "background" in ch_dict else global_background)
    ch_logo = (_resolve_project_image_path(ch_dict["logo"], renderer.base_dir, renderer.typst_root, "Logo")
               if "logo" in ch_dict else global_logo)
    typst_code = ""
    if (ch_landscape, ch_paper, ch_header, ch_footer, ch_paginate, ch_background, ch_logo) != (
            current_landscape, current_paper, current_header, current_footer, current_paginate, current_background, current_logo):
        typst_code += _page_set_fragment(ch_paper, ch_landscape, ch_header, ch_footer, ch_paginate, ch_background, ch_logo)
        current_landscape, current_paper = ch_landscape, ch_paper
        current_header, current_footer, current_paginate = ch_header, ch_footer, ch_paginate
        current_background, current_logo = ch_background, ch_logo

    font_size = front_matter.get('font_size')
    if font_size:
        # スコープを#[...]で閉じ、このチャプターだけにフォントサイズ指定を適用する
        typst_code += f"#[\n#set text(size: {font_size})\n{chapter_typst}\n]\n"
    else:
        typst_code += chapter_typst
    # front-matterのtitle/subtitle/author/dateは認識はするが、何も反映しない（#41）。
    # 文書全体の表紙（title/subtitle/author/date）は常にconfig.yaml側のみが正。
    typst_code += "\n#pagebreak(weak: true)\n"

    return typst_code, current_landscape, current_paper, current_header, current_footer, current_paginate, current_background, current_logo
