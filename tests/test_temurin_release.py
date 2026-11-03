"""JRE（Temurin）の、プラットフォームごとのリリースの決め方（text_compositor/deps.py。#255）のテスト。"""
import pytest

from text_compositor import deps


@pytest.mark.parametrize("key", sorted(deps.TEMURIN_JRE_ASSETS))
def test_every_platform_has_a_release_that_matches_its_file_name(key):
    release, base_url, top_dir = deps.temurin_jre_release(key)
    filename = deps.TEMURIN_JRE_ASSETS[key][0]
    # `jdk-21.0.13+9` -> ファイル名の`21.0.13_9`
    assert release.removeprefix("jdk-").replace("+", "_") in filename
    assert top_dir == f"{release}-jre"
    # URLの`+`は、`%2B`にする（GitHubのリリースのタグ）
    assert base_url.endswith("/") and "+" not in base_url and release.replace("+", "%2B") in base_url


def test_the_default_release_is_the_pinned_one():
    release, base_url, top_dir = deps.temurin_jre_release(("linux", "x86_64"))
    assert (release, base_url, top_dir) == (deps.TEMURIN_JRE_RELEASE, deps.TEMURIN_JRE_BASE_URL, deps.TEMURIN_JRE_TOP_DIR)


def test_windows_arm_stays_on_the_previous_release_because_the_new_one_has_no_build_for_it():
    release, _, top_dir = deps.temurin_jre_release(("win32", "aarch64"))
    assert release == "jdk-21.0.12.1+1" and top_dir == "jdk-21.0.12.1+1-jre"
    assert release != deps.TEMURIN_JRE_RELEASE


def test_the_overrides_name_only_known_platforms():
    assert set(deps.TEMURIN_JRE_RELEASE_OVERRIDES) <= set(deps.TEMURIN_JRE_ASSETS)
