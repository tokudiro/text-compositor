"""Mermaid用ブラウザの使い回し（MermaidBrowser、#167）のテスト。"""
import os
import sys

import pytest

import text_compositor.build as build
from text_compositor import diagnostics
from text_compositor.api import Session


class FakePage:
    def __init__(self, closed=False):
        self._closed = closed

    def is_closed(self):
        return self._closed


class FakeBrowser:
    def __init__(self, connected=True):
        self._connected = connected
        self.closed = False

    def is_connected(self):
        return self._connected

    def close(self):
        self.closed = True


class TestOwnership:
    def test_renderer_owns_and_closes_its_own_browser(self, monkeypatch):
        closed = []
        renderer = build.TypstRenderer(line_mapping="off")
        monkeypatch.setattr(renderer._mermaid, "close", lambda: closed.append(1))
        renderer.close()
        assert closed == [1]

    def test_renderer_does_not_close_an_injected_browser(self):
        closed = []

        class Injected(build.MermaidBrowser):
            def close(self):
                closed.append(1)
        renderer = build.TypstRenderer(line_mapping="off", mermaid_browser=Injected())
        renderer.close()
        renderer.close()
        assert closed == []

    def test_injected_browser_is_the_one_used(self):
        shared = build.MermaidBrowser()
        a = build.TypstRenderer(line_mapping="off", mermaid_browser=shared)
        b = build.TypstRenderer(line_mapping="off", mermaid_browser=shared)
        assert a._mermaid is shared and b._mermaid is shared


class TestMermaidBrowserLifecycle:
    def test_close_without_starting_is_harmless_and_repeatable(self):
        b = build.MermaidBrowser()
        b.close()
        b.close()
        assert b.page is None

    def test_close_resets_state_so_it_can_be_started_again(self):
        b = build.MermaidBrowser()
        b.page, b.browser = FakePage(), FakeBrowser()
        b.close()
        assert b.page is None and b.browser is None and b.playwright is None

    def test_a_live_page_is_reused(self):
        b = build.MermaidBrowser()
        page = FakePage()
        b.page, b.browser = page, FakeBrowser()
        assert b.ensure_page(True, False) is page

    @pytest.mark.parametrize("page,browser", [(FakePage(closed=True), FakeBrowser()),
                                              (FakePage(), FakeBrowser(connected=False))])
    def test_a_dead_browser_is_cleaned_up_and_restarted(self, monkeypatch, page, browser):
        """使い回している間にブラウザが落ちたら、片付けて、起動し直そうとする（ここでは、起動できない環境にして、
        エラーになることで、起動し直そうとしたことを確かめる）。"""
        monkeypatch.setattr(build, "find_system_browser", lambda: None)
        fake_playwright = type(sys)("playwright.sync_api")

        class FakePlaywright:
            def stop(self):
                pass
        fake_playwright.sync_playwright = lambda: type("S", (), {"start": lambda self: FakePlaywright()})()
        monkeypatch.setitem(sys.modules, "playwright", type(sys)("playwright"))
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_playwright)
        b = build.MermaidBrowser()
        b.page, b.browser = page, browser
        with diagnostics.collect() as c:
            with pytest.raises(SystemExit):
                b.ensure_page(True, False)
        assert browser.closed
        assert any("no longer available" in d.message for d in c.items if d.severity == "info")
        assert any("No system Chrome/Edge found" in d.message for d in c.errors)


class TestSessionCleanup:
    def test_a_half_started_browser_is_cleaned_up_after_a_failed_build(self, tmp_path, monkeypatch):
        closed = []

        class Half(build.MermaidBrowser):
            def close(self):
                closed.append(1)
        monkeypatch.setattr(build, "MermaidBrowser", Half)

        def fail(*a, **k):
            diagnostics.error("browser failed")
            sys.exit(1)
        monkeypatch.setattr(build, "_build_project", fail)
        md = tmp_path / "doc.md"
        md.write_text("# T\n", encoding="utf-8")
        with Session(font_dir="fonts") as s:
            assert not s.build(str(md), str(tmp_path / "o.pdf")).ok
            assert closed == [1]  # page is None -> cleaned up right away


def _has_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return build.find_system_browser() is not None


@pytest.mark.skipif(not _has_browser(), reason="needs playwright and a system Chrome/Edge")
class TestRealBrowser:
    def test_the_browser_is_reused_across_builds_and_released_on_close(self, tmp_path):
        md = tmp_path / "doc.md"
        out = tmp_path / "o.pdf"
        plugins = {"plantuml": False, "d2": False}
        with Session(font_dir=build.ensure_fonts()) as s:
            md.write_text("# T\n\n```mermaid\ngraph TD\n  A[one] --> B[two]\n```\n", encoding="utf-8")
            first = s.build(str(md), str(out), plugins=plugins)
            assert first.ok, first.diagnostics
            page, proc = s._mermaid.page, s._mermaid.chrome_proc
            assert page is not None and proc is not None and proc.poll() is None

            md.write_text("# T\n\n```mermaid\ngraph TD\n  A[three] --> B[four]\n```\n", encoding="utf-8")
            second = s.build(str(md), str(out), plugins=plugins)
            assert second.ok, second.diagnostics
            assert s._mermaid.page is page and s._mermaid.chrome_proc is proc  # 使い回された
            assert second.timings_ms["render"] < first.timings_ms["render"]  # ブラウザの起動が、2回目には無い
        assert proc.poll() is not None  # close()で、ブラウザのプロセスが終了した（ゾンビを残さない）
