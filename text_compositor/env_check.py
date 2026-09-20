"""実行環境の前提を事前確認する`--check-env`（#37）と、ビルド時のTypstバージョン確認（#49）。"""
import os
import re
import sys
import importlib.metadata
from collections import namedtuple
from text_compositor.config import _load_project_config, yaml
from text_compositor.deps import D2_ASSETS, NOTO_SANS_JP_FILES, TEMURIN_JRE_ASSETS, TEMURIN_JRE_TOP_DIR, _d2_bin_path, _d2_cache_root, _jre_cache_root, _temurin_platform_key, _user_cache_dir, find_system_browser, find_system_d2, find_system_java
from text_compositor.log import _warn

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
        _warn(f"Installed typst version ({installed_version}) does not match "
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
