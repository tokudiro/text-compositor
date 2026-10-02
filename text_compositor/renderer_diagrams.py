"""図のフェンス（Mermaid・PlantUML・D2・Graphviz・Pikchr・CeTZ・Fletcher・timeliney・finite・Structurizr・svg）の描画と、図のSVGのキャッシュ。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。状態（`self`の属性）は、`TypstRenderer`と共有する（#225）。
"""
import base64
import glob
import os
import re
import sys
import subprocess
import hashlib
import tempfile
from text_compositor import cetz_render, graphviz_render, host_renderers, pikchr_render, svg_trim, vega_render, wavedrom_render, bytefield_render
from text_compositor.deps import D2_RELEASE, MERMAID_JS_SHA256, VEGA_JS_SHA256, VEGA_LITE_JS_SHA256, WAVEDROM_JS_SHA256, WAVEDROM_SKIN_SHA256, BYTEFIELD_JS_SHA256, PLANTUML_JAR_SHA256, STRUCTURIZR_CLI_SHA256, _system_d2_version, bundled_d2_bin, bundled_java_bin, bundled_plantuml_jar, bundled_structurizr_cli_lib, ensure_d2_binary, ensure_mermaid_js, ensure_vega_js, ensure_wavedrom_js, ensure_bytefield_js, ensure_plantuml_jar, ensure_structurizr_cli, ensure_temurin_jre, find_system_d2, find_system_java
from text_compositor.env_check import _check_d2, _check_isolated_env, _check_plantuml, _check_structurizr
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


# java起動時に、JVM自体の文字コードをUTF-8に固定するオプション（#306）。JEP 400（JDK18）でfile.encodingの
# 既定はUTF-8になったが、stdin/stdout/stderrの既定はプラットフォームのネイティブエンコーディングに従う
# 場合があり、Windows等では日本語ラベルが文字化けし得る。3つとも明示することで、JDKバージョン・
# プラットフォーム・ロケールに依存させない。古いJDK（stdin/stdout/stderr.encodingが無い11〜17）でも、
# 未知の-Dは無害な追加システムプロパティとして無視されるだけなので、常に付けてよい。
_JAVA_UTF8_ENCODING_OPTS = [
    "-Dfile.encoding=UTF-8",
    "-Dstdin.encoding=UTF-8",
    "-Dstdout.encoding=UTF-8",
    "-Dstderr.encoding=UTF-8",
]


class DiagramMixin:
    """図のフェンス（Mermaid・PlantUML・D2・Graphviz・Pikchr・CeTZ・Fletcher・timeliney・finite・svg）の描画と、図のSVGのキャッシュ。"""

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

    # 今のフェンスの代替テキスト（#398）。_render_diagram_fenceが、描画の間だけ、入れ、`_render_sized_image`が、使う
    # （各`_render_*`の引数を、すべて増やさずに、画像として入る図に、alt を渡すため）。
    _pending_alt = None

    # フェンスの`alt="..."`（#398）。値は、"…"・'…'・空白なしの語のどれか。空白を含む値があるため、FENCE_ATTR_REとは別に取り出す。
    ALT_ATTR_RE = re.compile(r"""\balt\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s}"']+))""")

    def _parse_alt_attr(self, attrs_str):
        """フェンスのinfo string中の属性部分（例: '{alt="ログインの流れ" width=50%}'）から、図の代替テキスト`alt`を取り出す（#398）。
        スクリーンリーダー向けの説明で、HTMLでは`<img alt>`、PDFでは、Typstの`image`の`alt`に入る。
        未指定ならNone（呼び出し側は、既定の「<種類> diagram」を使う）。`alt=""`は、空文字（装飾の図として、読み上げから外す）。"""
        match = self.ALT_ATTR_RE.search(attrs_str) if attrs_str else None
        if not match:
            return None
        quoted_double, quoted_single, bare = match.groups()
        return next(v for v in (quoted_double, quoted_single, bare) if v is not None)

    def _without_alt(self, attrs_str):
        """`alt="..."`を取り除いた属性部分。altの値の中に`width=`などがあっても、別の属性と取り違えないため。"""
        return self.ALT_ATTR_RE.sub('', attrs_str) if attrs_str else attrs_str

    def _render_diagram_fence(self, lang, code, width=None, height=None, trim=None, alt=None):
        """```mermaid/```plantuml/```d2/```dot/```graphviz/```pikchr/```cetz/```fletcher/```timeliney/```finite/```svgフェンスの内容をTypstコードへ
        変換する。通常のMarkdownフロー（render_tokens）とlayout-right/layout-compareブロックの
        双方から共通で呼べるようにした処理（#77）。width/height（#82）が指定された場合、
        mermaid/plantuml/svg/d2は自動縮小（fit-image）をバイパスして直接そのサイズで埋め込み、
        dot/graphvizは_render_graphvizが同様にバイパスする。trim（#315）は、mermaid/plantuml/d2/
        structurizrにのみ効く（他は渡しても無視される）。alt（#398）は、画像として入る図（mermaid/plantuml/d2/structurizr/svg/
        vega/wavedrom/bytefield）の代替テキスト。Typstが描く図（graphviz/pikchr/cetz/fletcher/timeliney/finite）は、画像でないため、PDFでは使わない。"""
        self._pending_alt = alt
        try:
            return self._render_diagram_fence_inner(lang, code, width, height, trim)
        finally:
            self._pending_alt = None

    def _render_diagram_fence_inner(self, lang, code, width, height, trim):
        if lang == 'mermaid':
            return self._render_mermaid(code, width, height, trim)
        elif lang == 'plantuml':
            return self._render_plantuml(code, width, height, trim)
        elif lang == 'svg':
            return self._render_svg(code, width, height)
        elif lang == 'd2':
            return self._render_d2(code, width, height, trim)
        elif lang == 'structurizr':
            return self._render_structurizr(code, width, height, trim)
        elif lang == 'pikchr':
            return self._render_pikchr(code, width, height)
        elif lang in cetz_render.KINDS:
            return self._render_figure(lang, code, width, height)
        elif lang in vega_render.LANGS:
            return self._render_vega(lang, code, width, height)
        elif lang in wavedrom_render.LANGS:
            return self._render_wavedrom(code, width, height)
        elif lang in bytefield_render.LANGS:
            return self._render_bytefield(code, width, height)
        return self._render_graphviz(lang, code, width, height)

    def _render_diagram_or_image_match(self, m):
        """DIAGRAM_OR_IMAGE_REの1マッチをTypstコードへ変換する。フェンスは_render_diagram_fenceへ、
        単独行のMarkdown画像は通常の画像処理（alt|width=/height=構文込み）をそのまま再利用するため
        _render_markdown_segmentに委譲する（#77）。"""
        if m.group('lang'):
            width, height = self._parse_size_attrs(m.group('attrs'))
            trim = self._parse_trim_attr(m.group('attrs'))
            return self._render_diagram_fence(m.group('lang'), m.group('code'), width, height, trim,
                                              self._parse_alt_attr(m.group('attrs')))
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
        """```cetz・```fletcher・```timeliney・```finiteフェンスの内容を、Typstのcetz・fletcher・timeliney・finiteで描くコードへ変換する（#236・#294・#292）。
        原稿のコードは、`eval`へ文字列として渡し、ファイルを読む関数と`import`・`include`を禁じる（cetz_render.pyの先頭を参照）。
        `import`・`include`は、生成の前に検出して、Fail-fastでエラーにする。
        plugins.cetz・plugins.fletcher・plugins.timeliney・plugins.finite: falseなら、素のコード表示にする。
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
            image = f'image("{root_rel_path}"{width_arg}{height_arg})'
        else:
            image = f'fit-image("{root_rel_path}")'
        if self._pending_alt is not None:
            # 代替テキスト（#398）。`set image(alt: ...)`は、fit-image（layoutの中で`image`を作る）にも効く（実測）。
            # fit-imageの引数を増やさないため、独自のテンプレートが、壊れない。
            return f'#align(center)[#{{ set image(alt: "{escape_string_literal(self._pending_alt)}"); {image} }}]\n\n'
        return f'#align(center)[#{image}]\n\n'

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

    # `data:`のURIから、画像の種類（MIME）→ 書き出す拡張子。Typstのimage()が扱える形式に限る。
    _DATA_URI_EXTS = {
        'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/gif': 'gif',
        'image/svg+xml': 'svg', 'image/webp': 'webp',
    }
    _DATA_URI_RE = re.compile(
        r'^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?:;charset=[^;,]+)?(?:;(?P<enc>base64))?,(?P<data>.*)$', re.DOTALL)

    def _resolve_data_uri_asset(self, src):
        """`data:`のURIの画像を、図のSVGと同じキャッシュフォルダへ書き出し、絶対パスを返す。
        Typstの`#image()`は、ファイルパスしか受け取らず、`data:`のURIをそのまま渡せないため
        （HTMLはブラウザが`data:`を直接解釈できるが、PDFは、一度ファイルに書き出す必要がある。#238）。"""
        m = self._DATA_URI_RE.match(src)
        mime = (m.group('mime') or '').lower() if m else ''
        ext = self._DATA_URI_EXTS.get(mime)
        if not m or m.group('enc') != 'base64' or not ext:
            self._error_here(f"Unsupported data: URI image (referenced from {self.current_file}): "
                             f"only base64-encoded {', '.join(sorted(self._DATA_URI_EXTS))} are supported.")
            sys.exit(1)
        try:
            raw = base64.b64decode(m.group('data'), validate=True)
        except Exception:
            self._error_here(f"Invalid base64 in data: URI image (referenced from {self.current_file}).")
            sys.exit(1)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        path = os.path.join(self._diagram_cache_dir(), f"datauri_{digest}.{ext}")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(raw)
        return path

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
        """キャッシュキーに使うd2のバージョン。同梱・システムのd2があればその実バージョン、無ければ
        自動取得の対象（D2_RELEASE）。どちらの場合も、ここではバイナリの取得は行わない。"""
        if self._d2_version_cache is None:
            existing_d2 = bundled_d2_bin() or find_system_d2()
            version = _system_d2_version(existing_d2) if existing_d2 else None
            self._d2_version_cache = version or D2_RELEASE
        return self._d2_version_cache

    def _resolve_trim(self, trim):
        """トリミング（#315）を、この図に適用するか。フェンス属性`{trim=...}`（trim引数）が
        あればそれを優先し、無ければplugins.diagram_trimの既定値を使う。"""
        return self.diagram_trim_enabled if trim is None else trim

    def _maybe_trim_svg(self, svg, effective_trim, label):
        """effective_trimがtrueなら、svg_trim.trim_svg()でSVGの余白を縮める（#315）。
        失敗しても、元の図自体は正しく描画済みのため、ビルドは失敗させず、元のSVGのまま使う
        （svg_trim.TrimErrorのdocstring参照）。resvg_py・Pillow未導入時は、Fail-fastする
        （利用者が明示的にtrimを有効にしたのに、静かに無効化されたと気づかないままにしないため）。"""
        if not effective_trim:
            return svg
        try:
            return svg_trim.trim_svg(svg)
        except svg_trim.TrimError as e:
            _log_info(f"{label}: could not trim the diagram's margin; keeping it as-is ({e}).")
            return svg
        except ImportError:
            _error("plugins.diagram_trim: true requires the 'resvg_py' and 'Pillow' packages. "
                  "Install them with: pip install resvg_py Pillow")
            sys.exit(1)

    def _render_mermaid(self, code, width=None, height=None, trim=None):
        """mermaidブロックをヘッドレスブラウザ上のmermaid.render()でSVG化し、Typstのimage呼び出しに
        変換する。外部APIへの通信は行わず、ローカルのブラウザで完結させる（仕様書10章・11章、#35）。"""
        svg_path = self._mermaid_svg_path(code, trim=trim)
        if svg_path is None:
            return f"```mermaid\n{code}```\n\n"
        # fit-image() は templates/slide.typ 側で定義されているため、image() の相対パス解決基準は
        # base_dir ではなく templates/ になってしまう。ファイルの置き場所に依存しない
        # ルート絶対パス（--root 起点の "/..." 形式）にして、どこから呼んでも解決できるようにする。
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _render_vega(self, lang, code, width=None, height=None):
        """```vega-lite・```vegaフェンス（JSONの仕様）を、ヘッドレスブラウザ上のVega・Vega-LiteでSVG化し、Typstのimage呼び出しに
        変換する（#211）。外部APIへの通信は行わず、ローカルのブラウザで完結させる。plugins.vega: falseなら、素のコード表示にする。"""
        svg_path = self._vega_svg_path(lang, code)
        if svg_path is None:
            return f"```{lang}\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _vega_svg_path(self, lang, code, line=None):
        """```vega-lite・```vegaの図のSVG（キャッシュ）のパスを返す。無ければ、ヘッドレスブラウザで描画して作る。
        plugins.vega: falseなら、何も作らずNoneを返す（呼び出し側が、素のコード表示にフォールバックする）。
        仕様は、描画の前に検査する（vega_render.parse_spec）。JSONの誤りと、外部リソースの参照（`url`）は、Fail-fastでエラーにする。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        label = vega_render.LABELS[lang]
        if not self.vega_enabled:
            if not self._vega_disabled_warned:
                _log_info(f"plugins.vega is disabled; leaving ```vega-lite / ```vega fences as plain code (first seen in {self.current_file}).")
                self._vega_disabled_warned = True
            return None

        used_files = []
        try:
            spec = vega_render.parse_spec(code, load=self._vega_data_loader(used_files))
        except vega_render.SpecError as e:
            self._diagram_error(label, str(e), line)
            sys.exit(1)

        # 固定済みJS（vega・vega-lite）のSHA256を、バージョンとして使う（どちらかが変われば、別キーになる）。
        version = f"{VEGA_JS_SHA256}:{VEGA_LITE_JS_SHA256}:v1"
        # データファイルを読んだときは、その内容のハッシュも、キーに含める（データを変えたら、描き直す。#350）。
        # 読まなかったときは、キーを変えない（`url`を使わない図の、既存のキャッシュを、無効にしない）。
        key_code = code + "".join(f"\0{digest}" for _, digest in used_files)
        svg_path, digest = self._diagram_cache_path(lang, version, key_code)

        if not os.path.exists(svg_path):
            host = host_renderers._vega_host_renderer
            _log_info(f"Rendering {label} diagram via {'the host application' if host else 'headless browser'} -> {os.path.basename(svg_path)}")
            try:
                if host:
                    # 描画は、呼び出し元（ViewerのElectron）が行う。JSの取得・検証は、こちらで行い、パスを渡す。
                    # 描画スクリプトも、こちらから渡す（ブラウザ版と、同じ処理を使うため）
                    vega_js, vega_lite_js = ensure_vega_js()
                    svg = host(f"{lang}-{digest}", lang, spec, vega_render.RENDER_SCRIPT,
                               {"vega": vega_js, "vega_lite": vega_lite_js})
                else:
                    page = self._mermaid.ensure_vega_page(self.mermaid_enabled, self.mermaid_auto_download)
                    svg = page.evaluate(vega_render.RENDER_SCRIPT, [lang, spec])
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                message = "\n".join(l for l in str(e).splitlines() if not re.match(r"\s+at ", l))
                message = re.sub(r"^Page\.evaluate: (Error: )?", "", message)
                self._diagram_error(label, message, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached {label} diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _render_wavedrom(self, code, width=None, height=None):
        """```wavedromフェンス（JSONの仕様）を、ヘッドレスブラウザ上のWaveDromでSVG化し、Typstのimage呼び出しに変換する（#299）。
        外部APIへの通信は行わず、ローカルのブラウザで完結させる。plugins.wavedrom: falseなら、素のコード表示にする。"""
        svg_path = self._wavedrom_svg_path(code)
        if svg_path is None:
            return f"```wavedrom\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _wavedrom_svg_path(self, code, line=None):
        """```wavedromの図のSVG（キャッシュ）のパスを返す。無ければ、ヘッドレスブラウザで描画して作る。
        plugins.wavedrom: falseなら、何も作らずNoneを返す（呼び出し側が、素のコード表示にフォールバックする）。
        仕様は、描画の前に検査する（wavedrom_render.parse_spec）。JSONの誤りと、描けない形は、Fail-fastでエラーにする。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        label = wavedrom_render.LABEL
        if not self.wavedrom_enabled:
            if not self._wavedrom_disabled_warned:
                _log_info(f"plugins.wavedrom is disabled; leaving ```wavedrom fences as plain code (first seen in {self.current_file}).")
                self._wavedrom_disabled_warned = True
            return None

        try:
            spec = wavedrom_render.parse_spec(code)
        except wavedrom_render.SpecError as e:
            self._diagram_error(label, str(e), line)
            sys.exit(1)

        # 固定済みJS（本体・スキン）のSHA256を、バージョンとして使う（どちらかが変われば、別キーになる）。
        version = f"{WAVEDROM_JS_SHA256}:{WAVEDROM_SKIN_SHA256}:v1"
        svg_path, digest = self._diagram_cache_path('wavedrom', version, code)

        if not os.path.exists(svg_path):
            host = host_renderers._wavedrom_host_renderer
            _log_info(f"Rendering {label} diagram via {'the host application' if host else 'headless browser'} -> {os.path.basename(svg_path)}")
            try:
                if host:
                    # 描画は、呼び出し元（ViewerのElectron）が行う。JSの取得・検証と、描画スクリプトは、こちらから渡す（#392）
                    skin_js, wavedrom_js = ensure_wavedrom_js()
                    svg = host(f"wavedrom-{digest}", spec, wavedrom_render.RENDER_SCRIPT,
                               {"skin": skin_js, "wavedrom": wavedrom_js})
                else:
                    page = self._mermaid.ensure_wavedrom_page(self.mermaid_enabled, self.mermaid_auto_download)
                    svg = page.evaluate(wavedrom_render.RENDER_SCRIPT, [spec])
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                message = "\n".join(l for l in str(e).splitlines() if not re.match(r"\s+at ", l))
                message = re.sub(r"^Page\.evaluate: (Error: )?", "", message)
                self._diagram_error(label, message, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached {label} diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _render_bytefield(self, code, width=None, height=None):
        """```bytefieldフェンス（Bytefield-svgの記述）を、ヘッドレスブラウザ上のBytefield-svgでSVG化し、Typstのimage呼び出しに変換する（#300）。
        外部APIへの通信は行わず、ローカルのブラウザで完結させる。plugins.bytefield: falseなら、素のコード表示にする。"""
        svg_path = self._bytefield_svg_path(code)
        if svg_path is None:
            return f"```bytefield\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _bytefield_svg_path(self, code, line=None):
        """```bytefieldの図のSVG（キャッシュ）のパスを返す。無ければ、ヘッドレスブラウザで描画して作る。
        plugins.bytefield: falseなら、何も作らずNoneを返す（呼び出し側が、素のコード表示にフォールバックする）。
        空の入力は、描画の前に止める（bytefield_render.parse_spec）。構文・仕様の誤りは、Bytefield-svgが、行・桁つきで報告する。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        label = bytefield_render.LABEL
        if not self.bytefield_enabled:
            if not self._bytefield_disabled_warned:
                _log_info(f"plugins.bytefield is disabled; leaving ```bytefield fences as plain code (first seen in {self.current_file}).")
                self._bytefield_disabled_warned = True
            return None

        try:
            source = bytefield_render.parse_spec(code)
        except bytefield_render.SpecError as e:
            self._diagram_error(label, str(e), line)
            sys.exit(1)

        # 固定済みJS（lib.js）のSHA256を、バージョンとして使う
        version = f"{BYTEFIELD_JS_SHA256}:v1"
        svg_path, digest = self._diagram_cache_path('bytefield', version, code)

        if not os.path.exists(svg_path):
            host = host_renderers._bytefield_host_renderer
            _log_info(f"Rendering {label} diagram via {'the host application' if host else 'headless browser'} -> {os.path.basename(svg_path)}")
            try:
                if host:
                    # 描画は、呼び出し元（ViewerのElectron）が行う。JSの取得・検証と、描画スクリプトは、こちらから渡す（#300）
                    svg = host(f"bytefield-{digest}", source, bytefield_render.RENDER_SCRIPT,
                               {"bytefield": ensure_bytefield_js()})
                else:
                    page = self._mermaid.ensure_bytefield_page(self.mermaid_enabled, self.mermaid_auto_download)
                    svg = page.evaluate(bytefield_render.RENDER_SCRIPT, [source])
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                message = "\n".join(l for l in str(e).splitlines() if not re.match(r"\s+at ", l))
                message = re.sub(r"^Page\.evaluate: (Error: )?", "", message)
                self._diagram_error(label, message, line)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached {label} diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _vega_data_loader(self, used_files):
        """Vega・Vega-Liteのデータ定義の`url`を、ファイルの中身にするための関数を返す（#350）。
        読めるのは、プロジェクトのルート（base_dir）の中にある、`.csv`・`.tsv`・`.json`だけ。相対パスは、原稿の場所が基準
        （画像と同じ）。外へ出るもの（`../`・絶対パス・シンボリックリンク）と、URLは、失敗クローズにする。
        画像の参照には、この制限がない。データは、複数の書き手が、原稿の外のファイルを、図へ取り込めないように、より厳しくする。
        読んだファイルは、used_filesへ`(絶対パス, 内容のSHA256)`で足し、HTMLでは、変更の検知（dependencies）にも加える。"""
        root = os.path.realpath(self.base_dir)
        origin = self.current_dir or self.base_dir

        def within_root(path):
            try:
                return os.path.commonpath([os.path.normcase(root), os.path.normcase(path)]) == os.path.normcase(root)
            except ValueError:   # 別のドライブ
                return False

        def load(url):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]+:', url) or url.startswith('//'):
                raise vega_render.SpecError(f"External URLs are not supported: '{url}'. Use a data file inside the project.")
            if os.path.isabs(url) or url.startswith(('/', '\\')) or re.match(r'^[a-zA-Z]:', url):
                raise vega_render.SpecError(f"Absolute paths are not allowed: '{url}'. Use a path relative to the manuscript.")
            ext = os.path.splitext(url)[1].lower()
            if ext not in vega_render.DATA_EXTENSIONS:
                raise vega_render.SpecError(
                    f"Unsupported data file type: '{url}'. Supported: {', '.join(sorted(vega_render.DATA_EXTENSIONS))}.")
            path = os.path.realpath(os.path.join(origin, url))
            if not within_root(path):
                raise vega_render.SpecError(f"The data file is outside the project: '{url}'. Only files inside {root} can be used.")
            dependencies = getattr(self, 'dependencies', None)
            if dependencies is not None:
                dependencies.add(path)   # 無いファイルも入れる（あとから作られたときに、更新できるように。画像と同じ）
            if not os.path.isfile(path):
                raise vega_render.SpecError(f"Data file not found: {path}")
            size = os.path.getsize(path)
            if size > vega_render.MAX_DATA_BYTES:
                raise vega_render.SpecError(
                    f"The data file is too large: '{url}' ({size / 1048576:.1f} MB; the limit is {vega_render.MAX_DATA_BYTES // 1048576} MB).")
            with open(path, 'rb') as f:
                raw = f.read()
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise vega_render.SpecError(f"The data file is not UTF-8: '{url}'.") from None
            used_files.append((path, hashlib.sha256(raw).hexdigest()))
            return text, vega_render.DATA_EXTENSIONS[ext]

        return load

    def _mermaid_svg_path(self, code, line=None, trim=None):
        """mermaidの図のSVG（キャッシュ）のパスを返す。無ければ、ヘッドレスブラウザで描画して作る。
        plugins.mermaid: falseなら、何も作らずNoneを返す（呼び出し側が、素のコード表示にフォールバックする）。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行（分かる場合）。"""
        if not self.mermaid_enabled:
            if not self._mermaid_disabled_warned:
                _log_info(f"plugins.mermaid is disabled; leaving ```mermaid fences as plain code (first seen in {self.current_file}).")
                self._mermaid_disabled_warned = True
            return None

        effective_trim = self._resolve_trim(trim)
        # 固定済みmermaid.min.jsのSHA256をバージョンとして使う（バンドルが変われば別キーになる）。
        # ":margin1"は、mermaid.initialize()の余白設定（flowchart.padding等、#315）のバージョン。
        # トリミング（#315）が有効なときだけ":trim1"を足す。既定（無効）のキーは変えないことで、
        # plugins.diagram_trimを使わない大多数のプロジェクトの既存キャッシュを、無駄に無効化しない。
        version = f"{MERMAID_JS_SHA256}:margin1" + (":trim1" if effective_trim else "")
        svg_path, digest = self._diagram_cache_path("mermaid", version, code)

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
            svg = self._maybe_trim_svg(svg, effective_trim, "mermaid")
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
        """CeTZ・Fletcher・timeliney・finiteの図のSVG（キャッシュ）のパスを返す。無ければ、Typstのパッケージで作る（#236・#294・#292）。PDFと同じ経路。
        line: 失敗したときの診断に付ける、原稿でのフェンスの行。code_line: コードの1行目の、原稿での行。
        Typstのエラーは、`eval`の中の位置を含まないため、行は、`import`・`include`の検出（コードの中の行が分かる）を除き、フェンスの行にする。"""
        label = cetz_render.LABELS[kind]
        try:
            version = cetz_render.cache_version(kind)
        except ImportError as e:   # typstが入っていない（HTML出力のCeTZ・Fletcher・timeliney・finiteは、Typstを通す）
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

    def _math_svg_path(self, code, display_mode=False, line=None, code_line=None):
        """数式のSVG（キャッシュ）のパスを返す。無ければ、Typstのパッケージ`mitex`で作る（#183）。
        line: 失敗したときの診断に付ける、原稿での行。"""
        from text_compositor import math_render
        kind = math_render.kind_for(display_mode)
        try:
            version = math_render.cache_version(kind)
        except ImportError as e:
            self._diagram_error("Math", str(e), line)
            sys.exit(1)
        svg_path, _ = self._diagram_cache_path(kind, version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering math via Typst (mitex) -> {os.path.basename(svg_path)}")
            try:
                svg = math_render.render_svg(code, kind)
            except math_render.MathRenderError as e:
                at = code_line if code_line else line
                self._diagram_error("Math", str(e), at)
                sys.exit(1)
            except Exception as e:
                at = code_line if code_line else line
                self._diagram_error("Math", f"{type(e).__name__}: {e}", at)
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached math: {os.path.basename(svg_path)}")
        return svg_path


    def _ensure_plantuml_tools(self):
        """PlantUML実行に必要なjava実行ファイルとplantuml.jarを遅延解決する（初回のみ）。
        Obunzuが配布物に同梱したもの（`TEXT_COMPOSITOR_JAVA_BIN`・`TEXT_COMPOSITOR_PLANTUML_JAR`。
        #290）があれば最優先で使う。無ければシステムJava（11+）をそのまま再利用する（2章の最小限の
        ダウンロード）。それも無い場合、plugins.plantuml_auto_download（既定true）ならEclipse
        Temurin JREを自動取得し、falseならFail-fastでエラー終了する。mermaidのブラウザ自動取得
        （既定false）と非対称な既定値なのは、ダウンロードされる実体のサイズが一桁違うため
        （JRE約49.7MB対Chromium約700MB。#22の設計議論）。"""
        if self._plantuml_java_bin is None:
            java_bin = bundled_java_bin()
            if java_bin:
                _log_info(f"Using bundled Java for PlantUML rendering: {java_bin}")
            else:
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
            self._plantuml_jar_path = bundled_plantuml_jar() or ensure_plantuml_jar()
        return self._plantuml_java_bin, self._plantuml_jar_path

    def _render_plantuml(self, code, width=None, height=None, trim=None):
        """```plantumlブロックをローカルのjava+plantuml.jar（Smetanaレイアウトエンジン。dot等の
        外部バイナリに依存しない）でSVG化し、Typstのimage呼び出しに変換する。外部APIへの通信は
        行わない（仕様書10章・11章、#22）。コードは実際のPlantUML構文どおり@startuml/@enduml
        込みで書く必要がある（暗黙の補完はしない。9章の決定論的出力・明示性の方針に沿う）。"""
        svg_path = self._plantuml_svg_path(code, trim=trim)
        if svg_path is None:
            return f"```plantuml\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _run_plantuml_jar(self, java_bin, jar_path, code, timeout=60):
        """plantuml.jarへcodeを標準入力で渡し、SVGを標準出力から受け取る（PlantUML本体・
        Structurizr共通、#212）。OSError・終了コードのハンドリングは呼び出し側が行う。"""
        return subprocess.run(
            [java_bin, *_JAVA_UTF8_ENCODING_OPTS, "-jar", jar_path, "-tsvg", "-pipe", "-Playout=smetana"],
            input=code, capture_output=True, text=True, encoding="utf-8", timeout=timeout)

    # 複数の図をまとめて1回のJVM起動で処理するときの区切り文字列（#307）。plantuml.jarの
    # `-pipedelimitor`が標準出力にこの行をそのまま挟んで返す仕様を使う（実機確認）。図のコード
    # 自身にこの文字列が現れる可能性は無視できるほど低いため、固定値のままにする。
    _PLANTUML_BATCH_DELIMITER = "===text-compositor-plantuml-batch-delimiter==="

    def _run_plantuml_batch(self, java_bin, jar_path, codes, timeout=120):
        """複数のPlantUMLソース（codes）を、1回のJVM起動でまとめて処理する（#307）。
        `-pipe`は標準入力に連結した複数の@startuml/@endumlブロックを読み、`-pipedelimitor`で
        指定した区切り文字列を挟んで図の数だけSVG（または失敗時はエラー画像のSVG）を順に返す
        仕様がある（実機確認、ヘルプ上の記載はない）。1件でも構文エラーがあると、プロセス全体の
        終了コードが非0になり、標準エラーには最初のエラーだけしか出ない（どの図かは特定できない）ため、
        呼び出し側はreturncode!=0の場合、1件ずつ_run_plantuml_jar()で再実行してどれが失敗かを
        特定すること（安全側に倒す設計、#307のissueコメント参照）。
        戻り値は(returncode, パース済みのSVG文字列のリスト, stderr)。JVM自体の異常終了等で
        図の数とパースできた要素数が一致しない場合もあるため、呼び出し側は必ず数を確認すること。"""
        combined = "".join(codes)
        result = subprocess.run(
            [java_bin, *_JAVA_UTF8_ENCODING_OPTS, "-jar", jar_path, "-tsvg", "-pipe",
             "-pipedelimitor", self._PLANTUML_BATCH_DELIMITER, "-Playout=smetana"],
            input=combined, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        delim_line = self._PLANTUML_BATCH_DELIMITER + "\n"
        parts = result.stdout.split(delim_line)
        if parts and parts[-1] == "":
            parts = parts[:-1]
        return result.returncode, parts, result.stderr

    def _plantuml_svg_path(self, code, line=None, trim=None):
        """plantumlの図のSVG（キャッシュ）のパスを返す。無ければ、ローカルのjava+plantuml.jarで作る。
        plugins.plantuml: falseなら、何も作らずNoneを返す。line: 失敗時の診断に付ける行。"""
        if not self.plantuml_enabled:
            if not self._plantuml_disabled_warned:
                _log_info(f"plugins.plantuml is disabled; leaving ```plantuml fences as plain code (first seen in {self.current_file}).")
                self._plantuml_disabled_warned = True
            return None

        effective_trim = self._resolve_trim(trim)
        # トリミング（#315）が有効なときだけ":trim1"を足す（既定のキャッシュキーは変えない。
        # prefetch_plantuml_diagrams()の事前描画フェーズは、常にtrim無しのキーで書くため、
        # trim有効時はここで作り直す。バッチ起動の高速化（#307）が効かなくなるだけで、
        # 正しさには影響しない）。
        version = PLANTUML_JAR_SHA256 + (":trim1" if effective_trim else "")
        svg_path, _ = self._diagram_cache_path("plantuml", version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering PlantUML diagram via local Java -> {os.path.basename(svg_path)}")
            java_bin, jar_path = self._ensure_plantuml_tools()
            try:
                result = self._run_plantuml_jar(java_bin, jar_path, code)
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
            svg = self._maybe_trim_svg(result.stdout, effective_trim, "PlantUML")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached PlantUML diagram: {os.path.basename(svg_path)}")
        return svg_path

    def _ensure_structurizr_tools(self):
        """Structurizr実行に必要なjava実行ファイル・structurizr-cli一式・plantuml.jarを遅延解決する
        （初回のみ）。Obunzuが配布物に同梱したもの（`TEXT_COMPOSITOR_JAVA_BIN`・
        `TEXT_COMPOSITOR_STRUCTURIZR_CLI_LIB`・`TEXT_COMPOSITOR_PLANTUML_JAR`。#290）があれば
        最優先で使う。Javaの自動取得はplugins.structurizr_auto_downloadで制御し、
        plugins.plantuml_auto_downloadとは独立させる（structurizrを使うプロジェクトが常にPlantUMLも
        有効とは限らないため）。plantuml.jar自体は、内部実装として常に要る（plugins.plantumlの値には
        左右されない、#212）。"""
        if self._structurizr_java_bin is None:
            java_bin = bundled_java_bin()
            if java_bin:
                _log_info(f"Using bundled Java for Structurizr rendering: {java_bin}")
            else:
                java_bin = find_system_java()
                if java_bin:
                    _log_info(f"Reusing system Java for Structurizr rendering: {java_bin}")
                elif self.structurizr_auto_download:
                    java_bin = ensure_temurin_jre()
                else:
                    _error("No local Java 11+ found; required to render Structurizr diagrams. "
                          "Install Java 11+, or set plugins.structurizr_auto_download: true "
                          "(downloads Eclipse Temurin JRE, approx. 50MB), or set plugins.structurizr: false.")
                    sys.exit(1)
            self._structurizr_java_bin = java_bin
        if self._structurizr_lib_dir is None:
            self._structurizr_lib_dir = bundled_structurizr_cli_lib() or ensure_structurizr_cli()
        if self._structurizr_plantuml_jar_path is None:
            self._structurizr_plantuml_jar_path = bundled_plantuml_jar() or ensure_plantuml_jar()
        return self._structurizr_java_bin, self._structurizr_lib_dir, self._structurizr_plantuml_jar_path

    def _render_structurizr(self, code, width=None, height=None, trim=None):
        """```structurizrブロック（C4モデルのDSL）を、ローカルのjava+structurizr-cli（公式、
        Apache-2.0）でPlantUMLへ書き出し、それを既存のPlantUML+Smetanaパイプラインでそのまま
        描画する（#212）。外部APIへの通信は行わない。新しい描画コードは持たず、DSL→PlantUML
        という変換だけを挟む。"""
        svg_path = self._structurizr_svg_path(code, trim=trim)
        if svg_path is None:
            return f"```structurizr\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    def _structurizr_dsl_to_plantuml(self, code, line=None):
        """Structurizrのワークスペース（DSL）を、structurizr-cliでPlantUMLソースへ書き出す
        （#212、#307で事前収集フェーズからも呼べるよう`_structurizr_svg_path`から切り出した）。

        structurizr-cliは、ワークスペースが定義するビューの数だけファイルを分けて書き出す仕様で、
        CLI引数で1つだけ選ぶ方法は無い（実機確認）。このツールは「1フェンス=1図」という他の図表と
        同じ原則を保つため、ビューは1つに限定し、0または2つ以上ならFail-fastでエラーにする
        （複数ビューを1つのモデルから使い回したい場合は、DSLの`!include`で共通モデルを別ファイルへ
        切り出し、フェンスごとに`views`ブロックだけ変えるよう案内する）。"""
        java_bin, lib_dir, _ = self._ensure_structurizr_tools()
        with tempfile.TemporaryDirectory(prefix="structurizr-") as tmp_dir:
            dsl_path = os.path.join(tmp_dir, "workspace.dsl")
            with open(dsl_path, "w", encoding="utf-8") as f:
                f.write(code)
            out_dir = os.path.join(tmp_dir, "out")
            try:
                result = subprocess.run(
                    [java_bin, *_JAVA_UTF8_ENCODING_OPTS, "-cp", os.path.join(lib_dir, "*"),
                     "com.structurizr.cli.StructurizrCliApplication",
                     "export", "-workspace", dsl_path, "-format", "plantuml", "-output", out_dir],
                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            except OSError as e:
                self._error_here(f"Failed to run structurizr-cli for {self.current_file}:\n{e}")
                for diag in (_check_isolated_env(), _check_structurizr(self.structurizr_enabled, self.structurizr_auto_download)):
                    if diag.status != "OK":
                        _hint(f"[{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
            if result.returncode != 0:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                self._diagram_error("Structurizr", result.stderr or result.stdout, line)
                sys.exit(1)
            views = sorted(p for p in glob.glob(os.path.join(out_dir, "*.puml")) if not p.endswith("-key.puml"))
            if len(views) != 1:
                detail = (f"the workspace defines {len(views)} views, but exactly 1 is required per "
                          "```structurizr fence (one output image per fence). Split into separate "
                          "fences, one per view; share the model between them with the DSL's own "
                          "`!include` if needed.")
                self._diagram_error("Structurizr", detail, line)
                sys.exit(1)
            with open(views[0], "r", encoding="utf-8") as f:
                return f.read()

    def _structurizr_svg_path(self, code, line=None, trim=None):
        """Structurizrの図のSVG（キャッシュ）のパスを返す。無ければ、structurizr-cliでPlantUMLへ
        書き出し、それをローカルのjava+plantuml.jarで描画して作る。plugins.structurizr: falseなら、
        何も作らずNoneを返す。line: 失敗時の診断に付ける行。"""
        if not self.structurizr_enabled:
            if not self._structurizr_disabled_warned:
                _log_info(f"plugins.structurizr is disabled; leaving ```structurizr fences as plain code (first seen in {self.current_file}).")
                self._structurizr_disabled_warned = True
            return None

        effective_trim = self._resolve_trim(trim)
        # トリミング（#315）が有効なときだけ":trim1"を足す（既定のキャッシュキーは変えない。
        # prefetch_plantuml_diagrams()の事前描画フェーズは、常にtrim無しのキーで書くため、
        # trim有効時はここで作り直す。バッチ起動の高速化（#307）が効かなくなるだけで、
        # 正しさには影響しない）。
        version = f"{STRUCTURIZR_CLI_SHA256}:{PLANTUML_JAR_SHA256}" + (":trim1" if effective_trim else "")
        svg_path, _ = self._diagram_cache_path("structurizr", version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering Structurizr diagram via local Java -> {os.path.basename(svg_path)}")
            puml_code = self._structurizr_dsl_to_plantuml(code, line)
            java_bin, _, jar_path = self._ensure_structurizr_tools()
            try:
                result = self._run_plantuml_jar(java_bin, jar_path, puml_code)
            except OSError as e:
                self._error_here(f"Failed to run PlantUML for {self.current_file}:\n{e}")
                sys.exit(1)
            if result.returncode != 0:
                self._diagram_error("Structurizr", result.stderr, line)
                sys.exit(1)
            svg = self._maybe_trim_svg(result.stdout, effective_trim, "Structurizr")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached Structurizr diagram: {os.path.basename(svg_path)}")
        return svg_path

    def prefetch_plantuml_diagrams(self, file_texts):
        """ビルド対象のMarkdown原稿（複数ファイル分）から```plantuml/```structurizrフェンスを
        事前に集め、未キャッシュの図をまとめて1回のJVM起動で描画する（#307）。図ごとに毎回
        JVMを起動する現状（1個あたり実測1.5〜1.8秒、Structurizrは2回起動で2.4〜3.1秒）に対し、
        1回のビルドに複数の図があっても、通常は起動を1回に減らせる。呼ばなくても、通常の描画経路
        （_plantuml_svg_path/_structurizr_svg_path）が個別に描画するため、この事前フェーズは
        「呼べれば速くなる最適化」であり省いても正しさは変わらない。

        file_texts: [(filepath, text), ...]。textはfront-matter除去・{{KEY}}置換より前の生原稿でよい
        （フェンスの中身自体はどちらの影響も受けないため。variablesがコード中に使われる稀なケースは、
        キャッシュキーが一致せずこの事前フェーズの効果が及ばないだけで、後続の通常描画経路が
        従来どおり個別に描画するので正しさは保たれる）。

        plugins.plantuml・plugins.structurizrの両方がfalseなら何もしない。1件でも構文エラーが
        あった場合、バッチ全体を捨てて1件ずつ個別に再実行し、既存の診断（ファイル・行・エラー内容）
        でFail-fastする（_run_plantuml_batchのdocstring参照。バッチの標準エラーだけでは
        どの図が失敗したか特定できないため）。"""
        if not self.plantuml_enabled and not self.structurizr_enabled:
            return

        # cache_path -> (plantumlソース, 診断用のファイル・行, ラベル)
        targets = {}
        for filepath, text in file_texts:
            for m in self._finditer_outside_fences(self.DIAGRAM_OR_IMAGE_RE, text):
                lang = m.group('lang')
                if lang not in ('plantuml', 'structurizr'):
                    continue
                # markdown-itのfenceトークンのcontentは末尾に改行を1つ持つが、この正規表現の
                # codeグループは直後の`\r?\n```にマッチが取られるため改行を含まない。通常の
                # 描画経路（renderer_tokens.py、t.content）と同じキャッシュキーになるよう補う
                # （補わないと、同じ図が事前スキャン用とレンダリング用で別キーになり二重に描画される）。
                code = m.group('code') + '\n'
                line = text.count('\n', 0, m.start()) + 1
                if lang == 'plantuml':
                    if not self.plantuml_enabled:
                        continue
                    cache_path, _ = self._diagram_cache_path("plantuml", PLANTUML_JAR_SHA256, code)
                    if os.path.exists(cache_path) or cache_path in targets:
                        continue
                    targets[cache_path] = (code, filepath, line, "PlantUML")
                else:
                    if not self.structurizr_enabled:
                        continue
                    version = f"{STRUCTURIZR_CLI_SHA256}:{PLANTUML_JAR_SHA256}"
                    cache_path, _ = self._diagram_cache_path("structurizr", version, code)
                    if os.path.exists(cache_path) or cache_path in targets:
                        continue
                    # DSL->PlantUML変換自体はバッチ化できない（structurizr-cliに常駐/バッチモードは無い、
                    # #307のissueコメント参照）。1図ごとに1回起動する点は変わらない。
                    self.current_file = filepath
                    puml_code = self._structurizr_dsl_to_plantuml(code, line)
                    targets[cache_path] = (puml_code, filepath, line, "Structurizr")

        if not targets:
            return

        if self.plantuml_enabled:
            java_bin, jar_path = self._ensure_plantuml_tools()
        else:
            java_bin, _, jar_path = self._ensure_structurizr_tools()

        cache_paths = list(targets.keys())
        codes = [targets[p][0] for p in cache_paths]
        _log_info(f"Pre-rendering {len(cache_paths)} PlantUML/Structurizr diagram(s) via a single Java process...")
        try:
            returncode, parts, _stderr = self._run_plantuml_batch(java_bin, jar_path, codes)
        except OSError as e:
            self._error_here(f"Failed to run PlantUML for {self.current_file}:\n{e}")
            sys.exit(1)

        if returncode == 0 and len(parts) == len(cache_paths):
            for cache_path, svg in zip(cache_paths, parts):
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(svg)
            return

        # バッチの一部（または全部）が失敗、あるいは出力の対応が取れなかった。安全側に倒し、
        # 1件ずつ個別に再実行して、失敗した図だけをFail-fastで報告する（成功分はキャッシュに書く）。
        for cache_path in cache_paths:
            code, filepath, line, label = targets[cache_path]
            self.current_file = filepath
            try:
                result = self._run_plantuml_jar(java_bin, jar_path, code)
            except OSError as e:
                self._error_here(f"Failed to run PlantUML for {self.current_file}:\n{e}")
                sys.exit(1)
            if result.returncode != 0:
                self._diagram_error(label, result.stderr, line)
                sys.exit(1)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)

    def _ensure_d2_bin(self):
        """d2実行ファイルを遅延解決する（初回のみ）。Obunzuが配布物に同梱したもの
        （`TEXT_COMPOSITOR_D2_BIN`。#290）があれば最優先で使う。無ければシステムのdコマンドが
        あればそのまま再利用する（2章の最小限のダウンロード）。無い場合、plugins.d2_auto_download
        （既定true）ならD2公式CLIバイナリを自動取得し、falseならFail-fastでエラー終了する（#90）。"""
        if self._d2_bin is None:
            d2_bin = bundled_d2_bin()
            if d2_bin:
                _log_info(f"Using bundled D2 for d2 rendering: {d2_bin}")
            else:
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

    def _render_d2(self, code, width=None, height=None, trim=None):
        """```d2```ブロックをローカルのD2公式CLIバイナリでSVG化し、Typstのimage呼び出しに変換する。
        外部APIへの通信は行わない（仕様書10章・11章、#90）。`d2 - -`で標準入力から読み、標準出力へ
        SVGを書く（D2公式のstdin/stdout規約。ステータスメッセージは標準エラーへ出るため混ざらない）。"""
        svg_path = self._d2_svg_path(code, trim=trim)
        if svg_path is None:
            return f"```d2\n{code}```\n\n"
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

    # D2 CLIの`--pad`既定値（100px、上下左右）は、本文へ埋め込む小さな図には過大なため、
    # 小さな固定値へ縮める（#315）。実測: `A -> B`だけの図で258x434（既定）->74x250（pad8）。
    # D2自身が内容のバウンディングボックスを計算した上で外側に付け足す値のため、値を縮めても
    # 中身が見切れる心配はない（実機確認）。
    _D2_PAD = "8"

    def _d2_svg_path(self, code, line=None, trim=None):
        """d2の図のSVG（キャッシュ）のパスを返す。無ければ、ローカルのD2で作る。
        plugins.d2: falseなら、何も作らずNoneを返す。line: 失敗時の診断に付ける行。"""
        if not self.d2_enabled:
            if not self._d2_disabled_warned:
                _log_info(f"plugins.d2 is disabled; leaving ```d2 fences as plain code (first seen in {self.current_file}).")
                self._d2_disabled_warned = True
            return None

        effective_trim = self._resolve_trim(trim)
        # _D2_PADをキャッシュキーに含める。将来この値を変えたときに、古い（余白が違う）
        # キャッシュ済みSVGを再利用してしまわないようにするため。トリミング（#315）が有効な
        # ときだけ":trim1"を足す（既定のキャッシュキーは変えない）。
        version = f"{self._d2_version()}:pad{self._D2_PAD}" + (":trim1" if effective_trim else "")
        svg_path, _ = self._diagram_cache_path("d2", version, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering d2 diagram via local D2 -> {os.path.basename(svg_path)}")
            d2_bin = self._ensure_d2_bin()
            try:
                result = subprocess.run(
                    [d2_bin, "--pad", self._D2_PAD, "-", "-"],
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
            result_stdout = self._maybe_trim_svg(result.stdout, effective_trim, "d2")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(result_stdout)
        else:
            _log_verbose(f"Reusing cached d2 diagram: {os.path.basename(svg_path)}")
        return svg_path
