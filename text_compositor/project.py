"""1つのプロジェクト（config）のビルドの本体。configの読み込みから、Typstコードの生成、PDFの出力まで。"""
import os
import time
from text_compositor.changes import _is_up_to_date
from text_compositor.chapters import ChapterDefaults, _expand_chapters, _parse_chapter_entry, _parse_csv_header, _render_aggregate_chapter, _render_markdown_chapter, _render_section_heading
from text_compositor.compiler import _compile_and_cleanup
from text_compositor.config import _load_project_config, _resolve_line_mapping, _resolve_project_dirs, _resolve_variables, find_config_in_cwd
from text_compositor.document import _build_document_preamble, _build_glossary_section, _page_set_fragment, _prepare_template
from text_compositor.log import _log_info, _log_verbose
from text_compositor.renderer import TypstRenderer

def _build_one(tool_dir, repo_root, font_dir, config_path, keep_temp=False, if_changed=False):
    # 汎用ツールとして、呼び出し元プロジェクトが持つ設定ファイルを指定できるようにする。
    # inputs.dir/output.dir などプロジェクト固有の相対パスは、このconfigファイルの
    # 置き場所(project_dir)を基準に解決する。templates/等ツール自身のリソースはtool_dir基準のまま。
    project_dir, config, chapters = _load_project_config(config_path)

    # --if-changed（#151）。副作用（作業ディレクトリ作成・図表描画）より前に判定し、スキップ時は何も書かない。
    if if_changed:
        resolved_config_path = os.path.abspath(config_path) if config_path else find_config_in_cwd()
        up_to_date, out_pdf = _is_up_to_date(tool_dir, resolved_config_path, project_dir, config)
        if up_to_date:
            _log_info(f"Skipped (up to date): {out_pdf}")
            return

    _build_project(tool_dir, repo_root, font_dir, project_dir, config, chapters, keep_temp=keep_temp)

def _build_project(tool_dir, repo_root, font_dir, project_dir, config, chapters, keep_temp=False, *,
                   mermaid_browser=None, compiler_cache=None, out_pdf=None, timings=None):
    """読み込み済みのconfig・chaptersから、1つのPDFをビルドする（CLIの`_build_one`と、Python API
    （api.py、#167）が共有する本体）。

    mermaid_browser / compiler_cache / out_pdfは、常駐するPython API用の指定で、CLIでは渡さない。
      mermaid_browser: 使い回すMermaidBrowser。渡すと、このビルドでは片付けない（渡した側が片付ける）。
      compiler_cache: 使い回すtypst.Compilerを入れる辞書。渡すと、コンパイラを使い回し、PDFを原子的に書く。
      out_pdf: 出力先PDFのパス。渡すと、config.outputは使わず、出力先ディレクトリも作らない。
      timings: 渡した辞書へ、所要時間（ミリ秒）を入れる。render（Markdown→Typstコード。図表の描画を含む）と、
        compile（Typstコンパイル・PDFの書き出し・中間ファイルの削除）。
    """
    started = time.perf_counter()
    # plugins: Graphviz/PlantUML/Mermaid/D2の有効・無効切り替え（6章、#21、#90）。未指定時は
    # 既存動作を維持する既定値（graphviz/mermaid/plantuml/d2はいずれも常時有効）。
    # *_auto_download は、システムに必要なツール（ブラウザ/Java/D2）が無い場合の振る舞いを制御する
    # 別軸のフラグ（#22の設計議論）。既定値が非対称なのは、ダウンロードされる実体のサイズが
    # 一桁違うため（Playwright自身のChromium: 約700MB対Eclipse Temurin JRE: 約49.7MB対D2 CLI: 約13MB）。
    plugins_config = config.get("plugins") or {}
    graphviz_enabled = bool(plugins_config.get("graphviz", True))
    pikchr_enabled = bool(plugins_config.get("pikchr", True))   # #213
    cetz_enabled = bool(plugins_config.get("cetz", True))   # #236
    fletcher_enabled = bool(plugins_config.get("fletcher", True))
    mermaid_enabled = bool(plugins_config.get("mermaid", True))
    mermaid_auto_download = bool(plugins_config.get("mermaid_auto_download", False))
    plantuml_enabled = bool(plugins_config.get("plantuml", True))
    plantuml_auto_download = bool(plugins_config.get("plantuml_auto_download", True))
    d2_enabled = bool(plugins_config.get("d2", True))
    d2_auto_download = bool(plugins_config.get("d2_auto_download", True))
    # document.glossary: false（既定。#47）。trueなら[[用語]]を検出し、巻末に索引ページを生成する。
    glossary_enabled = bool(config.get("document", {}).get("glossary", False))
    # document.marp_compat: false（既定、#92）。trueなら実際のMarpitに合わせ、hr（---/***/___）を
    # 一律改ページとして描画する。
    marp_compat = bool(config.get("document", {}).get("marp_compat", False))
    line_mapping = _resolve_line_mapping(config)
    # variables: {{KEY}}プレースホルダの置換表（#72）。章の処理より前に解決し、環境変数の未設定
    # などの誤りを、長い描画処理を始める前にFail-fastで報告する。
    variables = _resolve_variables(config)
    # document.csv_header: true（既定、#220）。.csvの章の1行目を、ヘッダー行にするか。
    csv_header = _parse_csv_header(config.get("document", {}).get("csv_header", True), "document")

    outputs_dir, inputs_dir, work_dir, typst_root = _resolve_project_dirs(
        project_dir, config, create_outputs=out_pdf is None)
    template_copy_path, template_root_rel_path = _prepare_template(config, tool_dir, project_dir, work_dir, typst_root)

    (typst_code, global_landscape, global_paper, cover_mode, global_table_header,
     global_header, global_footer, global_paginate, global_background, global_logo) = _build_document_preamble(
        config, template_root_rel_path, graphviz_enabled, project_dir, typst_root)

    # headerの実効グローバル既定値。document.headerが未指定ならテンプレート側と同じくtitleへ
    # フォールバックする（#42）。章ごとの解決(chapters[]/front-matter)は、この実効値を起点にする。
    doc_title = config.get("document", {}).get("title", "Untitled")
    effective_global_header = global_header if global_header is not None else doc_title

    renderer = TypstRenderer(project_dir, typst_root=typst_root,
                              mermaid_enabled=mermaid_enabled, mermaid_auto_download=mermaid_auto_download,
                              plantuml_enabled=plantuml_enabled, plantuml_auto_download=plantuml_auto_download,
                              d2_enabled=d2_enabled, d2_auto_download=d2_auto_download, pikchr_enabled=pikchr_enabled,
                              cetz_enabled=cetz_enabled, fletcher_enabled=fletcher_enabled,
                              glossary_enabled=glossary_enabled, line_mapping=line_mapping,
                              marp_compat=marp_compat, variables=variables,
                              mermaid_browser=mermaid_browser, csv_header=csv_header)
    current_landscape, current_paper = global_landscape, global_paper
    current_header, current_footer, current_paginate = effective_global_header, global_footer, global_paginate
    current_background = global_background
    current_logo = global_logo
    is_first_chapter = True

    # chaptersをsectionを含めたフラットな描画順へ展開する（#68）。設定ミスは描画前に報告される。
    root_defaults = ChapterDefaults(
        landscape=global_landscape, paper=global_paper, header=effective_global_header, footer=global_footer,
        paginate=global_paginate, background=global_background, logo=global_logo,
        table_header=global_table_header, heading_offset=0)
    entries = _expand_chapters(chapters, root_defaults, project_dir, typst_root)

    try:
        for kind, ch, d in entries:
            if kind == "section":
                _log_verbose(f"Processing section: {ch}")
                (fragment, current_landscape, current_paper,
                 current_header, current_footer, current_paginate,
                 current_background, current_logo) = _render_section_heading(
                    ch, renderer, d, current_landscape, current_paper, current_header, current_footer,
                    current_paginate, current_background, current_logo)
                typst_code += fragment
                # sectionの見出しが先頭に来る場合、cover: replace/noneで落とす「先頭のタイトル」は
                # 存在しない。配下の最初の章のタイトルを落とさず、sectionの見出しの下に残す。
                is_first_chapter = False
                continue
            ch_file, ch_dict, ch_type = _parse_chapter_entry(ch)
            _log_verbose(f"Processing chapter ({ch_type}): {ch_file}")
            # 章の既定値（d）は、section配下ならsectionの指定で上書き済みの値。最上位の章では
            # 従来どおりdocument.*の実効値そのもの。
            if ch_type == "aggregate":
                (fragment, current_landscape, current_paper,
                 current_header, current_footer, current_paginate,
                 current_background, current_logo) = _render_aggregate_chapter(
                    ch_dict, ch_file, inputs_dir, renderer, current_landscape, current_paper,
                    d.landscape, d.paper, current_header, current_footer, current_paginate,
                    d.header, d.footer, d.paginate, current_background, d.background,
                    current_logo, d.logo, heading_offset=d.heading_offset)
            else:
                (fragment, current_landscape, current_paper,
                 current_header, current_footer, current_paginate,
                 current_background, current_logo) = _render_markdown_chapter(
                    ch_dict, ch_file, inputs_dir, renderer, current_landscape, current_paper,
                    d.landscape, d.paper, is_first_chapter, cover_mode, d.table_header,
                    current_header, current_footer, current_paginate,
                    d.header, d.footer, d.paginate, current_background, d.background,
                    current_logo, d.logo, heading_offset=d.heading_offset)
            typst_code += fragment
            is_first_chapter = False
    finally:
        # mermaidレンダリング用に起動したヘッドレスブラウザを、エラー終了時も含め必ず片付ける（#35）。
        renderer.close()

    if (current_landscape, current_paper, current_header, current_footer, current_paginate, current_background, current_logo) != (
            global_landscape, global_paper, effective_global_header, global_footer, global_paginate, global_background, global_logo):
        typst_code += _page_set_fragment(
            global_paper, global_landscape, effective_global_header, global_footer, global_paginate, global_background, global_logo)

    # 巻末の用語索引（#47）。全チャプター処理後、実際に[[用語]]が使われていた場合のみ追加する。
    if glossary_enabled and renderer.glossary_terms:
        typst_code += _build_glossary_section(renderer.glossary_terms)

    compile_started = time.perf_counter()
    if timings is not None:
        timings["render"] = (compile_started - started) * 1000.0
    _compile_and_cleanup(typst_code, work_dir, outputs_dir, config, typst_root, font_dir, template_copy_path, repo_root,
                         keep_temp=keep_temp, compiler_cache=compiler_cache, out_pdf=out_pdf)
    if timings is not None:
        timings["compile"] = (time.perf_counter() - compile_started) * 1000.0
