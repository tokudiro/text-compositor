import os
import re
import sys
import csv
import json
import io
import contextlib
import bisect
import subprocess
import hashlib
import shutil
import argparse
import urllib.request
import zipfile
import tarfile
import time
import tempfile
import platform
import importlib.metadata
import platformdirs
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from markdown_it import MarkdownIt
# タスクリスト(- [ ]/- [x])はGFM拡張のためcommonmarkプリセットに含まれず、mdit-py-pluginsの
# プラグインとして追加する（#48）。
from mdit_py_plugins.tasklists import tasklists_plugin
# 文字色指定（#46）。[text]{color=red}というPandoc由来のブラケット+属性記法をパースする
# （spans=Trueでspan_open/span_closeトークンとして出力される。既定では無効なので明示的に有効化）。
from mdit_py_plugins.attrs import attrs_plugin
# PyPIの typst パッケージ(typst-py)はコンパイラ本体をプラットフォーム別ホイールに同梱しているため、
# tools/typst.exe のような実行バイナリをリポジトリに持たずに済む（pipがOSごとに正しい版を入れてくれる）
import typst as typst_lib

try:
    import yaml
except ImportError:
    yaml = None

# ローカル環境やGitHub Actionsランナー(ubuntu-latest)に標準搭載されているChrome/Edgeの
# インストール先候補。見つかればmermaidレンダリング用にそのまま起動して再利用し、
# ブラウザの自動ダウンロード（実測699MB。#34）を回避する（仕様書11章、#35）。
SYSTEM_BROWSER_PATHS = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
    ],
}
SYSTEM_BROWSER_COMMANDS = [
    "google-chrome", "google-chrome-stable", "chromium-browser", "chromium",
    "msedge", "microsoft-edge", "microsoft-edge-stable",
]

# ログの詳細度（#52）。CLIの-q/-vで一度だけ設定するプロセスグローバルな状態。config.yamlに
# 書くべき文書内容ではなく実行時の振る舞いのため、CLIオプションのみで制御する（config.yaml側の
# 設定項目は設けない）。--config-listで複数ビルドをまとめて実行する場合もCLI全体で1つの
# 詳細度に統一される。既定は[Info]まで表示、[Warning]/[Error]/[Success]は常に表示する。
_QUIET = False
_VERBOSE = False

def _log_info(msg):
    if not _QUIET:
        print(f"[Info] {msg}")

def _log_verbose(msg):
    if _VERBOSE:
        print(f"[Verbose] {msg}")

def _user_cache_dir():
    """フォント/JRE/PlantUMLの取得物を置くアプリ専用のキャッシュディレクトリを返す。
    tool_dir（インストール場所）ではなくOS標準のユーザー領域（Windows:
    %LOCALAPPDATA%\\text-compositor\\Cache、Linux: ~/.cache/text-compositor、
    macOS: ~/Library/Caches/text-compositor）を使うことで、「クローンして直接叩く」
    でも「pipインストール」でも同じ場所にキャッシュが置ける（#50、#110）。"""
    return platformdirs.user_cache_dir("text-compositor", appauthor=False)

def find_system_browser():
    """既存のChrome/Edgeの実行ファイルパスを探す。見つからなければNone。"""
    platform_key = "darwin" if sys.platform == "darwin" else ("linux" if sys.platform.startswith("linux") else "win32")
    for path in SYSTEM_BROWSER_PATHS.get(platform_key, []):
        if os.path.exists(path):
            return path
    for cmd in SYSTEM_BROWSER_COMMANDS:
        found = shutil.which(cmd)
        if found:
            return found
    return None

def find_system_java():
    """PATH上のjavaコマンドを探し、PlantUML（最新版はJava 11+要求）を実行できるバージョンか
    確認する。見つからない、またはバージョンが古い場合はNoneを返す（#22）。
    見つかった場合はensure_temurin_jre()によるJRE取得を回避できる（2章の最小限のダウンロード）。"""
    java_path = shutil.which("java")
    if not java_path:
        return None
    try:
        result = subprocess.run([java_path, "-version"], capture_output=True, text=True, timeout=10)
    except OSError:
        return None
    # java -version は慣習的にstderrへ出力される（stdoutは空のことが多い）
    output = result.stderr or result.stdout
    m = re.search(r'version "([\d.]+)', output)
    if not m:
        return None
    parts = m.group(1).split('.')
    major = int(parts[0])
    if major == 1 and len(parts) > 1:
        # 旧来の "1.8.0_xxx" 形式（Java 8以前）。実質バージョンは2つ目の要素。
        major = int(parts[1])
    return java_path if major >= 11 else None

def find_system_d2():
    """PATH上のdコマンドを探す。PlantUMLのJava 11+のようなバージョン下限は無いため、
    存在確認のみ行う（#90）。見つかった場合はensure_d2_binary()によるダウンロードを回避できる
    （2章の最小限のダウンロード）。"""
    return shutil.which("d2")

def _diagram_cache_key(kind, tool_version, code):
    """図のキャッシュキー（#26）。入力テキストだけでなく、種別とレンダラのバージョンも
    ハッシュに含める。レンダラを更新しても同じ入力の古いSVGが使い回される事故を防ぐため。
    各要素の境界に\\0を挟み、「要素の切れ目が違うだけで連結結果が同じ」衝突を避ける。"""
    h = hashlib.sha256()
    for part in (kind, tool_version, code):
        h.update(part.encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()[:16]

def _system_d2_version(d2_bin):
    """`d2 --version`の出力（例: "v0.9.0"）を返す。取得できなければNone。"""
    try:
        result = subprocess.run([d2_bin, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None

def _typst_version_info(repo_root):
    """typstのインストール済みバージョンと、requirements.txtでピン留めされたバージョンを返す
    （#49のビルド時チェックと#37の--check-envで共用する）。requirements.txtが無い/`typst`の
    行が無い場合、pinned側はNoneになる。repo_rootは「クローンして直接叩く」場合のリポジトリ
    ルート（pipインストール後は同梱されないため、requirements.txtは見つからず自然にスキップ
    される、#111）。"""
    try:
        installed_version = importlib.metadata.version("typst")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None

    requirements_path = os.path.join(repo_root, "requirements.txt")
    pinned_version = None
    if os.path.exists(requirements_path):
        with open(requirements_path, "r", encoding="utf-8") as f:
            requirements_text = f.read()
        m = re.search(r'^typst==([\w.]+)', requirements_text, re.MULTILINE)
        if m:
            pinned_version = m.group(1)
    return installed_version, pinned_version

def check_typst_version(repo_root):
    """requirements.txtでピン留めされたtypstのバージョンと、実際にインストールされている
    バージョンが一致するかを確認する（#49）。9章の決定論的出力の前提が崩れていないかの
    簡易チェック。不一致でも警告のみでビルドは継続する（Fail-fastにはしない）。
    毎回のビルド時に自動実行される。requirements.txtが見つからない、または`typst`の行が
    無い場合は何もしない（将来pipインストール化された場合等を想定）。"""
    installed_version, pinned_version = _typst_version_info(repo_root)
    if installed_version and pinned_version and installed_version != pinned_version:
        print(f"[Warning] Installed typst version ({installed_version}) does not match "
              f"the version pinned in requirements.txt ({pinned_version}). Output may differ "
              f"from what's expected (see spec ch.9, deterministic output). "
              f"Run: pip install typst=={pinned_version}")

# 実行環境の前提を事前確認する`--check-env`（#37）。status: "OK"/"WARN"/"NG"。
# NGはこのままではビルドが失敗する状態、WARNは動作はするが何か（自動ダウンロード等）が
# 起きる状態、を表す。ビルド失敗時の原因切り分け（該当項目だけの再チェック）にも使う。
CheckResult = namedtuple("CheckResult", ["name", "status", "message"])

def _is_store_python_base(base_prefix):
    """base_prefixがMicrosoft Store版Pythonのインストール先かどうかを判定する（#138）。
    Store版Pythonは`C:\\Program Files\\WindowsApps\\<Publisher>.<Name>_...`配下にインストール
    される。venv/pipxが作る`python.exe`はCPython本体のコピーではなく別物の小さなランチャー
    （venvlauncher）で、`pyvenv.cfg`の`home`を通じて実行時にこのインストール先を参照しにいく
    ため、venv/pipx環境の内部であってもここが判定対象になる（実機検証済み）。"""
    return sys.platform == "win32" and "\\windowsapps\\" in base_prefix.lower()

def _check_isolated_env():
    """Windows + Microsoft Store版Pythonでは、ファイルシステムの透過的なリダイレクトにより、
    サブプロセス（PlantUML用のJava等）がキャッシュファイルを見失う既知の問題がある（実機で
    確認済み、#113）。venv/pipxで作った`python.exe`（venvlauncher）も、`pyvenv.cfg`の`home`を
    通じて結局Store版Pythonのインストール先を参照し続けるため、venv/pipxで隔離してもこの問題を
    回避できないことが判明した（実機検証済み、#138）。そのため「隔離環境を使っているか」では
    なく「ベースのPythonがStore版かどうか」を直接判定し、Store版なら隔離環境の有無に関わらず
    NGとする。隔離環境の使用自体は（Store版でなければ）引き続き一般的なベストプラクティスとして
    WARNで推奨する。"""
    base_prefix = sys.base_prefix
    if _is_store_python_base(base_prefix):
        return CheckResult("isolated environment", "NG",
                            f"the underlying Python ({base_prefix}) is the Microsoft Store "
                            "distribution. This tool cannot be used with it -- a venv/pipx "
                            "environment created from it does NOT avoid the problem, since its "
                            "`python.exe` still refers back to this same Store installation at "
                            "runtime (verified; see issue #138). Install Python from "
                            "https://www.python.org/downloads/ (or e.g. `winget install "
                            "Python.Python.3.12`), then recreate your venv/pipx environment "
                            "using that Python instead.")
    if sys.prefix != sys.base_prefix:
        return CheckResult("isolated environment", "OK", "running inside a venv/pipx-managed environment")
    return CheckResult("isolated environment", "WARN",
                        "not running inside an isolated environment (venv/pipx). Recommended: "
                        "`pipx install text-compositor` (end users) or a venv + "
                        "`pip install -e .` (developers)")

def _check_pyyaml(config_path):
    """PyYAML（`import yaml`、ファイル冒頭でオプショナルインポート）の導入状況を確認する。
    YAML形式のconfigを使う場合のみ必須（JSON設定なら不要）。config未指定時は既定の
    探索対象がYAMLのため、YAML想定として扱う。"""
    uses_yaml = config_path is None or config_path.lower().endswith((".yaml", ".yml"))
    if yaml is not None:
        return CheckResult("PyYAML", "OK", "installed")
    if uses_yaml:
        return CheckResult("PyYAML", "NG", "not installed but a YAML config is used. Run: pip install PyYAML==6.0.2")
    return CheckResult("PyYAML", "OK", "not installed, but not needed for a JSON config")

def _check_typst_env(repo_root):
    installed_version, pinned_version = _typst_version_info(repo_root)
    if pinned_version is None:
        return CheckResult("typst", "OK", f"{installed_version} installed (no pinned version in requirements.txt to compare)")
    if installed_version == pinned_version:
        return CheckResult("typst", "OK", f"{installed_version} (matches requirements.txt)")
    return CheckResult("typst", "WARN", f"{installed_version} installed but requirements.txt pins {pinned_version}")

def _check_font_cache():
    font_dir = os.path.join(_user_cache_dir(), "fonts", "NotoSansJP")
    missing = [name for name in NOTO_SANS_JP_FILES if not os.path.exists(os.path.join(font_dir, name))]
    if not missing:
        return CheckResult("Noto Sans JP font", "OK", f"cached under {font_dir}")
    return CheckResult("Noto Sans JP font", "WARN", "not cached yet; will be downloaded (one-time) on first build")

def _check_mermaid(mermaid_enabled, mermaid_auto_download):
    if not mermaid_enabled:
        return CheckResult("mermaid", "OK", "disabled (plugins.mermaid: false)")
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return CheckResult("mermaid", "NG", "the 'playwright' package is not installed. Run: pip install playwright==1.62.0")
    browser_path = find_system_browser()
    if browser_path:
        return CheckResult("mermaid", "OK", f"system browser found: {browser_path}")
    if mermaid_auto_download:
        return CheckResult("mermaid", "WARN",
                            "no system Chrome/Edge found; Playwright will download its own Chromium "
                            "(one-time; approx. 700MB) on first mermaid render")
    return CheckResult("mermaid", "NG",
                        "no system Chrome/Edge found and plugins.mermaid_auto_download is false. "
                        "Install Google Chrome or Microsoft Edge, or set plugins.mermaid_auto_download: true")

def _check_plantuml(plantuml_enabled, plantuml_auto_download):
    if not plantuml_enabled:
        return CheckResult("plantuml", "OK", "disabled (plugins.plantuml: false)")
    java_path = find_system_java()
    if java_path:
        return CheckResult("plantuml", "OK", f"system Java 11+ found: {java_path}")
    key = _temurin_platform_key()
    asset = TEMURIN_JRE_ASSETS.get(key)
    if asset:
        _, _, _, java_rel_parts = asset
        java_bin_path = os.path.join(_jre_cache_root(), TEMURIN_JRE_TOP_DIR, *java_rel_parts)
        if os.path.exists(java_bin_path):
            return CheckResult("plantuml", "OK", f"no local Java 11+, but Eclipse Temurin JRE already cached under {_jre_cache_root()}")
    if plantuml_auto_download:
        return CheckResult("plantuml", "WARN",
                            "no local Java 11+ found; Eclipse Temurin JRE will be downloaded "
                            "(one-time; approx. 50MB) on first plantuml render")
    return CheckResult("plantuml", "NG",
                        "no local Java 11+ found and plugins.plantuml_auto_download is false. "
                        "Install Java 11+, or set plugins.plantuml_auto_download: true")

def _check_d2(d2_enabled, d2_auto_download):
    if not d2_enabled:
        return CheckResult("d2", "OK", "disabled (plugins.d2: false)")
    d2_path = find_system_d2()
    if d2_path:
        return CheckResult("d2", "OK", f"system D2 found: {d2_path}")
    key = _temurin_platform_key()
    asset = D2_ASSETS.get(key)
    if asset:
        d2_bin_path = _d2_bin_path(_d2_cache_root(), key[0])
        if os.path.exists(d2_bin_path):
            return CheckResult("d2", "OK", f"no local D2, but the D2 CLI is already cached under {_d2_cache_root()}")
    if d2_auto_download:
        return CheckResult("d2", "WARN",
                            "no local D2 found; the D2 CLI binary will be downloaded "
                            "(one-time; approx. 13MB) on first d2 render")
    return CheckResult("d2", "NG",
                        "no local D2 found and plugins.d2_auto_download is false. "
                        "Install D2 (https://d2lang.com), or set plugins.d2_auto_download: true")

def run_env_check(repo_root, config_path):
    """`--check-env`本体。configを指定すればそのplugins設定を反映し、未指定なら全項目を
    既定値（すべて有効）でチェックする。実際のビルドは行わない。戻り値はexit code
    （NGが1件でもあれば1、無ければ0。WARNのみ・全部OKなら0）。"""
    if config_path is not None:
        _project_dir, config, _chapters = _load_project_config(config_path)
        plugins_config = config.get("plugins") or {}
    else:
        plugins_config = {}
    mermaid_enabled = bool(plugins_config.get("mermaid", True))
    mermaid_auto_download = bool(plugins_config.get("mermaid_auto_download", False))
    plantuml_enabled = bool(plugins_config.get("plantuml", True))
    plantuml_auto_download = bool(plugins_config.get("plantuml_auto_download", True))
    d2_enabled = bool(plugins_config.get("d2", True))
    d2_auto_download = bool(plugins_config.get("d2_auto_download", True))

    results = [
        _check_isolated_env(),
        _check_pyyaml(config_path),
        _check_typst_env(repo_root),
        _check_font_cache(),
        _check_mermaid(mermaid_enabled, mermaid_auto_download),
        _check_plantuml(plantuml_enabled, plantuml_auto_download),
        _check_d2(d2_enabled, d2_auto_download),
    ]
    _print_check_results(results)
    return 1 if any(r.status == "NG" for r in results) else 0

def _print_check_results(results):
    for r in results:
        print(f"[{r.status}] {r.name}: {r.message}")
    counts = {"OK": 0, "WARN": 0, "NG": 0}
    for r in results:
        counts[r.status] += 1
    print(f"\nSummary: {counts['OK']} OK, {counts['WARN']} WARN, {counts['NG']} NG")

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
                 glossary_enabled=False, line_mapping="block", marp_compat=False, variables=None):
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
        self._mermaid_page = None
        self._mermaid_browser = None
        self._mermaid_playwright = None
        self._mermaid_chrome_proc = None
        self._mermaid_profile_dir = None
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
            print("[Error] Undefined placeholder(s); define them under 'variables:' in the config, "
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
            print(f"[Error] {self.current_file} is an empty CSV file.")
            sys.exit(1)

        header, *body = rows
        cols = len(header)
        for row_no, row in enumerate(body, start=2):
            if len(row) != cols:
                print(f"[Error] {self.current_file}:{row_no}: expected {cols} columns (from the header row), "
                      f"got {len(row)}.")
                sys.exit(1)

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
            print(f"[Error] '{block_name}' block in {self.current_file} must contain exactly one "
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
            print(f"[Error] 'layout-compare' block in {self.current_file} must contain exactly two "
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
            print(f"[Error] 'layout-feature' block in {self.current_file} must contain exactly one "
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
            print(f"[Warning] PyYAML is not installed; front-matter in {self.current_file} is ignored.")
        else:
            try:
                loaded = yaml.safe_load(m.group(1))
                if isinstance(loaded, dict):
                    meta = loaded
                else:
                    print(f"[Warning] Front-matter in {self.current_file} is not a mapping; ignored.")
            except Exception as e:
                print(f"[Warning] Failed to parse front-matter in {self.current_file}: {e}")
        for key in meta:
            if key not in self.MARP_ONLY_KEYS and key not in ('title', 'subtitle', 'author', 'date',
                                                              'paper_size', 'landscape', 'font_size',
                                                              'header', 'footer', 'paginate'):
                print(f"[Warning] Unknown front-matter key '{key}' in {self.current_file}")
        if 'font_size' in meta and not self.FONT_SIZE_RE.match(str(meta['font_size'])):
            print(f"[Warning] front-matter 'font_size' in {self.current_file} should look like '16pt'; got {meta['font_size']!r}. Ignoring.")
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
                        print(f"[Error] Security: 'typst-exec' is allowed only under a 'reviewed/' directory ({self.current_file}).")
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
        
    def _warn_html(self, t):
        line_no = t.map[0] + 1 if t.map else '?'
        print(f"[Warning] HTML tag detected at {self.current_file}:{line_no} : {t.content.strip()}. HTML is not supported and will be ignored in Typst output.")

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
            print(f"[Error] Image not found: {abs_path} (referenced from {self.current_file})")
            sys.exit(1)
        root_rel_path = "/" + os.path.relpath(abs_path, self.typst_root).replace(os.sep, '/')
        return escape_string_literal(root_rel_path)

    def _ensure_mermaid_page(self):
        """Mermaidレンダリング用のヘッドレスブラウザ・ページを遅延起動する（初回のみ）。
        Node.js/npxを介さず、mermaid.min.js（実測約3.4MB）を直接ヘッドレスブラウザへ読み込ませて
        mermaid.render()を呼ぶ（仕様書11章、#35。mermaid-cli丸ごとの約396MBを回避する）。
        既存のシステムChrome/Edge（#34の検出ロジック）が見つかればPlaywrightのCDP接続で繋ぐだけで、
        ブラウザの追加ダウンロードは発生しない。見つからない場合、plugins.mermaid_auto_downloadが
        trueならPlaywright自身のChromium（実測約700MB）をその場で取得して使う。既定はfalseで、
        Fail-fastでエラー終了する（#22の設計議論。700MBは#34/#35がまさに避けた規模のため、
        既定で自動取得はしない）。"""
        if self._mermaid_page is not None:
            return self._mermaid_page

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[Error] The 'playwright' package is required for mermaid rendering (plugins.mermaid: true). "
                  "Install it with: pip install playwright==1.62.0")
            sys.exit(1)

        browser_path = find_system_browser()
        self._mermaid_playwright = sync_playwright().start()

        if browser_path:
            _log_info(f"Reusing system browser for mermaid rendering: {browser_path}")
            self._mermaid_profile_dir = tempfile.mkdtemp(prefix="cc-mermaid-")
            self._mermaid_chrome_proc, port = _launch_headless_chrome(browser_path, self._mermaid_profile_dir)
            try:
                self._mermaid_browser = self._mermaid_playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except Exception as e:
                print(f"[Error] Failed to connect to headless browser for mermaid rendering: {e}")
                diag = _check_mermaid(self.mermaid_enabled, self.mermaid_auto_download)
                if diag.status != "OK":
                    print(f"[Hint] [{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
        elif self.mermaid_auto_download:
            _log_info("No system Chrome/Edge found; plugins.mermaid_auto_download is true, so Playwright "
                      "will download its own Chromium (one-time; approx. 700MB; cached under Playwright's "
                      "browser cache, typically ~/.cache/ms-playwright)...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except (subprocess.CalledProcessError, OSError) as e:
                print(f"[Error] Failed to download Playwright's Chromium: {e}")
                sys.exit(1)
            try:
                self._mermaid_browser = self._mermaid_playwright.chromium.launch(headless=True)
            except Exception as e:
                print(f"[Error] Failed to launch the downloaded Chromium for mermaid rendering: {e}")
                sys.exit(1)
        else:
            print("[Error] No system Chrome/Edge found; required to render mermaid diagrams locally. "
                  "Install Google Chrome or Microsoft Edge, or set plugins.mermaid_auto_download: true "
                  "(downloads Playwright's own Chromium, approx. 700MB), or set plugins.mermaid: false.")
            sys.exit(1)

        mermaid_js_path = ensure_mermaid_js()

        context = self._mermaid_browser.contexts[0] if self._mermaid_browser.contexts else self._mermaid_browser.new_context()
        page = context.new_page()
        page.set_content("<div id='container'></div>")
        with open(mermaid_js_path, "r", encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        # Typstのraw SVGレンダラーは<foreignObject>内のHTMLを描画できないため、mermaid既定の
        # HTMLラベルを無効化し、通常のSVG<text>要素で出力させる（トップレベルとflowchart配下
        # 両方に指定する必要がある。PoCで確認済み）
        page.evaluate("mermaid.initialize({ startOnLoad: false, htmlLabels: false, flowchart: { htmlLabels: false } })")
        self._mermaid_page = page
        return page

    def close(self):
        """ビルド終了時に呼び出し、_ensure_mermaid_pageで起動したヘッドレスブラウザを片付ける
        （mermaidを一度も描画していなければ何もしない）。"""
        if self._mermaid_browser is not None:
            try:
                self._mermaid_browser.close()
            except Exception:
                pass
        if self._mermaid_playwright is not None:
            self._mermaid_playwright.stop()
        if self._mermaid_chrome_proc is not None:
            self._mermaid_chrome_proc.terminate()
            try:
                self._mermaid_chrome_proc.wait(timeout=5)
            except Exception:
                self._mermaid_chrome_proc.kill()
        if self._mermaid_profile_dir and os.path.exists(self._mermaid_profile_dir):
            shutil.rmtree(self._mermaid_profile_dir, ignore_errors=True)

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

    def _render_svg(self, code, width=None, height=None):
        """```svgフェンスの内容をTypstのimage呼び出しに変換する。mermaid/plantumlと異なりSVGは
        既にテキストで完結したベクター画像フォーマットのため、外部レンダリングエンジンは呼ばず、
        コードをそのままキャッシュ用の.svgファイルへ書き出すだけでよい（#91）。"""
        cache_dir = os.path.join(self.base_dir, ".text-compositor", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        digest = hashlib.sha256(code.encode('utf-8')).hexdigest()[:16]
        svg_path = os.path.join(cache_dir, f"svg_{digest}.svg")

        if not os.path.exists(svg_path):
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(code)

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
        if not self.mermaid_enabled:
            if not self._mermaid_disabled_warned:
                _log_info(f"plugins.mermaid is disabled; leaving ```mermaid fences as plain code (first seen in {self.current_file}).")
                self._mermaid_disabled_warned = True
            return f"```mermaid\n{code}```\n\n"

        # 固定済みmermaid.min.jsのSHA256をバージョンとして使う（バンドルが変われば別キーになる）
        svg_path, digest = self._diagram_cache_path("mermaid", MERMAID_JS_SHA256, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering mermaid diagram via headless browser -> {os.path.basename(svg_path)}")
            page = self._ensure_mermaid_page()
            try:
                svg = page.evaluate(
                    """async ([id, code]) => {
                        const { svg } = await mermaid.render(id, code);
                        return svg;
                    }""",
                    [f"mermaid-{digest}", code],
                )
            except Exception as e:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                print(f"[Error] mermaid rendering failed for {self.current_file}:\n{e}")
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
        else:
            _log_verbose(f"Reusing cached mermaid diagram: {os.path.basename(svg_path)}")

        # fit-image() は templates/slide.typ 側で定義されているため、image() の相対パス解決基準は
        # base_dir ではなく templates/ になってしまう。ファイルの置き場所に依存しない
        # ルート絶対パス（--root 起点の "/..." 形式）にして、どこから呼んでも解決できるようにする。
        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

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
                print("[Error] No local Java 11+ found; required to render PlantUML diagrams. "
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
        if not self.plantuml_enabled:
            if not self._plantuml_disabled_warned:
                _log_info(f"plugins.plantuml is disabled; leaving ```plantuml fences as plain code (first seen in {self.current_file}).")
                self._plantuml_disabled_warned = True
            return f"```plantuml\n{code}```\n\n"

        svg_path, _ = self._diagram_cache_path("plantuml", PLANTUML_JAR_SHA256, code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering PlantUML diagram via local Java -> {os.path.basename(svg_path)}")
            java_bin, jar_path = self._ensure_plantuml_tools()
            try:
                result = subprocess.run(
                    [java_bin, "-jar", jar_path, "-tsvg", "-pipe", "-Playout=smetana"],
                    input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
            except OSError as e:
                print(f"[Error] Failed to run PlantUML for {self.current_file}:\n{e}")
                # 隔離環境（venv/pipx）外での実行が原因の可能性が高い（#113、ファイルが
                # 存在するように見えてもサブプロセスから見えない既知の問題）ため優先して案内する。
                for diag in (_check_isolated_env(), _check_plantuml(self.plantuml_enabled, self.plantuml_auto_download)):
                    if diag.status != "OK":
                        print(f"[Hint] [{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
            if result.returncode != 0:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                print(f"[Error] PlantUML rendering failed for {self.current_file}:\n{result.stderr}")
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
        else:
            _log_verbose(f"Reusing cached PlantUML diagram: {os.path.basename(svg_path)}")

        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

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
                print("[Error] No local D2 found; required to render d2 diagrams. "
                      "Install D2 (https://d2lang.com), or set plugins.d2_auto_download: true "
                      "(downloads the D2 CLI binary, approx. 13MB), or set plugins.d2: false.")
                sys.exit(1)
            self._d2_bin = d2_bin
        return self._d2_bin

    def _render_d2(self, code, width=None, height=None):
        """```d2```ブロックをローカルのD2公式CLIバイナリでSVG化し、Typstのimage呼び出しに変換する。
        外部APIへの通信は行わない（仕様書10章・11章、#90）。`d2 - -`で標準入力から読み、標準出力へ
        SVGを書く（D2公式のstdin/stdout規約。ステータスメッセージは標準エラーへ出るため混ざらない）。"""
        if not self.d2_enabled:
            if not self._d2_disabled_warned:
                _log_info(f"plugins.d2 is disabled; leaving ```d2 fences as plain code (first seen in {self.current_file}).")
                self._d2_disabled_warned = True
            return f"```d2\n{code}```\n\n"

        svg_path, _ = self._diagram_cache_path("d2", self._d2_version(), code)

        if not os.path.exists(svg_path):
            _log_info(f"Rendering d2 diagram via local D2 -> {os.path.basename(svg_path)}")
            d2_bin = self._ensure_d2_bin()
            try:
                result = subprocess.run(
                    [d2_bin, "-", "-"],
                    input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
            except OSError as e:
                print(f"[Error] Failed to run D2 for {self.current_file}:\n{e}")
                # 隔離環境（venv/pipx）外での実行が原因の可能性が高い（#113、ファイルが
                # 存在するように見えてもサブプロセスから見えない既知の問題）ため優先して案内する。
                for diag in (_check_isolated_env(), _check_d2(self.d2_enabled, self.d2_auto_download)):
                    if diag.status != "OK":
                        print(f"[Hint] [{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
            if result.returncode != 0:
                # 仕様9章のFail-fast方針: 描画失敗時はテキストへフォールバックせず即エラー
                print(f"[Error] d2 rendering failed for {self.current_file}:\n{result.stderr}")
                sys.exit(1)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
        else:
            _log_verbose(f"Reusing cached d2 diagram: {os.path.basename(svg_path)}")

        root_rel_path = escape_string_literal("/" + os.path.relpath(svg_path, self.typst_root).replace(os.sep, '/'))
        return self._render_sized_image(root_rel_path, width, height)

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
                    print(f"[Warning] Ignoring bg/border in {self.current_file}: they apply only to a span that "
                          f"wraps the entire table cell, e.g. | [text]{{bg=\"#eeeeee\"}} |.")
                color = attrs.get('color')
                size = attrs.get('size')
                if size is not None and not self.FONT_SIZE_RE.match(str(size)):
                    line_no = t.map[0] + 1 if t.map else '?'
                    print(f"[Warning] Ignoring invalid size {size!r} in {self.current_file}:{line_no}; expected e.g. '10pt'.")
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
                line_no = t.map[0] + 1 if t.map else '?'
                print(f"[Warning] Unhandled inline token '{t.type}' at {self.current_file}:{line_no}")
            # 改行直後のテキストのみ行頭エスケープの対象にする
            at_line_start = t.type in ['softbreak', 'hardbreak']
        if html_span_depth > 0:
            # 壊れたTypstコード（閉じ角括弧の不足）を生成しないよう自動で閉じ、書き忘れに気付けるよう警告する
            print(f"[Warning] Unclosed <span style=\"color:...\"> in {self.current_file}; closing it automatically.")
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
                print(f"[Warning] Ignoring invalid border {border!r} in {self.current_file}; "
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

def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def default_config():
    return {
        "document": {
            "title": "System_Specification",
            "subtitle": "自動生成ドキュメント",
            "author": "開発チーム",
            "date": "auto",
            "diagnostics": {
                "line_mapping": "block"
            }
        },
        "output": {
            "filename": "System_Specification.pdf",
            "dir": "outputs"
        },
        "template": {
            "path": "template"
        },
        "inputs": {
            "dir": "inputs",
            "files": None
        }
    }

def resolve_template_path(template_path_value, tool_dir, project_dir):
    """template.pathを「名前」と「パス」で区別して解決する（5章、#23）。
    拡張子(.typ)を含まない値（例: template, slide）は「名前」とみなし、ツール同梱の
    tool_dir/templates/<name>.typ から解決する。.typで終わる値は「パス」とみなし、
    他の相対パスと同じ規則（5章）でproject_dir基準で解決し、プロジェクト独自の
    テンプレートを持ち込めるようにする（サブディレクトリの有無を問わない）。
    絶対パスはos.path.joinの挙動によりそのまま使われる。"""
    if template_path_value.endswith('.typ'):
        return os.path.normpath(os.path.join(project_dir, template_path_value))
    return os.path.join(tool_dir, "templates", template_path_value + ".typ")

# CJKフォント(Noto Sans JP)の取得元。バイナリはリポジトリに同梱せず、初回ビルド時にのみ
# ここから取得しユーザーキャッシュディレクトリ（#110）に保存する（2章の「最小限のダウンロード」方針）。
# 版とSHA256を固定し、同梱バイナリと違って取得結果が変わらないようにする（9章の決定論的出力）。
NOTO_SANS_JP_RELEASE_URL = "https://github.com/notofonts/noto-cjk/releases/download/Sans2.004/16_NotoSansJP.zip"
NOTO_SANS_JP_FILES = {
    "NotoSansJP-Regular.otf": "dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073",
    "NotoSansJP-Bold.otf": "1b0edfb500b73a4fa8a4fcaae1bbbd403994e08e73e3e0da37e70d3853f42c5f",
}

def ensure_fonts():
    """Noto Sans JP（Regular/Bold）がユーザーキャッシュディレクトリの fonts/NotoSansJP/ に
    なければダウンロードする。2回目以降のビルドはキャッシュを使い、ネットワークアクセスなしで
    完結する（#110）。"""
    font_dir = os.path.join(_user_cache_dir(), "fonts", "NotoSansJP")
    os.makedirs(font_dir, exist_ok=True)

    missing = [name for name in NOTO_SANS_JP_FILES if not os.path.exists(os.path.join(font_dir, name))]
    if not missing:
        return font_dir

    _log_info(f"Downloading Noto Sans JP font (one-time; cached under {font_dir})...")
    zip_path = os.path.join(font_dir, "_download.zip")
    try:
        urllib.request.urlretrieve(NOTO_SANS_JP_RELEASE_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            for name in missing:
                data = zf.read(name)
                digest = hashlib.sha256(data).hexdigest()
                if digest != NOTO_SANS_JP_FILES[name]:
                    print(f"[Error] Checksum mismatch for {name}: expected {NOTO_SANS_JP_FILES[name]}, got {digest}")
                    sys.exit(1)
                with open(os.path.join(font_dir, name), "wb") as f:
                    f.write(data)
    except zipfile.BadZipFile as e:
        print(f"[Error] Failed to download fonts (bad zip): {e}")
        sys.exit(1)
    except OSError as e:
        print(f"[Error] Failed to download fonts: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    return font_dir

# Mermaid公式配布の単一バンドルJS（UMD形式、全図種込み）。mermaid-cli丸ごと（npm依存ツリー約396MB）
# ではなくこのファイル単体（実測約3.4MB）だけを取得し、Playwright経由でヘッドレスブラウザに
# 読み込ませてmermaid.render()を直接呼び出す（仕様書11章、#35）。バージョン・SHA256を固定し、
# Noto Sans JPと同様に決定論的な取得結果にする（9章）。
MERMAID_JS_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.16.1/dist/mermaid.min.js"
MERMAID_JS_SHA256 = "18327bef70d96fb505fe7287d9f6a7362ebf07ff6576ddfaffb1a06f3e1a2954"

def ensure_mermaid_js():
    """mermaid.min.jsがユーザーキャッシュディレクトリの mermaid/ になければダウンロードする。
    2回目以降のビルドはキャッシュを使い、ネットワークアクセスなしで完結する（#110）。"""
    cache_dir = os.path.join(_user_cache_dir(), "mermaid")
    os.makedirs(cache_dir, exist_ok=True)
    js_path = os.path.join(cache_dir, "mermaid.min.js")
    if os.path.exists(js_path):
        return js_path

    _log_info(f"Downloading mermaid.min.js (one-time; cached under {cache_dir})...")
    try:
        urllib.request.urlretrieve(MERMAID_JS_URL, js_path)
    except OSError as e:
        print(f"[Error] Failed to download mermaid.min.js: {e}")
        sys.exit(1)

    with open(js_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != MERMAID_JS_SHA256:
        os.remove(js_path)
        print(f"[Error] Checksum mismatch for mermaid.min.js: expected {MERMAID_JS_SHA256}, got {digest}")
        sys.exit(1)

    return js_path

# ローカルにJava 11+が見つからない場合のみ取得するEclipse Temurin JRE（Adoptium配布、
# GPLv2+Classpath Exception。OpenJDK本体と同じライセンス系統で安心度が高い）。CI
# （GitHub Actions ubuntu-latest等）はJavaが標準搭載されているためこの取得は発生しない（#22）。
# バージョン・プラットフォーム別にURL・SHA256を固定し、決定論的な取得結果にする（9章）。
TEMURIN_JRE_RELEASE = "jdk-21.0.12+8"
TEMURIN_JRE_BASE_URL = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12%2B8/"
TEMURIN_JRE_TOP_DIR = "jdk-21.0.12+8-jre"
# キー: (sys.platform判定用キー, platform.machine()正規化キー)。
# 値: (アーカイブファイル名, SHA256, アーカイブ形式, TEMURIN_JRE_TOP_DIR配下のjava実行ファイルへの相対パス)
TEMURIN_JRE_ASSETS = {
    ("win32", "x86_64"): ("OpenJDK21U-jre_x64_windows_hotspot_21.0.12_8.zip",
                           "b8aa18fef5edb69bee8618f99677d66d0873d22cb40d974c15ac9ffcdecf73ba",
                           "zip", ("bin", "java.exe")),
    ("win32", "aarch64"): ("OpenJDK21U-jre_aarch64_windows_hotspot_21.0.12_8.zip",
                            "a50ed83b6a88d3127d406713f5057d78f845c3412d59e201dac6db37714af85c",
                            "zip", ("bin", "java.exe")),
    ("linux", "x86_64"): ("OpenJDK21U-jre_x64_linux_hotspot_21.0.12_8.tar.gz",
                           "8a379a67c91a3ae61ffb33d46e0a40c7ba35e70713c4db31cfca30492f792eff",
                           "tar.gz", ("bin", "java")),
    ("linux", "aarch64"): ("OpenJDK21U-jre_aarch64_linux_hotspot_21.0.12_8.tar.gz",
                            "5f9c96b656827b9d14ebeda7739e25be554fa6d25669b03847c1df6e869c0679",
                            "tar.gz", ("bin", "java")),
    ("darwin", "x86_64"): ("OpenJDK21U-jre_x64_mac_hotspot_21.0.12_8.tar.gz",
                            "539706197baea8189c9a677aea5bf44671b74a71baa42dde436e312f2158fa3a",
                            "tar.gz", ("Contents", "Home", "bin", "java")),
    ("darwin", "aarch64"): ("OpenJDK21U-jre_aarch64_mac_hotspot_21.0.12_8.tar.gz",
                             "36bb71d6fa5184e12a6483e7662783c2cbd383f5dca8034140f0a84dd5aa797d",
                             "tar.gz", ("Contents", "Home", "bin", "java")),
}

def _temurin_platform_key():
    if sys.platform == "darwin":
        os_key = "darwin"
    elif sys.platform.startswith("linux"):
        os_key = "linux"
    else:
        os_key = "win32"
    machine = platform.machine().lower()
    arch_key = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return os_key, arch_key

def _jre_cache_root():
    return os.path.join(_user_cache_dir(), "jre")

def ensure_temurin_jre():
    """ユーザーキャッシュディレクトリの jre/ にEclipse Temurin JREが無ければダウンロード・
    展開する。java実行ファイルの絶対パスを返す。2回目以降のビルドはキャッシュを使い、
    ネットワークアクセスなしで完結する（find_system_java()でシステムJavaが見つからなかった
    場合のみ呼ばれる、#22、#110）。"""
    key = _temurin_platform_key()
    asset = TEMURIN_JRE_ASSETS.get(key)
    if asset is None:
        print(f"[Error] No Eclipse Temurin JRE build available for this platform ({key[0]}/{key[1]}). "
              "Install Java 11+ manually and ensure it is on PATH, or set plugins.plantuml: false.")
        sys.exit(1)
    filename, sha256, archive_type, java_rel_parts = asset

    cache_root = _jre_cache_root()
    java_bin_path = os.path.join(cache_root, TEMURIN_JRE_TOP_DIR, *java_rel_parts)
    if os.path.exists(java_bin_path):
        return java_bin_path

    os.makedirs(cache_root, exist_ok=True)
    archive_path = os.path.join(cache_root, filename)
    _log_info(f"No local Java 11+ found; downloading Eclipse Temurin JRE {TEMURIN_JRE_RELEASE} "
              f"(one-time; cached under {cache_root})...")
    try:
        urllib.request.urlretrieve(TEMURIN_JRE_BASE_URL + filename, archive_path)
    except OSError as e:
        print(f"[Error] Failed to download Eclipse Temurin JRE: {e}")
        sys.exit(1)

    with open(archive_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        os.remove(archive_path)
        print(f"[Error] Checksum mismatch for {filename}: expected {sha256}, got {digest}")
        sys.exit(1)

    if archive_type == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(cache_root)
    else:
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(cache_root)
    os.remove(archive_path)

    if not os.path.exists(java_bin_path):
        print(f"[Error] Eclipse Temurin JRE extraction did not produce the expected binary: {java_bin_path}")
        sys.exit(1)
    if key[0] != "win32":
        os.chmod(java_bin_path, 0o755)

    return java_bin_path

# PlantUML本体（MIT版。GPL/LGPL/Apache/EPL版と機能差はDITAA等ごく一部のみで、UML図生成は
# 100%対応。#22の調査でmit-light版はstdlib/クラウドアイコン素材と絵文字データのみが欠けることが
# 分かったが、Markdown原稿（GitHub管理・AI生成）には絵文字が含まれ得るため、フル機能のmit版を
# 採用する）。レイアウトエンジンはSmetana（純Java実装）を明示指定し、Graphviz(dot)実行ファイルへの
# 依存を避ける（-Playout=smetana）。バージョン・SHA256を固定し、決定論的な取得結果にする（9章）。
PLANTUML_JAR_URL = "https://github.com/plantuml/plantuml/releases/download/v1.2026.6/plantuml-mit-1.2026.6.jar"
PLANTUML_JAR_SHA256 = "5814ab31dd569f3772747c3a0c1b52fd3bf2996b8132c62d17006d758c2d3fe3"

def ensure_plantuml_jar():
    """plantuml.jarがユーザーキャッシュディレクトリの plantuml/ になければダウンロードする。
    2回目以降のビルドはキャッシュを使い、ネットワークアクセスなしで完結する（#110）。"""
    cache_dir = os.path.join(_user_cache_dir(), "plantuml")
    os.makedirs(cache_dir, exist_ok=True)
    jar_path = os.path.join(cache_dir, "plantuml-mit.jar")
    if os.path.exists(jar_path):
        return jar_path

    _log_info(f"Downloading plantuml.jar (one-time; cached under {cache_dir})...")
    try:
        urllib.request.urlretrieve(PLANTUML_JAR_URL, jar_path)
    except OSError as e:
        print(f"[Error] Failed to download plantuml.jar: {e}")
        sys.exit(1)

    with open(jar_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != PLANTUML_JAR_SHA256:
        os.remove(jar_path)
        print(f"[Error] Checksum mismatch for plantuml.jar: expected {PLANTUML_JAR_SHA256}, got {digest}")
        sys.exit(1)

    return jar_path

# D2公式CLIバイナリ（Go製、単一実行ファイル、外部ランタイム不要）。mermaid/plantumlと同じ設計方針
# （#90）で、GitHub Releasesから取得しSHA256を固定した上でtool_dir配下にキャッシュする。
# バージョン・SHA256を固定し、決定論的な取得結果にする（9章）。SHA256は公式リリースの
# SHA256SUMSアセットから取得した値（https://github.com/d2lang/d2/releases/tag/v0.9.0）。
D2_RELEASE = "v0.9.0"
D2_BASE_URL = f"https://github.com/d2lang/d2/releases/download/{D2_RELEASE}/"
D2_TOP_DIR = f"d2-{D2_RELEASE}"
D2_ASSETS = {
    ("win32", "x86_64"): ("d2-v0.9.0-windows-amd64.tar.gz",
                           "5f63b643de8f5a6dfb922d172e1b5496e4caf47497c33c4427cf1127f28c340f"),
    ("win32", "aarch64"): ("d2-v0.9.0-windows-arm64.tar.gz",
                           "dd05cab459410c287d7ca3eb9cf78145a071742ee8e1b81a0122f84f471883e1"),
    ("linux", "x86_64"): ("d2-v0.9.0-linux-amd64.tar.gz",
                          "5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9"),
    ("linux", "aarch64"): ("d2-v0.9.0-linux-arm64.tar.gz",
                           "ac2c028697199479acb321db1e3d68caee9f2ba492ed73caa3cd13f3829bf913"),
    ("darwin", "x86_64"): ("d2-v0.9.0-macos-amd64.tar.gz",
                           "cad39576a480d6bb02ea142fef1726647914b0d2da51ccc9b30b660a2b1babf0"),
    ("darwin", "aarch64"): ("d2-v0.9.0-macos-arm64.tar.gz",
                            "eaf6c0c143e56dd9fa97bfb6df25ea9c1ebce40245f056a0768cf1a6c15d3064"),
}

def _d2_cache_root():
    return os.path.join(_user_cache_dir(), "d2")

def _d2_bin_path(cache_root, os_key):
    exe = "d2.exe" if os_key == "win32" else "d2"
    return os.path.join(cache_root, D2_TOP_DIR, "bin", exe)

def ensure_d2_binary():
    """ユーザーキャッシュディレクトリの d2/ にD2公式CLIバイナリが無ければダウンロード・展開する。
    d2実行ファイルの絶対パスを返す。2回目以降のビルドはキャッシュを使い、ネットワークアクセス
    なしで完結する（find_system_d2()でシステムのdコマンドが見つからなかった場合のみ呼ばれる、
    #90）。プラットフォーム判定は_temurin_platform_key()を共用する（OS/CPUアーキテクチャの
    検出ロジックはD2固有の事情が無く、Temurin JRE用のものと同一のため）。"""
    key = _temurin_platform_key()
    asset = D2_ASSETS.get(key)
    if asset is None:
        print(f"[Error] No D2 CLI build available for this platform ({key[0]}/{key[1]}). "
              "Install D2 manually (https://d2lang.com) and ensure it is on PATH, or set plugins.d2: false.")
        sys.exit(1)
    filename, sha256 = asset

    cache_root = _d2_cache_root()
    d2_bin_path = _d2_bin_path(cache_root, key[0])
    if os.path.exists(d2_bin_path):
        return d2_bin_path

    os.makedirs(cache_root, exist_ok=True)
    archive_path = os.path.join(cache_root, filename)
    _log_info(f"No local D2 found; downloading D2 CLI {D2_RELEASE} (one-time; cached under {cache_root})...")
    try:
        urllib.request.urlretrieve(D2_BASE_URL + filename, archive_path)
    except OSError as e:
        print(f"[Error] Failed to download D2 CLI: {e}")
        sys.exit(1)

    with open(archive_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        os.remove(archive_path)
        print(f"[Error] Checksum mismatch for {filename}: expected {sha256}, got {digest}")
        sys.exit(1)

    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(cache_root)
    os.remove(archive_path)

    if not os.path.exists(d2_bin_path):
        print(f"[Error] D2 CLI extraction did not produce the expected binary: {d2_bin_path}")
        sys.exit(1)
    if key[0] != "win32":
        os.chmod(d2_bin_path, 0o755)

    return d2_bin_path

def _launch_headless_chrome(browser_path, user_data_dir):
    """browser_pathをリモートデバッグ有効・ヘッドレスで起動し、(Popen, ポート番号)を返す。
    ポートは0（OSに自動割当させる）を指定し、Chromeがuser_data_dir/DevToolsActivePortに
    書き出す実際のポートを読み取る（固定ポートによる競合を避けるため）。"""
    os.makedirs(user_data_dir, exist_ok=True)
    port_file = os.path.join(user_data_dir, "DevToolsActivePort")
    if os.path.exists(port_file):
        os.remove(port_file)

    proc = subprocess.Popen(
        [browser_path, "--remote-debugging-port=0", "--headless=new", "--disable-gpu",
         "--no-first-run", f"--user-data-dir={user_data_dir}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(80):
        if os.path.exists(port_file):
            with open(port_file, "r", encoding="utf-8") as f:
                port = int(f.readline().strip())
            return proc, port
        if proc.poll() is not None:
            break
        time.sleep(0.25)

    proc.terminate()
    print("[Error] Headless browser did not become ready in time (needed for mermaid rendering).")
    sys.exit(1)

def load_config_file(config_path):
    """指定された1ファイル(yaml/json)から設定を読み込む。存在しなければFail-fast。"""
    config = default_config()
    if not os.path.exists(config_path):
        print(f"[Error] Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        if config_path.endswith(('.yaml', '.yml')):
            if yaml is None:
                print("[Error] PyYAML is not installed; cannot read a .yaml config file.")
                sys.exit(1)
            loaded = yaml.safe_load(f) or {}
        else:
            loaded = json.load(f) or {}
    deep_update(config, loaded)
    return config

def _resolve_variables(config):
    """configの`variables:`（#72）から{{KEY}}の置換表{KEY: 文字列}を作る。キーが無ければNone
    （置換機構を無効にする）。値は次のいずれか。
      * スカラー（文字列・数値・真偽値）: そのまま文字列化して使う。
      * {env: 環境変数名, default: 既定値}: ビルド時の環境変数から取得する。未設定でdefaultも無ければ
        エラー終了する（CI等で値の渡し忘れに気づけるように）。
    コマンド実行による取得は設けない。configの記述だけで任意コマンドが動くのは安全性の面で
    望ましくなく、出力を環境変数に入れて渡せば同じことができるため。
    値は1行に限る。改行を許すと、行番号による診断（#27のsrcmap）が元のMarkdownの行とずれる。"""
    raw = config.get("variables")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        print("[Error] 'variables' must be a mapping of KEY: value.")
        sys.exit(1)
    variables = {}
    for key, spec in raw.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(key)):
            print(f"[Error] variables.{key}: the key must consist of letters, digits and '_' "
                  f"(and not start with a digit).")
            sys.exit(1)
        if isinstance(spec, dict):
            unknown = set(spec) - {"env", "default"}
            if "env" not in spec or unknown:
                print(f"[Error] variables.{key}: a mapping value must have 'env' (and optionally 'default'); "
                      f"got keys {sorted(map(str, spec))}.")
                sys.exit(1)
            value = os.environ.get(str(spec["env"]))
            if value is None:
                if "default" not in spec:
                    print(f"[Error] variables.{key}: environment variable {spec['env']} is not set "
                          f"and no 'default' is given.")
                    sys.exit(1)
                value = spec["default"]
        elif isinstance(spec, (list, tuple)):
            print(f"[Error] variables.{key}: a list is not supported; use a scalar or {{env: NAME}}.")
            sys.exit(1)
        else:
            value = spec
        value = "" if value is None else str(value)
        if "\n" in value or "\r" in value:
            print(f"[Error] variables.{key}: the value must be a single line.")
            sys.exit(1)
        variables[str(key)] = value
    return variables

def escape_string_literal(text):
    return str(text).replace('\\', '\\\\').replace('"', '\\"')

def _typst_str_or_none(value):
    """PythonのNone/文字列をTypstの`none`/文字列リテラルへ変換する（#42のheader/footer等）。"""
    if value is None:
        return "none"
    return f'"{escape_string_literal(str(value))}"'

def _resolve_project_image_path(path, base_dir, typst_root, label):
    """document.background/chapters[].background（#55）、document.logo/chapters[].logo（#54）の
    相対パスを、project_dir基準からtypst_root起点のルート絶対パスへ変換する（5章: config.yaml内の
    相対パスはproject_dir基準。Markdown内画像の_resolve_asset()とは基準ディレクトリが異なる）。
    仕様9章のFail-fast方針に従い、画像欠損は即エラーとする。"""
    if not path:
        return None
    abs_path = os.path.normpath(os.path.join(base_dir, path))
    if not os.path.exists(abs_path):
        print(f"[Error] {label} image not found: {abs_path}")
        sys.exit(1)
    return "/" + os.path.relpath(abs_path, typst_root).replace(os.sep, '/')

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

def extract_md_string(data, key):
    """YAMLからテキストを抽出。リスト形式の場合は改行で結合して単一文字列にする"""
    val = data.get(key, "")
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)

def find_config_in_cwd():
    """--config省略時、カレントディレクトリ直下の推奨ファイル名を探す（ツール本体ディレクトリは見ない）。"""
    for name in ("text-compositor.config.yaml", "text-compositor.config.json"):
        path = os.path.join(os.getcwd(), name)
        if os.path.exists(path):
            return path
    return None

def parse_args():
    parser = argparse.ArgumentParser(description="Markdown -> Typst -> PDF ドキュメントビルダー")
    parser.add_argument("--config", help="設定ファイル(yaml/json)へのパス。省略時はカレントディレクトリの text-compositor.config.yaml/.json を探す。")
    parser.add_argument("--config-list", help="ビルド対象のconfigファイルパスを1行1件で列挙したテキストファイル。空行と'#'で始まる行は無視される。--configとは同時指定できない。相対パスはこのファイル自身の置き場所が基準。")
    parser.add_argument("--check-env", action="store_true",
                         help="ビルドを実行せず、実行環境の前提（依存パッケージ・Typstバージョン・"
                              "フォントキャッシュ・mermaid/plantumlに必要なツール）を確認して終了する（#37）。"
                              "--configと併用するとそのplugins設定を反映する。NGが1件でもあればexit code 1。")
    # 実行時の振る舞い系オプション（#52）。文書の内容（出力先・用紙設定等）に関わる上書きオプションは
    # 「config.yamlが単一の正」という方針とやや相性が悪いため見送り、ログレベルと中間ファイルの
    # 扱いのみをCLIオプション化した（Issue本文で見送りが推奨されていた）。
    parser.add_argument("-q", "--quiet", action="store_true",
                         help="[Info]レベルのログを抑制する（[Warning]/[Error]/[Success]は常に表示）。-vとは同時指定できない。")
    parser.add_argument("-v", "--verbose", action="store_true",
                         help="[Info]に加え、処理中の章やキャッシュ再利用状況など[Verbose]レベルの詳細なログも表示する。-qとは同時指定できない。")
    parser.add_argument("--keep-temp", action="store_true",
                         help="ビルド成功時も中間ファイル（temp_build.typ等、.text-compositor/配下）を削除せずに残す。"
                              "既定ではビルド失敗時のみ残る（デバッグ用）。")
    parser.add_argument("--watch", action="store_true",
                         help="初回ビルド後も終了せず、config・入力ファイル・テンプレートの保存を検知して自動で再ビルドする（#30）。"
                              "ビルドが失敗しても終了せず、次の保存を待つ。Ctrl+Cで終了する。--check-envとは同時指定できない。")
    parser.add_argument("--if-changed", action="store_true",
                         help="出力PDFが、config・入力ファイル・テンプレート・ツール自身のいずれよりも新しい場合はビルドをスキップする"
                              "（makeと同様の更新日時による判定、#151）。既定は従来どおり常に再生成する。"
                              "--clean/--watchとは同時指定できない。")
    parser.add_argument("--clean", action="store_true",
                         help="ビルドせず、生成物を削除して終了する（#151）。削除対象は出力PDFと、"
                              ".text-compositor/配下の中間ファイル（temp_build.typ・_template.typ・_common.typ）。"
                              "図表キャッシュ（.text-compositor/cache/）は残す（--clean-cacheで削除）。")
    parser.add_argument("--clean-cache", action="store_true",
                         help="--cleanの削除対象に、図表キャッシュ（.text-compositor/cache/）も加える。"
                              "単独で指定しても--cleanを含む。再生成コストが高いため別オプションにしている。")
    args = parser.parse_args()
    if args.clean_cache:
        args.clean = True
    if args.quiet and args.verbose:
        parser.error("-q/--quiet と -v/--verbose は同時に指定できません。")
    if args.config and args.config_list:
        parser.error("--config と --config-list は同時に指定できません。")
    if args.check_env and args.config_list:
        parser.error("--check-env と --config-list は同時に指定できません。")
    if args.check_env and args.watch:
        parser.error("--check-env と --watch は同時に指定できません。")
    if args.clean and (args.check_env or args.watch or args.if_changed):
        parser.error("--clean/--clean-cache は --check-env・--watch・--if-changed と同時に指定できません。")
    if args.if_changed and args.watch:
        parser.error("--if-changed と --watch は同時に指定できません。")
    return args

def _read_config_list(list_path):
    """--config-listのファイルを読み、configファイルパスのリストを返す（コメント行・空行を除く）。"""
    list_path = os.path.abspath(list_path)
    base_dir = os.path.dirname(list_path)
    paths = []
    with open(list_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            paths.append(line if os.path.isabs(line) else os.path.join(base_dir, line))
    return paths

def _load_project_config(config_path):
    """configパス（Noneならカレントディレクトリから探索）から設定ファイルを読み込み、(project_dir, config, chapters)を返す。"""
    if config_path:
        config_path = os.path.abspath(config_path)
    else:
        config_path = find_config_in_cwd()
        if not config_path:
            print("[Error] --config not specified, and no text-compositor.config.yaml/.json found in the current directory.")
            sys.exit(1)
    project_dir = os.path.dirname(config_path)
    config = load_config_file(config_path)

    chapters = config.get("chapters", [])
    # 【修正】章が空の場合は正常終了せずFail-fastでエラー終了させる
    if not chapters:
        print("[Error] No chapters configured in config.yaml. Aborting.")
        sys.exit(1)
    return project_dir, config, chapters

def _resolve_project_dirs(project_dir, config):
    """出力先・入力元・作業ディレクトリと、それらを跨ぐ--root（typst_root）を解決する。"""
    outputs_dir = os.path.normpath(os.path.join(project_dir, config["output"]["dir"]))
    os.makedirs(outputs_dir, exist_ok=True)
    # 【修正】ハードコードをやめ config の inputs.dir を実際に使用する
    inputs_dir = os.path.normpath(os.path.join(project_dir, config.get("inputs", {}).get("dir") or "inputs"))

    work_dir = os.path.join(project_dir, ".text-compositor")
    os.makedirs(work_dir, exist_ok=True)

    # project_dir・inputs_dir・outputs_dir・work_dirすべてを跨いでtypstから参照できるよう、
    # それら全ての共通の親ディレクトリを --root にする（tool_dirは含めない）
    typst_root = os.path.commonpath([project_dir, inputs_dir, outputs_dir, work_dir])
    return outputs_dir, inputs_dir, work_dir, typst_root

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
        print(f"[Error] Template not found: {template_abs_path}")
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
        print("[Error] document.revision_history must be a list of mappings "
              "(version / date / description / author).")
        sys.exit(1)
    entries = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            print(f"[Error] document.revision_history[{i}] must be a mapping "
                  f"(version / date / description / author), got {item!r}.")
            sys.exit(1)
        unknown = [k for k in item if k not in REVISION_HISTORY_KEYS]
        if unknown:
            print(f"[Error] document.revision_history[{i}]: unknown key(s) {unknown} "
                  f"(allowed: {', '.join(REVISION_HISTORY_KEYS)}).")
            sys.exit(1)
        entry = {k: ("" if item.get(k) is None else str(item[k])) for k in REVISION_HISTORY_KEYS}
        if not any(v.strip() for v in entry.values()):
            print(f"[Error] document.revision_history[{i}] is empty.")
            sys.exit(1)
        entries.append(entry)
    return entries or None

def _typst_multiline_literal(text):
    """複数行の文字列を、改行を`\\n`とした1行のTypst文字列リテラルにする。値はデータとして埋め込むため、
    `#`や`*`等はMarkup記法として解釈されない。テンプレート側が`\\n`をlinebreak()等へ変換する。"""
    return '"' + escape_string_literal(text.replace('\r\n', '\n')).replace('\r', '').replace('\n', '\\n') + '"'

def _resolve_abstract(doc_config):
    """document.abstract（#64）を検証し、文字列（前後の空白を除く）を返す。未指定・空文字ならNone
    （概要を出さない）。文字列以外（リスト等）は、意図しない値が黙って文字列化されるのを避けるためエラーにする。"""
    raw = doc_config.get("abstract")
    if raw is None:
        return None
    if not isinstance(raw, str):
        print(f"[Error] document.abstract must be a string (got {type(raw).__name__}).")
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
        print(f"[Error] Invalid document.cover: {cover_mode!r} (expected template / replace / markdown / none)")
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

def _parse_chapter_entry(ch):
    """chaptersの1エントリを解析し、(ファイル/ディレクトリ名, 章固有設定のdict, 種別)を返す。
    種別は"file"（Markdown等の通常章）または"aggregate"（YAML/JSON集約）。"""
    if isinstance(ch, str):
        return ch, {}, "file"
    if not isinstance(ch, dict):
        print(f"[Error] Invalid chapter entry (must be a string or a mapping): {ch!r}")
        sys.exit(1)
    if "aggregate" in ch:
        ch_file = ch["aggregate"]
        ch_type = "aggregate"
    else:
        ch_file = ch.get("file")
        ch_type = "file"
    if not ch_file:
        print(f"[Error] Invalid chapter entry (no 'file' or 'aggregate' key): {ch!r}")
        sys.exit(1)
    return ch_file, ch, ch_type

# 章に効くページ設定・スタイルの「既定値」一式（#68）。最上位ではdocument.*の実効値、section配下では
# sectionの指定でそれを上書きしたもの。各章の解決は「章の指定 ＞ front-matter ＞ この既定値」の順。
ChapterDefaults = namedtuple("ChapterDefaults", [
    "landscape", "paper", "header", "footer", "paginate", "background", "logo", "table_header", "heading_offset"])

def _parse_heading_offset(value, where):
    """heading_offset（見出しレベルをずらす段数）を検証して返す。0以上の整数のみ。上限5は、
    MarkdownのH1〜H6を最大でH11相当まで下げても意味を成さないため、明らかな誤記を弾く目的。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        print(f"[Error] {where}: heading_offset must be an integer from 0 to 5 (got {value!r}).")
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
                print(f"[Error] Invalid section (the heading must be a non-empty string): {ch!r}")
                sys.exit(1)
            if "file" in ch or "aggregate" in ch:
                print(f"[Error] section {title!r}: 'section' cannot be combined with 'file'/'aggregate'; "
                      f"list the files under 'chapters:'.")
                sys.exit(1)
            children = ch.get("chapters")
            if not isinstance(children, list) or not children:
                print(f"[Error] section {title!r}: 'chapters' must be a non-empty list.")
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
                    print(f"[Error] section {title!r}: nested sections are not supported "
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

        typst_code += '#table(\n  columns: (auto, auto, auto, 1fr, 1fr),\n'
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
                    print(f"[Warning] Failed to parse {tc_file}: {e}")
                    continue

            tc_id = renderer.escape_typst(str(tc_data.get("id", "")))
            tc_title = renderer.escape_typst(str(tc_data.get("title", "")))
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
        print(f"[Error] Aggregate directory not found: {agg_path}")
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
        print(f"[Error] Chapter file not found: {md_path}")
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

def _resolve_line_mapping(config):
    """document.diagnostics.line_mapping: "block"（既定。#27）。Typstコンパイルエラーの行番号を
    元のMarkdownの行番号へ逆引きする精度を読み取る。"fine"（リスト項目・テーブル行単位）は
    未実装の将来課題のため、指定されても現時点では"block"にフォールバックする。
    document.diagnosticsキー自体は存在するが値が空（YAMLで`diagnostics:`とだけ書いてNoneに
    なる場合）でも例外を出さないよう、`or {}`でNoneをdictに読み替える。"""
    line_mapping = (config.get("document", {}).get("diagnostics") or {}).get("line_mapping", "block")
    if line_mapping not in ("off", "block"):
        print(f"[Warning] document.diagnostics.line_mapping: {line_mapping!r} is not supported yet; falling back to 'block'.")
        line_mapping = "block"
    return line_mapping

# TypstRenderer._emit_srcmapが生成コードへ挿し込む目印行（`// @srcmap {mdファイル}:{md行番号}`）
# を検出する正規表現（#27）。ファイルパス自体にコロンを含みうる（Windowsの絶対パス`C:\...`）ため、
# 末尾の数字グループのみを行番号として貪欲マッチさせ、残り全体をファイルパスとして扱う。
SRCMAP_LINE_RE = re.compile(re.escape(TypstRenderer.SRCMAP_PREFIX) + r'(.+):(\d+)$', re.MULTILINE)
# typst_lib.TypstErrorのメッセージ（codespan_reportingが整形する`┌─ temp_build.typ:12:5`形式）
# から、コンパイル対象ファイル内の行:列を検出する正規表現。
TYPST_ERROR_LOC_RE = re.compile(r'temp_build\.typ:(\d+):\d+')

def _build_srcmap(typst_code):
    """typst_code全体から`// @srcmap`の目印行を集め、[(typstコード上の行番号, mdファイル, md行番号), ...]
    をtypst行番号の昇順で返す（#27）。line_mapping: "off"（既定はblock）で目印が無い場合は空リスト。"""
    return [
        (typst_code.count('\n', 0, m.start()) + 1, m.group(1), int(m.group(2)))
        for m in SRCMAP_LINE_RE.finditer(typst_code)
    ]

def _resolve_srcmap(src_map, typst_line):
    """typst_line以前にある直近の目印から、対応する元のMarkdownの(ファイル, 行番号)を引く（#27）。
    目印より前（テンプレートのpreambleなど）の行はNoneを返す。"""
    linenos = [s[0] for s in src_map]
    idx = bisect.bisect_right(linenos, typst_line) - 1
    return (src_map[idx][1], src_map[idx][2]) if idx >= 0 else None

def _annotate_typst_error(error_text, src_map):
    """Typstのコンパイルエラーメッセージ中の`temp_build.typ:行:列`を#27のsrc_mapで元のMarkdownの
    (ファイル, 行番号)へ逆引きし、ヒントとして追記する。src_mapが空（line_mapping: off、または
    該当行が目印より前）の場合は元のメッセージのまま返す。"""
    hints = []
    seen = set()
    for m in TYPST_ERROR_LOC_RE.finditer(error_text):
        typst_line = int(m.group(1))
        if typst_line in seen:
            continue
        seen.add(typst_line)
        resolved = _resolve_srcmap(src_map, typst_line)
        if resolved:
            md_file, md_line = resolved
            hints.append(f"[Hint] temp_build.typ:{typst_line} corresponds to around {md_file}:{md_line}")
    return error_text + "\n" + "\n".join(hints) if hints else error_text

def _compile_and_cleanup(typst_code, work_dir, outputs_dir, config, typst_root, font_dir, template_copy_path, repo_root,
                          keep_temp=False):
    """temp_build.typへ書き出してtypstコンパイルし、成功時は使い捨ての中間ファイルを削除する。
    keep_temp=True（--keep-temp、#52）なら成功時も削除せず残す（失敗時は元々常に残る）。"""
    temp_typ_path = os.path.join(work_dir, "temp_build.typ")
    with open(temp_typ_path, "w", encoding="utf-8") as f:
        f.write(typst_code)

    # コンパイル失敗時にTypst側の行番号を元のMarkdownへ逆引きするための対応表（#27）。
    src_map = _build_srcmap(typst_code)

    out_pdf = os.path.join(outputs_dir, config["output"]["filename"])

    try:
        # ignore_system_fonts=True（#71）。テンプレート（template.typ/slide.typ）は本文フォントを
        # 一貫して"Noto Sans JP"（font_dirに同梱・キャッシュ済み）のみ指定しているため、システム
        # フォントを混ぜる必要が無い。付けないと、テンプレート指定フォントがカバーしない文字
        # （絵文字等）のフォールバック先がOSごとに異なる system フォント構成に左右され、同一入力
        # からでも環境ごとに出力（フォールバックフォントの選択）が変わり得る（9章の決定論的出力の
        # 前提が崩れる）。デフォルトで常に有効にし、config.yaml側に設定項目は設けない（このツールの
        # 「明示性優先」方針に合わせ、フォントを変えたい場合は独自テンプレート（template.path）で
        # 対応する）。
        typst_lib.compile(temp_typ_path, output=out_pdf, root=typst_root, font_paths=[font_dir],
                           ignore_system_fonts=True)
        print(f"[Success] Generated PDF: {out_pdf}")
    except typst_lib.TypstError as e:
        # str(e)はe.message（例: "unknown variable: foo"）のみで位置情報を持たない。
        # ファイル:行:列を含む整形済み診断（`┌─ temp_build.typ:32:1`形式）はe.diagnosticに
        # 別途入っている（実機確認で判明。#27の行番号マッピングはこちらが無いと機能しない）。
        diagnostic_text = getattr(e, "diagnostic", None) or str(e)
        print(f"[Error] Compile failed:\n{_annotate_typst_error(diagnostic_text, src_map)}")
        sys.exit(1)
    except Exception as e:
        print(f"[Error] Execution failed: {e}")
        # 原因が記述ミスではなく環境不備（typstのバージョン不一致等）の可能性があるため、
        # 関連するチェックだけを再実行して診断ヒントを出す（#37。全項目は--check-env参照）。
        diag = _check_typst_env(repo_root)
        if diag.status != "OK":
            print(f"[Hint] [{diag.status}] {diag.name}: {diag.message}")
        sys.exit(1)

    # ビルド成功後、使い捨ての中間ファイルを削除する（12章、#20）。
    # mermaidキャッシュ(cache/)は次回以降のビルドで再利用するため対象外。
    # 失敗時は温存し、生成されたTypstコードをそのままデバッグに使えるようにする。
    if keep_temp:
        _log_info(f"--keep-temp: keeping intermediate files ({temp_typ_path}, {template_copy_path})")
    else:
        os.remove(temp_typ_path)
        os.remove(template_copy_path)
        os.remove(os.path.join(work_dir, COMMON_TEMPLATE_NAME))

def _config_paths_from_args(args):
    """--config-list/--config/カレントディレクトリ探索から、対象のconfigパス（未指定ならNone）のリストを返す。"""
    if args.config_list:
        config_paths = _read_config_list(args.config_list)
        if not config_paths:
            print(f"[Error] --config-list {args.config_list} に有効なconfigパスがありません。")
            sys.exit(1)
        return config_paths
    return [args.config]

def _output_pdf_path(project_dir, config):
    """出力PDFの絶対パス。ディレクトリは作らない（_resolve_project_dirsと違い副作用を持たない）。"""
    return os.path.normpath(os.path.join(project_dir, config["output"]["dir"], config["output"]["filename"]))

# --if-changed（#151）。判定は更新日時のみ（make方式）で、内容ハッシュは採用しない。ハッシュ方式は
# 全入力を毎回読む必要があり、しかもCIではactions/checkoutが全ファイルの更新日時を更新するため、
# 更新日時方式は出力PDFを復元しない限り常に再生成になる。CIで使う場合は出力先をactions/cacheで
# 復元し、復元したPDFが入力より新しくなる運用が必要（仕様書4章）。
def _is_up_to_date(tool_dir, config_path, project_dir, config):
    """(出力PDFが依存物のどれよりも新しいか, 出力PDFパス)を返す。出力PDFが無ければ古い扱い。
    依存物は--watchと同じ解決結果（config・project_dir配下・inputs.dir・.typテンプレート）に、ツール自身
    （build.py）と同梱テンプレートを加えたもの。ツールの更新（pip upgrade等）で出力が変わり得るため。
    Typst自体のバージョンは判定に含めない（更新日時では検出できない。再生成したいときは--if-changedを外す）。"""
    out_pdf = _output_pdf_path(project_dir, config)
    try:
        out_mtime = os.stat(out_pdf).st_mtime_ns
    except OSError:
        return False, out_pdf
    roots, ignore, files = _watch_targets(tool_dir, config_path)
    files = files + [os.path.abspath(__file__), _common_template_path(tool_dir),
                     resolve_template_path(config["template"]["path"], tool_dir, project_dir)]
    explicit = {os.path.normcase(os.path.normpath(f)) for f in files}
    snapshot = _watch_snapshot(roots, ignore, files)
    # 同じproject_dirを共有する別configのPDFを入力とみなすと、--config-listで互いのPDFの更新を
    # 検知し合い、常に再生成になる。PDFはTypstの入力にならないため、個別指定の依存物以外は除外する。
    newest = max((mtime for path, (mtime, _) in snapshot.items()
                  if not path.lower().endswith(".pdf") or os.path.normcase(os.path.normpath(path)) in explicit),
                 default=0)
    return out_mtime > newest, out_pdf

def _clean_one(config_path, include_cache):
    """1つのconfigの生成物を削除する。出力PDFと.text-compositor/直下の中間ファイル（temp_build.typ・
    _template.*）が対象。include_cacheなら図表キャッシュ（.text-compositor/cache/）も削除する。
    パスはビルド時と同じくconfigの置き場所（project_dir）基準で解決する。存在しないものは無視する。"""
    project_dir, config, _ = _load_project_config(config_path)
    work_dir = os.path.join(project_dir, ".text-compositor")
    targets = [_output_pdf_path(project_dir, config), os.path.join(work_dir, "temp_build.typ")]
    if os.path.isdir(work_dir):
        targets += [os.path.join(work_dir, n) for n in sorted(os.listdir(work_dir)) if n.startswith("_template.") or n == COMMON_TEMPLATE_NAME]
    removed = 0
    for path in targets:
        if os.path.isfile(path):
            os.remove(path)
            _log_info(f"Removed: {path}")
            removed += 1
    cache_dir = os.path.join(work_dir, "cache")
    if include_cache and os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        _log_info(f"Removed: {cache_dir}")
        removed += 1
    # 空になった作業ディレクトリは残さない（他のファイルがあれば削除されない）
    try:
        os.rmdir(work_dir)
    except OSError:
        pass
    print(f"[Success] Cleaned {removed} item(s): {project_dir}")

def _clean_all(config_paths, include_cache):
    for config_path in config_paths:
        _clean_one(config_path, include_cache)

def build():
    # tool_dir: ツール自身に同梱されたリソース（templates/）の場所。パッケージ化後は
    # text_compositor/ パッケージのディレクトリを指す（#111）。
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    # repo_root: 「クローンして直接叩く」場合のリポジトリルート。requirements.txt探索にのみ使う。
    # pipインストール後はrequirements.txtが同梱されないため、自然に「見つからない」扱いになる。
    repo_root = os.path.dirname(tool_dir)
    args = parse_args()

    # ログの詳細度（#52）。CLI起動時に一度だけプロセスグローバルへ反映する。
    global _QUIET, _VERBOSE
    _QUIET = args.quiet
    _VERBOSE = args.verbose

    if args.check_env:
        sys.exit(run_env_check(repo_root, args.config))

    # cleanは削除のみで、Typstやフォントを必要としない。環境不備やフォントのダウンロードで妨げない。
    if args.clean:
        _clean_all(_config_paths_from_args(args), include_cache=args.clean_cache)
        return

    check_typst_version(repo_root)
    font_dir = ensure_fonts()

    if args.config_list:
        config_paths = _read_config_list(args.config_list)
        if not config_paths:
            print(f"[Error] --config-list {args.config_list} に有効なconfigパスがありません。")
            sys.exit(1)
        if args.watch:
            _watch(tool_dir, repo_root, font_dir, config_paths, keep_temp=args.keep_temp)
            return
        # いずれかのビルドが失敗した時点でsys.exit(1)により停止する（_load_project_config等が担う）。
        for config_path in config_paths:
            print(f"[Build] {config_path}")
            _build_one(tool_dir, repo_root, font_dir, config_path, keep_temp=args.keep_temp,
                       if_changed=args.if_changed)
    elif args.watch:
        config_path = os.path.abspath(args.config) if args.config else find_config_in_cwd()
        if not config_path:
            print("[Error] --config not specified, and no text-compositor.config.yaml/.json found in the current directory.")
            sys.exit(1)
        _watch(tool_dir, repo_root, font_dir, [config_path], keep_temp=args.keep_temp)
    else:
        _build_one(tool_dir, repo_root, font_dir, args.config, keep_temp=args.keep_temp,
                   if_changed=args.if_changed)

# --watch（#30）。watchdog等のファイル監視ライブラリは追加せず、標準ライブラリだけでmtime/サイズを
# ポーリングする（2章の「依存・ダウンロードは最小限」方針。対象は手書きの文書プロジェクトで
# ファイル数が少なく、0.5秒間隔の走査で十分軽いため、OS依存のイベントAPIを持ち込む利点が薄い）。
_WATCH_POLL_SECONDS = 0.5
# エディタの保存は「一時ファイルへ書いてからリネーム」等で複数の変更に分かれることがある。
# 変更検知後、この間隔で走査し直して変化が止まるのを待ってからビルドする。
_WATCH_SETTLE_SECONDS = 0.3

def _watch_targets(tool_dir, config_path):
    """configから監視対象を解決し、(監視ルートのリスト, 無視するパスのリスト, 個別監視ファイルのリスト)を返す。
    ルートはproject_dirとinputs.dir、個別ファイルはconfig自身と（.typパス指定の場合のみ）テンプレート。
    ツール同梱テンプレート（名前指定）は利用者が編集しないため対象外。出力先は、ビルド自身が
    書き込むPDFを「変更」と誤検知して無限に再ビルドしないよう無視する。config自体が壊れている
    最中でも監視を続けたいので、読めなければconfigとproject_dirだけを対象にする。"""
    project_dir = os.path.dirname(config_path)
    roots, ignore, files = [project_dir], [], [config_path]
    try:
        # load_config_fileは失敗時に[Error]を出力してsys.exit(1)する。ビルド側で既に報告されるため、
        # ここでの二重表示を避ける。
        with contextlib.redirect_stdout(io.StringIO()):
            config = load_config_file(config_path)
        inputs_dir = os.path.normpath(os.path.join(project_dir, config.get("inputs", {}).get("dir") or "inputs"))
        outputs_dir = os.path.normpath(os.path.join(project_dir, config["output"]["dir"]))
        roots.append(inputs_dir)
        ignore.append(os.path.join(outputs_dir, config["output"]["filename"]))
        # output.dirが監視ルート自身（"."等）や祖先のときにディレクトリごと無視すると何も監視できなくなる
        if not any(r == outputs_dir or r.startswith(outputs_dir + os.sep) for r in roots):
            ignore.append(outputs_dir)
        template_value = config["template"]["path"]
        if template_value.endswith(".typ"):
            files.append(resolve_template_path(template_value, tool_dir, project_dir))
    except (Exception, SystemExit):
        pass
    return roots, ignore, files

def _watch_snapshot(roots, ignore, files):
    """監視対象の{パス: (mtime_ns, サイズ)}を返す。.始まりのディレクトリ・ファイル（.git、
    .text-compositor、エディタのスワップファイル等）と末尾~のバックアップは対象外。"""
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    ignored = {norm(p) for p in ignore}
    state = {}

    def record(path):
        try:
            st = os.stat(path)
        except OSError:
            return
        state[path] = (st.st_mtime_ns, st.st_size)

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d != "node_modules"
                           and norm(os.path.join(dirpath, d)) not in ignored]
            for name in filenames:
                path = os.path.join(dirpath, name)
                if name.startswith(".") or name.endswith("~") or norm(path) in ignored:
                    continue
                record(path)
    for path in files:
        record(path)
    return state

def _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp):
    """1回のビルドを実行し、成否を返す。ビルド内部のエラー終了（sys.exit(1)）や想定外の例外で
    ウォッチ全体を止めないよう握りつぶす（エラー内容は呼び出し先が出力済み）。"""
    try:
        _build_one(tool_dir, repo_root, font_dir, config_path, keep_temp=keep_temp)
        return True
    except SystemExit as e:
        return e.code in (0, None)
    except Exception as e:
        print(f"[Error] Build crashed: {e}")
        return False

def _watch(tool_dir, repo_root, font_dir, config_paths, keep_temp=False):
    """全configを初回ビルドした後、保存を検知したconfigだけを再ビルドし続ける。失敗しても終了せず、
    次の保存を待つ（編集→保存→結果確認の試行を繰り返す用途のため）。Ctrl+Cで終了する。"""
    watched = {}
    try:
        for config_path in config_paths:
            # 走査はビルドの前に行う。ビルド中の保存を取りこぼさず、次のループで検知するため。
            targets = _watch_targets(tool_dir, config_path)
            watched[config_path] = (targets, _watch_snapshot(*targets))
            print(f"[Build] {config_path}")
            _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp)
        _log_info("Watching for changes... (Ctrl+C to stop)")

        while True:
            time.sleep(_WATCH_POLL_SECONDS)
            for config_path in config_paths:
                targets, baseline = watched[config_path]
                current = _watch_snapshot(*targets)
                if current == baseline:
                    continue
                while True:
                    time.sleep(_WATCH_SETTLE_SECONDS)
                    settled = _watch_snapshot(*targets)
                    if settled == current:
                        break
                    current = settled
                changed = sorted(p for p in current if baseline.get(p) != current[p]) + \
                          sorted(p for p in baseline if p not in current)
                shown = ", ".join(os.path.basename(p) for p in changed[:3])
                _log_info(f"Change detected ({shown}{', ...' if len(changed) > 3 else ''}); rebuilding...")
                # configの変更でinputs.dir等が変わり得るため、再ビルドのたびに監視対象を解決し直す
                targets = _watch_targets(tool_dir, config_path)
                watched[config_path] = (targets, _watch_snapshot(*targets))
                print(f"[Build] {config_path}")
                _build_guarded(tool_dir, repo_root, font_dir, config_path, keep_temp)
                _log_info("Watching for changes... (Ctrl+C to stop)")
    except KeyboardInterrupt:
        _log_info("Watch stopped.")

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

    # plugins: Graphviz/PlantUML/Mermaid/D2の有効・無効切り替え（6章、#21、#90）。未指定時は
    # 既存動作を維持する既定値（graphviz/mermaid/plantuml/d2はいずれも常時有効）。
    # *_auto_download は、システムに必要なツール（ブラウザ/Java/D2）が無い場合の振る舞いを制御する
    # 別軸のフラグ（#22の設計議論）。既定値が非対称なのは、ダウンロードされる実体のサイズが
    # 一桁違うため（Playwright自身のChromium: 約700MB対Eclipse Temurin JRE: 約49.7MB対D2 CLI: 約13MB）。
    plugins_config = config.get("plugins") or {}
    graphviz_enabled = bool(plugins_config.get("graphviz", True))
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

    outputs_dir, inputs_dir, work_dir, typst_root = _resolve_project_dirs(project_dir, config)
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
                              d2_enabled=d2_enabled, d2_auto_download=d2_auto_download,
                              glossary_enabled=glossary_enabled, line_mapping=line_mapping,
                              marp_compat=marp_compat, variables=variables)
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

    _compile_and_cleanup(typst_code, work_dir, outputs_dir, config, typst_root, font_dir, template_copy_path, repo_root,
                         keep_temp=keep_temp)

if __name__ == "__main__":
    build()
