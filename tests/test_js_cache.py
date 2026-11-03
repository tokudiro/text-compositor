"""図のJS（Mermaid・Vega・WaveDrom・Bytefield）のキャッシュ（text_compositor/deps.py。#597）のテスト。

固定した版を上げても、取得済みの古い版が使われ続けないこと。壊れたファイルを使わないこと。"""
import hashlib
import os
import urllib.request

import pytest

from text_compositor import deps as deps_mod

NEW = b"new-version"
OLD = b"old-version"
NEW_SHA = hashlib.sha256(NEW).hexdigest()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(deps_mod, "_user_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(deps_mod, "_verified_cache_files", set())
    monkeypatch.delenv(deps_mod.MERMAID_JS_ENV, raising=False)
    return tmp_path / "cache" / "lib"


def fetch(monkeypatch, content=NEW):
    calls = []

    def retrieve(url, filename):
        calls.append(url)
        with open(filename, "wb") as f:
            f.write(content)

    monkeypatch.setattr(urllib.request, "urlretrieve", retrieve)
    return calls


def forbid_download(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlretrieve", lambda *a, **k: pytest.fail("downloaded"))


def ensure():
    return deps_mod._ensure_verified_js("https://example.invalid/lib.min.js", NEW_SHA, "lib", "lib.min.js")


class TestCacheName:
    def test_the_name_contains_the_pinned_hash(self):
        assert deps_mod._cache_file_name("mermaid.min.js", "6484afc32872a3aa") == "mermaid.min-6484afc32872.js"

    def test_a_different_pin_gives_a_different_name(self):
        assert deps_mod._cache_file_name("lib.js", "a" * 64) != deps_mod._cache_file_name("lib.js", "b" * 64)


class TestEnsure:
    def test_a_file_cached_under_the_old_fixed_name_is_not_used(self, cache, monkeypatch):
        cache.mkdir(parents=True)
        (cache / "lib.min.js").write_bytes(OLD)
        calls = fetch(monkeypatch)
        path = ensure()
        assert open(path, "rb").read() == NEW and calls == ["https://example.invalid/lib.min.js"]
        assert os.path.basename(path) == deps_mod._cache_file_name("lib.min.js", NEW_SHA)
        assert (cache / "lib.min.js").read_bytes() == OLD   # 古いファイルは、消さない

    def test_a_good_cache_is_used_without_the_network(self, cache, monkeypatch):
        fetch(monkeypatch)
        path = ensure()
        forbid_download(monkeypatch)
        assert ensure() == path

    def test_a_corrupted_cache_is_downloaded_again(self, cache, monkeypatch):
        fetch(monkeypatch)
        path = ensure()
        with open(path, "wb") as f:
            f.write(b"tampered-and-longer")
        calls = fetch(monkeypatch)
        assert open(ensure(), "rb").read() == NEW and len(calls) == 1

    def test_a_file_with_the_right_name_but_wrong_content_is_not_trusted(self, cache, monkeypatch):
        cache.mkdir(parents=True)
        (cache / deps_mod._cache_file_name("lib.min.js", NEW_SHA)).write_bytes(OLD)
        calls = fetch(monkeypatch)
        assert open(ensure(), "rb").read() == NEW and len(calls) == 1

    def test_a_download_that_does_not_match_is_an_error_and_is_removed(self, cache, monkeypatch):
        fetch(monkeypatch, content=OLD)
        with pytest.raises(SystemExit):
            ensure()
        assert not (cache / deps_mod._cache_file_name("lib.min.js", NEW_SHA)).exists()


class TestWiring:
    """それぞれのensure_*が、固定した版のURL・SHA256で、確認つきの取得を通ること。"""

    @pytest.fixture
    def calls(self, monkeypatch):
        recorded = []
        monkeypatch.setattr(deps_mod, "_ensure_verified_js", lambda *args: recorded.append(args) or f"path-{len(recorded)}")
        for env in (deps_mod.MERMAID_JS_ENV, deps_mod.VEGA_JS_DIR_ENV, deps_mod.WAVEDROM_JS_DIR_ENV, deps_mod.BYTEFIELD_JS_DIR_ENV):
            monkeypatch.delenv(env, raising=False)
        return recorded

    def test_mermaid(self, calls):
        deps_mod.ensure_mermaid_js()
        assert calls == [(deps_mod.MERMAID_JS_URL, deps_mod.MERMAID_JS_SHA256, "mermaid", "mermaid.min.js")]

    def test_vega(self, calls):
        deps_mod.ensure_vega_js()
        assert [(c[0], c[1]) for c in calls] == [(deps_mod.VEGA_JS_URL, deps_mod.VEGA_JS_SHA256),
                                                (deps_mod.VEGA_LITE_JS_URL, deps_mod.VEGA_LITE_JS_SHA256)]

    def test_wavedrom(self, calls):
        deps_mod.ensure_wavedrom_js()
        assert [(c[0], c[1]) for c in calls] == [(deps_mod.WAVEDROM_SKIN_URL, deps_mod.WAVEDROM_SKIN_SHA256),
                                                (deps_mod.WAVEDROM_JS_URL, deps_mod.WAVEDROM_JS_SHA256)]

    def test_bytefield(self, calls):
        deps_mod.ensure_bytefield_js()
        assert calls == [(deps_mod.BYTEFIELD_JS_URL, deps_mod.BYTEFIELD_JS_SHA256, "bytefield", "lib.js")]


def test_a_bundled_file_is_still_used_without_any_check(tmp_path, monkeypatch):
    bundled = tmp_path / "mermaid.min.js"
    bundled.write_bytes(b"anything")
    monkeypatch.setenv(deps_mod.MERMAID_JS_ENV, str(bundled))
    forbid_download(monkeypatch)
    assert deps_mod.ensure_mermaid_js() == str(bundled)
