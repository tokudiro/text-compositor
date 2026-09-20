"""外部ツールと取得物（フォント・Mermaid・Viz.js・JRE・PlantUML・D2）の、検出・ダウンロード・キャッシュ。"""
import os
import re
import sys
import subprocess
import hashlib
import shutil
import urllib.error
import urllib.request
import http.client
import zipfile
import tarfile
import time
import platform
import platformdirs
from text_compositor.log import _error, _log_info

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

# 取得（ダウンロード）の再試行（#189）。GitHubのリリース等は、一時的に5xxや接続エラーを返すことがある。CIの
# ように、毎回まっさらな環境で、取得が必ず起こる場合、1回の失敗が、テスト全体の失敗になっていた。
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAYS = (1.0, 3.0)   # 失敗ごとの、次の試行までの待ち時間（秒）

def _is_transient_download_error(error):
    """再試行して、成功する見込みのある失敗か。HTTPの5xx・408・429、接続や時間切れ、途中で切れた転送。
    404などのクライアントエラーや、ディスクへの書き込みの失敗は、再試行しても直らないため、対象外。"""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code in (408, 429)
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))

def _download(url, dest, attempts=DOWNLOAD_ATTEMPTS, delays=DOWNLOAD_RETRY_DELAYS, sleep=None):
    """urlをdestへ取得する。一時的な失敗は、間隔を空けて再試行する（合計attempts回）。
    取得中は、`dest.part`へ書き、成功したときだけdestへ置き換える。途中で失敗した書きかけのファイルが、
    destに残って、次回以降、取得済みとして使われるのを防ぐ。最後の失敗は、OSErrorとして、そのまま送出する。"""
    part = dest + ".part"
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            urllib.request.urlretrieve(url, part)
            os.replace(part, dest)
            return
        except http.client.HTTPException as e:   # 切れた応答など。一時的な失敗とみなす。呼び出し側は、OSErrorだけを扱う
            last_error = OSError(f"{type(e).__name__}: {e}")
            last_error.__cause__ = e
            transient = True
        except OSError as e:
            last_error = e
            transient = _is_transient_download_error(e)
        finally:
            if os.path.exists(part):
                os.remove(part)
        if attempt == attempts or not transient:
            raise last_error
        delay = delays[min(attempt - 1, len(delays) - 1)]
        _log_info(f"Download failed ({last_error}); retrying in {delay:g}s ({attempt}/{attempts})...")
        (sleep or time.sleep)(delay)
    raise last_error

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

def _system_d2_version(d2_bin):
    """`d2 --version`の出力（例: "v0.9.0"）を返す。取得できなければNone。"""
    try:
        result = subprocess.run([d2_bin, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None

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
        _download(NOTO_SANS_JP_RELEASE_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            for name in missing:
                data = zf.read(name)
                digest = hashlib.sha256(data).hexdigest()
                if digest != NOTO_SANS_JP_FILES[name]:
                    _error(f"Checksum mismatch for {name}: expected {NOTO_SANS_JP_FILES[name]}, got {digest}")
                    sys.exit(1)
                with open(os.path.join(font_dir, name), "wb") as f:
                    f.write(data)
    except zipfile.BadZipFile as e:
        _error(f"Failed to download fonts (bad zip): {e}")
        sys.exit(1)
    except OSError as e:
        _error(f"Failed to download fonts: {e}")
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
        _download(MERMAID_JS_URL, js_path)
    except OSError as e:
        _error(f"Failed to download mermaid.min.js: {e}")
        sys.exit(1)

    with open(js_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != MERMAID_JS_SHA256:
        os.remove(js_path)
        _error(f"Checksum mismatch for mermaid.min.js: expected {MERMAID_JS_SHA256}, got {digest}")
        sys.exit(1)

    return js_path

# Graphvizは、Viz.js（MIT。Graphvizを、WebAssemblyにしたもの。Graphviz本体はEPL-2.0、ExpatはMIT）の
# 単一ファイルだけを取得し、ViewerのElectronのChromiumで描画する（#181）。mermaid.min.jsと同様に、
# バージョン・SHA256を固定し、初回にだけダウンロードして、キャッシュする。同梱は、しない。
VIZ_JS_VERSION = "3.30.0"
VIZ_JS_URL = f"https://cdn.jsdelivr.net/npm/@viz-js/viz@{VIZ_JS_VERSION}/dist/viz-global.js"
VIZ_JS_SHA256 = "c857641af952c8f82ac7243917f8563959046e5cfc44d7e84eff9a2b470f5eab"
# ホスト側（viewer/src/graphviz-host.js）が行う、文字幅の補正の版。補正の方法を変えたら、上げる（キャッシュの無効化）。
GRAPHVIZ_FIT_REVISION = 1

def ensure_viz_js():
    """viz-global.jsがユーザーキャッシュディレクトリの viz/ になければダウンロードする（ensure_mermaid_jsと同じ）。"""
    cache_dir = os.path.join(_user_cache_dir(), "viz")
    os.makedirs(cache_dir, exist_ok=True)
    js_path = os.path.join(cache_dir, f"viz-global-{VIZ_JS_VERSION}.js")
    if os.path.exists(js_path):
        return js_path

    _log_info(f"Downloading viz-global.js (one-time; cached under {cache_dir})...")
    tmp_path = js_path + ".download"
    try:
        _download(VIZ_JS_URL, tmp_path)
    except OSError as e:
        _error(f"Failed to download viz-global.js: {e}")
        sys.exit(1)

    with open(tmp_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != VIZ_JS_SHA256:
        os.remove(tmp_path)
        _error(f"Checksum mismatch for viz-global.js: expected {VIZ_JS_SHA256}, got {digest}")
        sys.exit(1)
    os.replace(tmp_path, js_path)   # 検証に通ったものだけを、正式な名前にする
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
        _error(f"No Eclipse Temurin JRE build available for this platform ({key[0]}/{key[1]}). "
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
        _download(TEMURIN_JRE_BASE_URL + filename, archive_path)
    except OSError as e:
        _error(f"Failed to download Eclipse Temurin JRE: {e}")
        sys.exit(1)

    with open(archive_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        os.remove(archive_path)
        _error(f"Checksum mismatch for {filename}: expected {sha256}, got {digest}")
        sys.exit(1)

    if archive_type == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(cache_root)
    else:
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(cache_root)
    os.remove(archive_path)

    if not os.path.exists(java_bin_path):
        _error(f"Eclipse Temurin JRE extraction did not produce the expected binary: {java_bin_path}")
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
        _download(PLANTUML_JAR_URL, jar_path)
    except OSError as e:
        _error(f"Failed to download plantuml.jar: {e}")
        sys.exit(1)

    with open(jar_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != PLANTUML_JAR_SHA256:
        os.remove(jar_path)
        _error(f"Checksum mismatch for plantuml.jar: expected {PLANTUML_JAR_SHA256}, got {digest}")
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
        _error(f"No D2 CLI build available for this platform ({key[0]}/{key[1]}). "
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
        _download(D2_BASE_URL + filename, archive_path)
    except OSError as e:
        _error(f"Failed to download D2 CLI: {e}")
        sys.exit(1)

    with open(archive_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        os.remove(archive_path)
        _error(f"Checksum mismatch for {filename}: expected {sha256}, got {digest}")
        sys.exit(1)

    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(cache_root)
    os.remove(archive_path)

    if not os.path.exists(d2_bin_path):
        _error(f"D2 CLI extraction did not produce the expected binary: {d2_bin_path}")
        sys.exit(1)
    if key[0] != "win32":
        os.chmod(d2_bin_path, 0o755)

    return d2_bin_path
