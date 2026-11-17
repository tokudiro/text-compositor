import os
import sys

import pytest

# text_compositor/ パッケージはリポジトリ直下にあるため、pipインストールしていない
# 開発環境でも tests/配下からimportできるよう、リポジトリ直下をsys.pathへ追加する（#111）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cached_java():
    """ダウンロードせずに、使えるJavaを探す（システムのJava 11+、または、取得済みのTemurin JRE）。"""
    from text_compositor import deps
    java = deps.find_system_java()
    if java:
        return java
    try:
        key = deps._temurin_platform_key()
        asset = deps.TEMURIN_JRE_ASSETS.get(key)
        if asset is None:
            return None
        _release, _base_url, top_dir = deps.temurin_jre_release(key)
        path = os.path.join(deps._jre_cache_root(), top_dir, *asset[3])
        return path if os.path.exists(path) else None
    except Exception:
        return None


def _cached_jar():
    from text_compositor import deps
    path = os.path.join(deps._user_cache_dir(), "plantuml", os.path.basename(deps.PLANTUML_JAR_URL))
    return path if os.path.exists(path) else None


@pytest.fixture
def real_tools():
    """実際のJavaとplantuml.jarで確かめるテスト用。(javaのパス, jarのパス)を返す。
    どちらかがキャッシュに無いときは、ダウンロードせずに、スキップする。"""
    java, jar = _cached_java(), _cached_jar()
    if not java or not jar:
        pytest.skip("Java and plantuml.jar are not cached (no download in tests)")
    return java, jar


@pytest.fixture(autouse=True)
def _no_github_actions_env(monkeypatch):
    """このプロジェクト自身のCIもGitHub Actions上（GITHUB_ACTIONS=true）で動くため、これらの
    環境変数を明示的に未設定にしない限り、diagnostics.pyのGitHub Actionsアノテーション出力（#29）が
    テスト実行環境によって意図せず有効になり、標準出力を厳密比較する既存テストがローカルでは通り
    CI上だけ落ちる、という不安定な状態になる。個別のテストがmonkeypatch.setenvで上書きすればよい。"""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
