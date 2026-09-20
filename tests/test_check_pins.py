"""週次の固定値確認（.github/scripts/check-pins.py。#240）のテスト。ネットワークには接続しない。"""
import importlib.util
import os

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".github", "scripts", "check-pins.py")


@pytest.fixture(scope="module")
def check_pins():
    spec = importlib.util.spec_from_file_location("check_pins", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_pins_finds_every_pin_in_the_sources(check_pins):
    """deps.py・build-dist.js・_common.typの書き方を変えたときに、確認が空振りにならないための番人。"""
    pins = check_pins.read_pins()
    missing = [name for name, version in pins.items() if version is None]
    assert missing == []
    for name in ("Mermaid", "PlantUML", "D2", "Temurin JRE 21", "Noto Sans JP", "組込版Python"):
        assert name in pins
    assert any(name.startswith("Typstパッケージ ") for name in pins)


def test_read_pins_matches_the_source_constants(check_pins):
    from text_compositor import deps
    pins = check_pins.read_pins()
    assert f"v{pins['D2']}" == deps.D2_RELEASE
    assert f"jdk-{pins['Temurin JRE 21']}" == deps.TEMURIN_JRE_RELEASE


@pytest.mark.parametrize("latest, current, expected", [
    ("1.2026.8", "1.2026.6", True),
    ("21.0.12.1+1", "21.0.12+8", True),    # 桁が多い版は、新しい（ビルド番号の大小より先に比べる）
    ("21.0.12+8", "21.0.12.1+1", False),
    ("3.14.7", "3.14.7", False),
    ("3.14.10", "3.14.9", True),           # 文字列ではなく、数として比べる
    ("v0.9.1", "0.9.0", True),
    ("2.004", "2.004", False),
])
def test_is_newer(check_pins, latest, current, expected):
    assert check_pins.is_newer(latest, current) is expected


def test_is_major_update(check_pins):
    assert check_pins.is_major_update("12.0.0", "11.16.1")
    assert not check_pins.is_major_update("11.17.0", "11.16.1")


def test_build_report_counts_updates_and_failures(check_pins):
    pins = {"Mermaid": "11.16.1", "D2": "0.9.0", "PlantUML": "1.2026.6"}
    latest = {
        "Mermaid": ("12.0.0", ""),
        "D2": ("0.9.0", ""),
        "PlantUML": TimeoutError("timed out"),
    }
    report, updates, failures = check_pins.build_report(pins, latest)
    assert (updates, failures) == (1, 1)
    assert "**12.0.0**" in report and "メジャー更新" in report
    assert "確認できず（TimeoutError: timed out）" in report


def test_build_report_without_differences(check_pins):
    report, updates, failures = check_pins.build_report({"D2": "0.9.0"}, {"D2": ("0.9.0", "")})
    assert (updates, failures) == (0, 0)
    assert "最新" in report
