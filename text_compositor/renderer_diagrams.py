"""図のフェンス（Mermaid・PlantUML・D2・Graphviz・Pikchr・CeTZ・Fletcher・svg）の描画と、図のSVGのキャッシュ。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import os
import re
import sys
import subprocess
import hashlib
from text_compositor import cetz_render, graphviz_render, host_renderers, pikchr_render
from text_compositor.deps import D2_RELEASE, MERMAID_JS_SHA256, PLANTUML_JAR_SHA256, _system_d2_version, ensure_d2_binary, ensure_mermaid_js, ensure_plantuml_jar, ensure_temurin_jre, find_system_d2, find_system_java
from text_compositor.env_check import _check_d2, _check_isolated_env, _check_plantuml
from text_compositor.log import _error, _hint, _log_info, _log_verbose
from text_compositor.typst_literal import _typst_multiline_literal, escape_string_literal

def _diagram_cache_key(kind, tool_version, code):
    """図のキャッシュキー（#26）。入力テキストだけでなく、種別とレンダラのバージョンも
    ハッシュに含める。レンダラを更新しても同じ入力の古いSVGが使い回される事故を防ぐため。
    各要素の境界に\\0を挟み、「要素の切れ目が違うだけで連結結果が同じ」衝突を避ける。"""
    h = hashlib.sha256()
    for part in (kind, tool_version, code):
        h.update(part.encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()[:16]


class DiagramMixin:
    """図のフェンス（Mermaid・PlantUML・D2・Graphviz・Pikchr・CeTZ・Fletcher・svg）の描画と、図のSVGのキャッシュ。"""

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

    def _render_diagram_fence(self, lang, code, width=None, height=None):
        """```mermaid/```plantuml/```d2/```dot/```graphviz/```pikchr/```cetz/```fletcher/```svgフェンスの内容をTypstコードへ
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
        elif lang == 'pikchr':
            return self._render_pikchr(code, width, height)
        elif lang in cetz_render.KINDS:
            return self._render_figure(lang, code, width, height)
        return self._render_graphviz(lang, code, width, height)

    def _render_diagram_or_image_match(self, m):
        """DIAGRAM_OR_IMAGE_REの1マッチをTypstコードへ変換する。フェンスは_render_diagram_fenceへ、
        単独行のMarkdown画像は通常の画像処理（alt|width=/height=構文込み）をそのまま再利用するため
        _render_markdown_segmentに委譲する（#77）。"""
        if m.group('lang'):
            width, height = self._parse_size_attrs(m.group('attrs'))
            return self._render_diagram_fence(m.group('lang'), m.group('code'), width, height)
        return self._render_markdown_segment(m.group('image'), False).strip()

    def _render_pikchr(self, code, width=None, height=None):
        """```pikchrフェンスの内容を、Typstのkip（PikchrのWASMプラグイン）で描くコードへ変換する（#213）。
        自動縮小と、width/heightの扱いは、Graphvizの`render-graph()`と同じ。plugins.pikchr: falseなら、素のコード表示にする。
        テンプレートの補助関数にしない（`render-graph`と違い、生成コードが、kipを直接importする）: 生成コードが読み込むテンプレートの
        公開名を増やすと、既存のカスタムテンプレートが、`unknown variable`で壊れるため。
        kip()関数は、構文エラーのPikchrで、原因の分からない`failed to parse SVG`になる。そこで、kipが公開するプラグインを直接呼び、
        SVGでない返り値（Pikchr自身のエラー: 行・位置・原因）を、panicでそのまま出す（HTML出力のpikchr_render.pyと同じ処理）。"""
        if not self.pikchr_enabled:
            return self._render_raw_text(code, 'pikchr')
        if width or height:
            image_args = (f'width: {width if width else "auto"}, height: {height if height else "auto"}')
            body = f'image(bytes(out), format: "svg", {image_args})'
        else:
            body = ('layout(size => context {\n'
                    '    let figure = image(bytes(out), format: "svg")\n'
                    '    if measure(figure).width > size.width { image(bytes(out), format: "svg", width: 100%) } else { figure }\n'
                    '  })')
        return ('#align(center)[#{\n'
                f'  import "@preview/kip:{pikchr_render.KIP_VERSION}": pikchr-plugin\n'
                f'  let out = str(pikchr-plugin.typst_pikchr(bytes({_typst_multiline_literal(code)})))\n'
                '  if not out.trim().starts-with("<svg") { panic("Pikchr error: " + out) }\n'
                f'  {body}\n'
                '}]\n\n')

    def _render_figure(self, kind, code, width=None, height=None):
        """```cetz・```fletcherフェンスの内容を、Typstのcetz・fletcherで描くコードへ変換する（#236）。
        原稿のコードは、`eval`へ文字列として渡し、ファイルを読む関数と`import`・`include`を禁じる（cetz_render.pyの先頭を参照）。
        `import`・`include`は、生成の前に検出して、Fail-fastでエラーにする。
        plugins.cetz・plugins.fletcher: falseなら、素のコード表示にする。
        テンプレートの補助関数にしない（`_render_pikchr`と同じ理由: カスタムテンプレートを壊さないため）。"""
        if not self.figure_enabled[kind]:
            return self._render_raw_text(code, kind)
        try:
            cetz_render.check_code(code)
        except cetz_render.FigureCodeError as e:
            # 直近のブロック（このフェンス）の開始行に、コードの中の行を足す。layoutの中など、分からなければ、行なし
            at = self._block_line + e.code_line if (self._block_line and e.code_line) else None
            self._diagram_error(cetz_render.LABELS[kind], str(e), at)
            sys.exit(1)
        return cetz_render.pdf_source(kind, code, width, height)

    def _diagram_error(self, tool, output, line=None):
        """図の描画の失敗を、エラーとして出す（呼び出し側が、sys.exitで止める）。
        messageは短い要約にし、ツールの出力は、detailへ入れる（Viewerが、帯には要約だけを出し、詳細を別に見せる。#202）。
        CLIの表示は、従来どおり（原稿のパスと、ツールの出力を、そのまま出す）。"""
        output = (output or "").strip()
        self._error_here(f"{tool} diagram failed to render", line=line, detail=output or None,
                         cli_text=f"{tool} rendering failed for {self.current_file}:\n{output}")

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
        cache_dir = self._diagram_cache_dir()
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
        digest = _diagram_cache_key(kind, tool_version, code)
        return os.path.join(self._diagram_cache_dir(), f"{kind}_{digest}.svg"), digest

    def _diagram_cache_dir(self):
        """図のSVGのキャッシュのフォルダ（作って返す）。cache_dirの指定がなければ、原稿の隣の.text-compositor/cache/。"""
        cache_dir = self.cache_dir or os.path.join(self.base_dir, ".text-compositor", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

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

    def _graphviz_svg_path(self, code, line=None, code_line=None):
        """Graphvizの図のSVG（キャッシュ）のパスを返す。無ければ、Typstのパッケージ`diagraph`で作る（#264）。PDFと同じ経路。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。
        code_line: DOTの1行目の、原稿での行（フェンスの次の行。図の単体ファイルなら1）。構文エラーの行を、原稿の行に直すために使う。"""
        try:
            version = graphviz_render.cache_version()
        except ImportError as e:   # typstが入っていない（HTML出力のGraphvizは、Typstを通す）
            self._diagram_error("Graphviz", str(e), line)
            sys.exit(1)
        svg_path, _ = self._diagram_cache_path("graphviz", version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering Graphviz diagram via diagraph (Typst) -> {os.path.basename(svg_path)}")
            try:
                svg = graphviz_render.render_svg(code)
            except graphviz_render.GraphvizRenderError as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー。diagraphが返すDOTの行を、原稿の行にする
                at = code_line + e.dot_line - 1 if (code_line and e.dot_line) else line
                self._diagram_error("Graphviz", str(e), at)
                sys.exit(1)
            except Exception as e:   # typstの読み込みの失敗など
                self._diagram_error("Graphviz", f"{type(e).__name__}: {e}", line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached Graphviz diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _pikchr_svg_path(self, code, line=None, code_line=None):
        """Pikchrの図のSVG（キャッシュ）のパスを返す。無ければ、Typstのパッケージ`kip`で作る（#213）。PDFと同じ経路。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行。code_line: コードの1行目の、原稿での行。"""
        try:
            version = pikchr_render.cache_version()
        except ImportError as e:   # typstが入っていない（HTML出力のPikchrは、Typstを通す）
            self._diagram_error("Pikchr", str(e), line)
            sys.exit(1)
        svg_path, _ = self._diagram_cache_path("pikchr", version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering Pikchr diagram via kip (Typst) -> {os.path.basename(svg_path)}")
            try:
                svg = pikchr_render.render_svg(code)
            except pikchr_render.PikchrRenderError as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー。Pikchrが返す行を、原稿の行にする
                at = code_line + e.code_line - 1 if (code_line and e.code_line) else line
                self._diagram_error("Pikchr", str(e), at)
                sys.exit(1)
            except Exception as e:   # typstの読み込みの失敗など
                self._diagram_error("Pikchr", f"{type(e).__name__}: {e}", line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached Pikchr diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _figure_svg_path(self, kind, code, line=None, code_line=None):
        """CeTZ・Fletcherの図のSVG（キャッシュ）のパスを返す。無ければ、Typstのパッケージで作る（#236）。PDFと同じ経路。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行。code_line: コードの1行目の、原稿での行。
        Typstのエラーは、`eval`の中の位置を含まないため、行は、`import`・`include`の検出（コードの中の行が分かる）を除き、フェンスの行にする。"""
        label = cetz_render.LABELS[kind]
        try:
            version = cetz_render.cache_version(kind)
        except ImportError as e:   # typstが入っていない（HTML出力のCeTZ・Fletcherは、Typstを通す）
            self._diagram_error(label, str(e), line)
            sys.exit(1)
        svg_path, _ = self._diagram_cache_path(kind, version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering {label} diagram via Typst -> {os.path.basename(svg_path)}")
            try:
                svg = cetz_render.render_svg(kind, code)
            except cetz_render.FigureCodeError as e:
                at = code_line + e.code_line - 1 if (code_line and e.code_line) else line
                self._diagram_error(label, str(e), at)
                sys.exit(1)
            except cetz_render.FigureRenderError as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                self._diagram_error(label, str(e), line)
                sys.exit(1)
            except Exception as e:   # typstの読み込みの失敗など
                self._diagram_error(label, f"{type(e).__name__}: {e}", line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached {label} diagram: {os.path.basename(svg_path)}")
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
