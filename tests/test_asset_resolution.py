"""画像パス解決（_resolve_asset、_resolve_project_image_path）のリグレッションテスト（#96）。

いずれも仕様9章のFail-fast方針どおり、画像欠損時はフォールバックせず即エラー終了する。
"""
import base64
import os

import pytest

from text_compositor.config import _resolve_project_image_path
from text_compositor.renderer import TypstRenderer


class TestResolveAsset:
    """TypstRenderer._resolve_asset(): Markdownファイル基準の相対パスを、
    temp_build.typの置き場所に依存しないtypst_root起点のルート絶対パスへ変換する。"""

    def _renderer(self, tmp_path):
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        renderer.current_dir = str(tmp_path)
        renderer.current_file = str(tmp_path / "doc.md")
        return renderer

    def test_relative_path_resolves_to_root_absolute_path(self, tmp_path):
        (tmp_path / "images").mkdir()
        (tmp_path / "images" / "a.png").write_bytes(b"\x89PNG")
        renderer = self._renderer(tmp_path)
        assert renderer._resolve_asset("images/a.png") == "/images/a.png"

    def test_root_absolute_path_is_passed_through_unresolved(self, tmp_path):
        renderer = self._renderer(tmp_path)
        assert renderer._resolve_asset("/already/absolute.png") == "/already/absolute.png"

    def test_url_is_passed_through_unresolved(self, tmp_path):
        renderer = self._renderer(tmp_path)
        assert renderer._resolve_asset("https://example.com/a.png") == "https://example.com/a.png"

    def test_missing_file_exits(self, tmp_path):
        renderer = self._renderer(tmp_path)
        with pytest.raises(SystemExit):
            renderer._resolve_asset("missing.png")

    def test_resolves_relative_to_typst_root_not_base_dir(self, tmp_path):
        """base_dir（原稿側）とtypst_root（--rootに相当）が異なる場合、ルート絶対パスは
        typst_root基準で組み立てる（5章）。"""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "a.png").write_bytes(b"\x89PNG")
        renderer = TypstRenderer(line_mapping="off", base_dir=str(project_dir), typst_root=str(tmp_path))
        renderer.current_dir = str(project_dir)
        renderer.current_file = str(project_dir / "doc.md")
        assert renderer._resolve_asset("a.png") == "/project/a.png"


class TestResolveDataUriAsset:
    """`data:`のURI画像は、キャッシュへ書き出してから解決する。PDF（Typstの#image()）は、data:のURIを
    直接受け取れないため（HTMLと挙動をそろえ、`Image not found`のエラーにしない。#238）。"""

    PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10).decode()

    def _renderer(self, tmp_path):
        renderer = TypstRenderer(line_mapping="off", base_dir=str(tmp_path), typst_root=str(tmp_path))
        renderer.current_dir = str(tmp_path)
        renderer.current_file = str(tmp_path / "doc.md")
        return renderer

    def test_data_uri_is_written_to_the_cache_and_resolved(self, tmp_path):
        renderer = self._renderer(tmp_path)
        result = renderer._resolve_asset(f"data:image/png;base64,{self.PNG_BASE64}")
        assert result.startswith("/.text-compositor/cache/datauri_") and result.endswith(".png")
        cache_path = tmp_path / result.lstrip("/")
        assert cache_path.is_file()
        assert cache_path.read_bytes() == base64.b64decode(self.PNG_BASE64)

    def test_the_same_data_uri_reuses_the_cached_file(self, tmp_path):
        renderer = self._renderer(tmp_path)
        src = f"data:image/png;base64,{self.PNG_BASE64}"
        first = renderer._resolve_asset(src)
        cache_path = tmp_path / first.lstrip("/")
        mtime = cache_path.stat().st_mtime_ns
        second = renderer._resolve_asset(src)
        assert second == first
        assert cache_path.stat().st_mtime_ns == mtime

    def test_unsupported_mime_type_exits(self, tmp_path):
        renderer = self._renderer(tmp_path)
        with pytest.raises(SystemExit):
            renderer._resolve_asset("data:application/pdf;base64,AAAA")

    def test_non_base64_data_uri_exits(self, tmp_path):
        renderer = self._renderer(tmp_path)
        with pytest.raises(SystemExit):
            renderer._resolve_asset("data:image/png,not-base64-encoded")


class TestResolveProjectImagePath:
    """document.background/logo、chapters[].background/logo（project_dir基準）の解決。"""

    def test_none_path_returns_none(self, tmp_path):
        assert _resolve_project_image_path(None, str(tmp_path), str(tmp_path), "Logo") is None

    def test_existing_file_resolves_to_root_absolute_path(self, tmp_path):
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")
        result = _resolve_project_image_path("logo.png", str(tmp_path), str(tmp_path), "Logo")
        assert result == "/logo.png"

    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            _resolve_project_image_path("missing.png", str(tmp_path), str(tmp_path), "Logo")

    def test_resolves_relative_to_typst_root_not_base_dir(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "logo.png").write_bytes(b"\x89PNG")
        result = _resolve_project_image_path("logo.png", str(project_dir), str(tmp_path), "Logo")
        assert result == "/project/logo.png"
