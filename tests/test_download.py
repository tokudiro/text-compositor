"""取得（ダウンロード）の再試行（_download、#189）のテスト。ネットワークは使わず、urlretrieveを差し替えて、
失敗を再現する。"""
import hashlib
import http.client
import io
import os
import urllib.error
import zipfile

import pytest

from text_compositor.deps import DOWNLOAD_ATTEMPTS, VIZ_JS_URL, VIZ_JS_VERSION, _download, ensure_fonts, ensure_mermaid_js, ensure_viz_js
import text_compositor.deps as deps_mod
import time
import urllib.request


def http_error(code):
    return urllib.error.HTTPError("https://example.com/x", code, f"HTTP {code}", None, io.BytesIO(b""))


class FakeRetrieve:
    """urlretrieveの代わり。呼ばれるたびに、steps（例外、または、書き込む内容）を1つずつ使う。"""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, url, filename):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        with open(filename, "wb") as f:
            f.write(step)
        return filename, None


@pytest.fixture
def sleeps():
    return []


def download(tmp_path, retrieve, monkeypatch, sleeps, **kwargs):
    monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)
    dest = str(tmp_path / "file.bin")
    _download("https://example.com/file.bin", dest, sleep=sleeps.append, **kwargs)
    return dest


class TestDownload:
    def test_success_on_the_first_try_leaves_no_part_file(self, tmp_path, monkeypatch, sleeps):
        retrieve = FakeRetrieve(b"data")
        dest = download(tmp_path, retrieve, monkeypatch, sleeps)
        assert open(dest, "rb").read() == b"data"
        assert not os.path.exists(dest + ".part")
        assert retrieve.calls == 1 and sleeps == []

    @pytest.mark.parametrize("error", [
        http_error(500), http_error(502), http_error(503), http_error(429), http_error(408),
        urllib.error.URLError("connection refused"),
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        urllib.error.ContentTooShortError("short", b""),
        http.client.RemoteDisconnected("closed"),
        http.client.BadStatusLine("garbage"),
    ])
    def test_transient_failures_are_retried_until_they_succeed(self, tmp_path, monkeypatch, sleeps, error):
        retrieve = FakeRetrieve(error, error, b"data")
        dest = download(tmp_path, retrieve, monkeypatch, sleeps)
        assert open(dest, "rb").read() == b"data"
        assert retrieve.calls == 3
        assert sleeps == [1.0, 3.0]   # 間隔を空けて、再試行する

    @pytest.mark.parametrize("error", [http_error(404), http_error(403), http_error(400), PermissionError("denied")])
    def test_permanent_failures_are_not_retried(self, tmp_path, monkeypatch, sleeps, error):
        retrieve = FakeRetrieve(error, b"never used")
        with pytest.raises(OSError):
            download(tmp_path, retrieve, monkeypatch, sleeps)
        assert retrieve.calls == 1 and sleeps == []

    def test_gives_up_after_the_last_attempt_with_the_last_error(self, tmp_path, monkeypatch, sleeps):
        retrieve = FakeRetrieve(http_error(500), http_error(502), http_error(503))
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            download(tmp_path, retrieve, monkeypatch, sleeps)
        assert excinfo.value.code == 503
        assert retrieve.calls == DOWNLOAD_ATTEMPTS == 3
        assert len(sleeps) == 2   # 最後の失敗のあとは、待たない

    def test_a_partial_file_from_a_failed_attempt_is_removed(self, tmp_path, monkeypatch, sleeps):
        def writes_then_fails(url, filename):
            with open(filename, "wb") as f:
                f.write(b"half")
            raise ConnectionResetError("cut")

        with pytest.raises(ConnectionResetError):
            download(tmp_path, writes_then_fails, monkeypatch, sleeps)
        assert not os.path.exists(str(tmp_path / "file.bin"))       # 取得済みとして、使われない
        assert not os.path.exists(str(tmp_path / "file.bin.part"))

    def test_a_broken_http_response_is_reported_as_oserror(self, tmp_path, monkeypatch, sleeps):
        retrieve = FakeRetrieve(*[http.client.IncompleteRead(b"x")] * 3)
        with pytest.raises(OSError) as excinfo:   # 呼び出し側は、OSErrorだけを扱う
            download(tmp_path, retrieve, monkeypatch, sleeps)
        assert "IncompleteRead" in str(excinfo.value)

    def test_the_delay_list_is_reused_when_there_are_more_attempts(self, tmp_path, monkeypatch, sleeps):
        retrieve = FakeRetrieve(http_error(500), http_error(500), http_error(500), b"data")
        download(tmp_path, retrieve, monkeypatch, sleeps, attempts=4, delays=(2.0,))
        assert sleeps == [2.0, 2.0, 2.0]


class TestEnsureFonts:
    """フォントの取得が、一時的な失敗から回復し、チェックサムの不一致では、再試行しないこと。"""

    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        files = {"NotoSansJP-Regular.otf": b"regular", "NotoSansJP-Bold.otf": b"bold"}
        monkeypatch.setattr(deps_mod, "NOTO_SANS_JP_FILES", {n: hashlib.sha256(d).hexdigest() for n, d in files.items()})
        monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(tmp_path / "cache"))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        archive = tmp_path / "fonts.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return archive.read_bytes(), tmp_path

    def test_recovers_from_transient_errors(self, cache, monkeypatch):
        archive, tmp_path = cache
        retrieve = FakeRetrieve(http_error(500), urllib.error.URLError("dns"), archive)
        monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)

        font_dir = ensure_fonts()

        assert retrieve.calls == 3
        assert sorted(os.listdir(font_dir)) == ["NotoSansJP-Bold.otf", "NotoSansJP-Regular.otf"]

    def test_a_cached_font_is_not_downloaded_again(self, cache, monkeypatch):
        archive, _ = cache
        monkeypatch.setattr(urllib.request, "urlretrieve", FakeRetrieve(archive))
        ensure_fonts()
        second = FakeRetrieve()
        monkeypatch.setattr(urllib.request, "urlretrieve", second)
        ensure_fonts()
        assert second.calls == 0

    def test_a_checksum_mismatch_is_an_error_and_is_not_retried(self, cache, monkeypatch, tmp_path):
        _, _ = cache
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("NotoSansJP-Regular.otf", b"tampered")
            zf.writestr("NotoSansJP-Bold.otf", b"bold")
        retrieve = FakeRetrieve(bad.read_bytes(), b"never used")
        monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)
        with pytest.raises(SystemExit):
            ensure_fonts()
        assert retrieve.calls == 1

    def test_gives_up_with_an_error_after_all_attempts(self, cache, monkeypatch):
        retrieve = FakeRetrieve(http_error(500), http_error(500), http_error(500))
        monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)
        with pytest.raises(SystemExit):
            ensure_fonts()
        assert retrieve.calls == 3


class TestOtherDownloads:
    """フォント以外の取得（Mermaid用のJS）も、同じ再試行を使う。"""

    def test_mermaid_js_recovers_and_a_partial_file_is_never_used(self, tmp_path, monkeypatch):
        content = b"mermaid-bundle"
        monkeypatch.setattr(deps_mod, "MERMAID_JS_SHA256", hashlib.sha256(content).hexdigest())
        monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(tmp_path / "cache"))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        def flaky(url, filename, calls=[0]):
            calls[0] += 1
            if calls[0] == 1:
                with open(filename, "wb") as f:
                    f.write(b"partial")
                raise ConnectionResetError("cut")
            with open(filename, "wb") as f:
                f.write(content)

        monkeypatch.setattr(urllib.request, "urlretrieve", flaky)
        path = ensure_mermaid_js()
        assert open(path, "rb").read() == content

    def test_viz_js_is_verified_by_checksum_and_only_a_verified_file_is_kept(self, tmp_path, monkeypatch):
        monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(tmp_path / "cache"))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        def fetch(content):
            def retrieve(url, filename):
                with open(filename, "wb") as f:
                    f.write(content)
            return retrieve

        monkeypatch.setattr(deps_mod, "VIZ_JS_SHA256", hashlib.sha256(b"viz-bundle").hexdigest())
        monkeypatch.setattr(urllib.request, "urlretrieve", fetch(b"tampered"))
        with pytest.raises(SystemExit):
            ensure_viz_js()
        assert list((tmp_path / "cache" / "viz").iterdir()) == []   # 検証に通らなければ、何も残らない

        monkeypatch.setattr(urllib.request, "urlretrieve", fetch(b"viz-bundle"))
        path = ensure_viz_js()
        assert open(path, "rb").read() == b"viz-bundle"
        # 取得済みなら、ネットワークを使わない
        monkeypatch.setattr(urllib.request, "urlretrieve", lambda *a: pytest.fail("downloaded again"))
        assert ensure_viz_js() == path

    def test_the_pinned_viz_js_url_names_the_pinned_version(self):
        assert f"@viz-js/viz@{VIZ_JS_VERSION}/" in VIZ_JS_URL

    def test_plantuml_jar_cached_by_an_older_version_is_not_reused(self, tmp_path, monkeypatch):
        """版を上げたとき、取得済みの古いjar（固定名plantuml-mit.jar）が使われ続けると、修正が届かない（#240）。"""
        cache = tmp_path / "cache"
        monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(cache))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        (cache / "plantuml").mkdir(parents=True)
        (cache / "plantuml" / "plantuml-mit.jar").write_bytes(b"old-version")

        def retrieve(url, filename):
            with open(filename, "wb") as f:
                f.write(b"new-version")

        monkeypatch.setattr(deps_mod, "PLANTUML_JAR_SHA256", hashlib.sha256(b"new-version").hexdigest())
        monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)
        path = deps_mod.ensure_plantuml_jar()
        assert open(path, "rb").read() == b"new-version"
        assert os.path.basename(path) == os.path.basename(deps_mod.PLANTUML_JAR_URL)
