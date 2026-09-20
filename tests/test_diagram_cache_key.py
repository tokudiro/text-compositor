"""図のキャッシュキーを複合ハッシュにする設計（#26）のリグレッションテスト。"""
import os

import text_compositor.renderer as renderer_mod
from text_compositor.deps import D2_RELEASE
from text_compositor.renderer import TypstRenderer, _diagram_cache_key


class TestDiagramCacheKey:
    def test_same_inputs_give_same_key(self):
        assert _diagram_cache_key("d2", "v0.9.0", "a -> b") == _diagram_cache_key("d2", "v0.9.0", "a -> b")

    def test_tool_version_changes_key(self):
        assert _diagram_cache_key("d2", "v0.9.0", "a -> b") != _diagram_cache_key("d2", "v0.9.1", "a -> b")

    def test_code_changes_key(self):
        assert _diagram_cache_key("d2", "v0.9.0", "a -> b") != _diagram_cache_key("d2", "v0.9.0", "a -> c")

    def test_kind_changes_key(self):
        assert _diagram_cache_key("d2", "v1", "x") != _diagram_cache_key("plantuml", "v1", "x")

    def test_element_boundary_does_not_collide(self):
        # 連結すると同じ文字列になる組み合わせでも、要素の境界が違えば別キーになる
        assert _diagram_cache_key("d2", "v1", "2x") != _diagram_cache_key("d2", "v12", "x")


class TestDiagramCachePath:
    def test_path_contains_kind_and_key(self, tmp_path):
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        path, digest = renderer._diagram_cache_path("plantuml", "ver", "@startuml\n@enduml\n")
        assert os.path.dirname(path) == str(tmp_path / ".text-compositor" / "cache")
        assert os.path.basename(path) == f"plantuml_{digest}.svg"
        assert os.path.isdir(os.path.dirname(path))

    def test_d2_version_uses_system_d2_output(self, tmp_path, monkeypatch):
        monkeypatch.setattr(renderer_mod, "find_system_d2", lambda: "/usr/bin/d2")
        monkeypatch.setattr(renderer_mod, "_system_d2_version", lambda _bin: "v9.9.9")
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._d2_version() == "v9.9.9"

    def test_d2_version_falls_back_to_pinned_release_without_downloading(self, tmp_path, monkeypatch):
        monkeypatch.setattr(renderer_mod, "find_system_d2", lambda: None)
        monkeypatch.setattr(renderer_mod, "ensure_d2_binary", lambda: (_ for _ in ()).throw(AssertionError("must not download")))
        renderer = TypstRenderer(base_dir=str(tmp_path), line_mapping="off")
        assert renderer._d2_version() == D2_RELEASE
