"""Mermaid描画用のヘッドレスブラウザ（PlaywrightとシステムのChrome/Edge）。"""
import os
import sys
import subprocess
import shutil
import time
import tempfile
from text_compositor.deps import ensure_mermaid_js, ensure_vega_js, find_system_browser
from text_compositor.env_check import _check_mermaid
from text_compositor.log import _error, _hint, _log_info

class MermaidBrowser:
    """Mermaid描画用のヘッドレスブラウザとページ（遅延起動）。

    ビルドごとに起動・終了すると、図1つあたり約1.3秒かかる（ブラウザの起動）。常駐するPython API
    （api.Session、#167）は、1つを使い回し、2回目以降は約18 msにする。CLIのように使い回さない場合は、
    TypstRendererが自分で持ち、ビルドの終わりに片付ける。
    """

    def __init__(self):
        self.page = None
        self.vega_page = None   # Vega・Vega-Lite用のページ（#211）。同じブラウザに、別のタブとして開く
        self.browser = None
        self.playwright = None
        self.chrome_proc = None
        self.profile_dir = None

    def ensure_page(self, mermaid_enabled, mermaid_auto_download):
        """Mermaidレンダリング用のヘッドレスブラウザ・ページを遅延起動する（初回のみ）。
        Node.js/npxを介さず、mermaid.min.js（実測約3.4MB）を直接ヘッドレスブラウザへ読み込ませて
        mermaid.render()を呼ぶ（仕様書11章、#35。mermaid-cli丸ごとの約396MBを回避する）。
        既存のシステムChrome/Edge（#34の検出ロジック）が見つかればPlaywrightのCDP接続で繋ぐだけで、
        ブラウザの追加ダウンロードは発生しない。見つからない場合、plugins.mermaid_auto_downloadが
        trueならPlaywright自身のChromium（実測約700MB）をその場で取得して使う。既定はfalseで、
        Fail-fastでエラー終了する（#22の設計議論。700MBは#34/#35がまさに避けた規模のため、
        既定で自動取得はしない）。"""
        if self.page is not None:
            try:
                if not self.page.is_closed() and self.browser.is_connected():
                    return self.page
            except Exception:
                pass
            # 常駐して使い回す間に、ブラウザが落ちた場合（#167）。片付けてから、起動し直す
            _log_info("Mermaid browser is no longer available; restarting it.")
            self.close()

        self._ensure_browser(mermaid_enabled, mermaid_auto_download)
        mermaid_js_path = ensure_mermaid_js()
        page = self._new_page()
        page.set_content("<div id='container'></div>")
        with open(mermaid_js_path, "r", encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        # Typstのraw SVGレンダラーは<foreignObject>内のHTMLを描画できないため、mermaid既定の
        # HTMLラベルを無効化し、通常のSVG<text>要素で出力させる（トップレベルとflowchart配下
        # 両方に指定する必要がある。PoCで確認済み）。
        # flowchart.padding（既定15）・sequence.diagramMarginX/Y（既定50/10）は、本文へ埋め込む
        # 小さな図には過大なため、D2と同じ8pxへ縮める（#315）。これらは内容のレイアウト後に
        # 外側へ付け足す余白で、内容自体の大きさは変えないため、値を縮めても見切れる心配はない
        # （実機確認: 長いnoteを含む図で、内容のバウンディングボックスが変化しないことを確認）。
        # 他の図の種類（class/state/er/gantt等）は、種類ごとに別のキー・既定値を持つため未対応。
        page.evaluate("mermaid.initialize({ startOnLoad: false, htmlLabels: false, "
                      "flowchart: { htmlLabels: false, padding: 8 }, "
                      "sequence: { diagramMarginX: 8, diagramMarginY: 8 } })")
        self.page = page
        return page

    def ensure_vega_page(self, mermaid_enabled, mermaid_auto_download):
        """Vega・Vega-Lite描画用のページを遅延起動して返す（#211）。Mermaidと同じヘッドレスブラウザに、別のタブとして開く
        （ブラウザの起動は、約1.3秒かかるため、共有する）。vega.min.jsとvega-lite.min.js（合わせて約772KB）を読み込ませ、
        `vega.View`・`vegaLite.compile`を直接呼ぶ（Node.jsやvega-cliは、要らない）。"""
        if self.vega_page is not None:
            try:
                if not self.vega_page.is_closed() and self.browser.is_connected():
                    return self.vega_page
            except Exception:
                pass
            _log_info("Vega browser is no longer available; restarting it.")
            self.close()

        self._ensure_browser(mermaid_enabled, mermaid_auto_download)
        vega_js_path, vega_lite_js_path = ensure_vega_js()
        page = self._new_page()
        page.set_content("<div id='container'></div>")
        for path in (vega_js_path, vega_lite_js_path):
            with open(path, "r", encoding="utf-8") as f:
                page.add_script_tag(content=f.read())
        self.vega_page = page
        return page

    def _new_page(self):
        context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        return context.new_page()

    def _ensure_browser(self, mermaid_enabled, mermaid_auto_download):
        """ヘッドレスブラウザを、まだ起動していなければ起動する（Mermaidと、Vega・Vega-Liteで共有する）。"""
        if self.browser is not None:
            try:
                if self.browser.is_connected():
                    return
            except Exception:
                pass
            self.close()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            _error("The 'playwright' package is required for mermaid rendering (plugins.mermaid: true). "
                  "Install it with: pip install playwright==1.63.0")
            sys.exit(1)

        browser_path = find_system_browser()
        self.playwright = sync_playwright().start()

        if browser_path:
            _log_info(f"Reusing system browser for mermaid rendering: {browser_path}")
            self.profile_dir = tempfile.mkdtemp(prefix="cc-mermaid-")
            self.chrome_proc, port = _launch_headless_chrome(browser_path, self.profile_dir)
            try:
                self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except Exception as e:
                _error(f"Failed to connect to headless browser for mermaid rendering: {e}")
                diag = _check_mermaid(mermaid_enabled, mermaid_auto_download)
                if diag.status != "OK":
                    _hint(f"[{diag.status}] {diag.name}: {diag.message}")
                sys.exit(1)
        elif mermaid_auto_download:
            _log_info("No system Chrome/Edge found; plugins.mermaid_auto_download is true, so Playwright "
                      "will download its own Chromium (one-time; approx. 700MB; cached under Playwright's "
                      "browser cache, typically ~/.cache/ms-playwright)...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except (subprocess.CalledProcessError, OSError) as e:
                _error(f"Failed to download Playwright's Chromium: {e}")
                sys.exit(1)
            try:
                self.browser = self.playwright.chromium.launch(headless=True)
            except Exception as e:
                _error(f"Failed to launch the downloaded Chromium for mermaid rendering: {e}")
                sys.exit(1)
        else:
            _error("No system Chrome/Edge found; required to render mermaid diagrams locally. "
                  "Install Google Chrome or Microsoft Edge, or set plugins.mermaid_auto_download: true "
                  "(downloads Playwright's own Chromium, approx. 700MB), or set plugins.mermaid: false.")
            sys.exit(1)

    def close(self):
        """ensure_pageで起動したヘッドレスブラウザを片付ける（一度も起動していなければ何もしない）。
        何度呼んでも安全で、片付けた後は再びensure_pageで起動できる。"""
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception:
                pass
        if self.chrome_proc is not None:
            self.chrome_proc.terminate()
            try:
                self.chrome_proc.wait(timeout=5)
            except Exception:
                self.chrome_proc.kill()
        if self.profile_dir and os.path.exists(self.profile_dir):
            shutil.rmtree(self.profile_dir, ignore_errors=True)
        self.page = self.vega_page = self.browser = self.playwright = self.chrome_proc = self.profile_dir = None

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
    _error("Headless browser did not become ready in time (needed for mermaid rendering).")
    sys.exit(1)
