"""config.yamlの未知キー検証（#309）のテスト。

`deep_update()`は、読み込んだYAML/JSONをそのまま既定値へマージするだけで、未知のキー・
スペルミス・置き場所の間違いを検証しない。1文字間違えても、エラーも警告も出ずに黙って既定動作へ
フォールバックしてしまう問題（Quartoの「設定がどこに効くか分からない」失敗、#308）を防ぐため、
トップレベル・document・output・template・inputs・pluginsの各ブロックの未知キーをFail-fastで
検出する（`_validate_config_keys`/`_collect_unknown_keys`、config.py）。"""
import pytest

from text_compositor import diagnostics
from text_compositor.config import load_config_file


def _write_config(tmp_path, yaml_text):
    path = tmp_path / "text-compositor.config.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return str(path)


class TestValidConfigsAreUnaffected:
    def test_a_config_using_only_known_keys_loads_without_error(self, tmp_path):
        path = _write_config(tmp_path, (
            "document:\n"
            "  title: T\n"
            "  diagnostics:\n"
            "    line_mapping: block\n"
            "output:\n"
            "  filename: out.pdf\n"
            "  dir: outputs\n"
            "template:\n"
            "  path: template\n"
            "inputs:\n"
            "  dir: inputs\n"
            "plugins:\n"
            "  plantuml_auto_download: true\n"
            "  structurizr: true\n"
            "chapters:\n"
            "  - a.md\n"
            "variables:\n"
            "  FOO: bar\n"
        ))
        config = load_config_file(path)
        assert config["document"]["title"] == "T"

    def test_a_minimal_config_with_only_chapters_loads_without_error(self, tmp_path):
        path = _write_config(tmp_path, "chapters:\n  - a.md\n")
        load_config_file(path)


class TestUnknownTopLevelKey:
    def test_a_typo_at_the_top_level_is_fail_fast(self, tmp_path):
        # "chapters"のtypo。plugins:の外側に置き間違えた場合も同じ経路で捕まる。
        path = _write_config(tmp_path, "chapter:\n  - a.md\n")
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                load_config_file(path)
        errors = [d.message for d in c.items if d.severity == "error"]
        assert any("chapter" in m and "unknown key" in m for m in errors)


class TestUnknownPluginsKey:
    def test_a_typo_in_plugins_is_fail_fast_with_a_suggestion(self, tmp_path):
        path = _write_config(tmp_path, (
            "chapters:\n  - a.md\n"
            "plugins:\n"
            "  structurizr_auto_downlaod: true\n"  # 意図的なtypo（issue本文の例）
        ))
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                load_config_file(path)
        errors = [d.message for d in c.items if d.severity == "error"]
        assert any("plugins.structurizr_auto_downlaod" in m for m in errors)
        assert any("structurizr_auto_download" in m for m in errors)   # 近い既知キー名の提案

    def test_a_correct_plugins_key_does_not_error(self, tmp_path):
        path = _write_config(tmp_path, (
            "chapters:\n  - a.md\n"
            "plugins:\n"
            "  structurizr_auto_download: true\n"
        ))
        load_config_file(path)   # 例外を出さない


class TestUnknownKeyInOtherBlocks:
    @pytest.mark.parametrize("block,bad_key", [
        ("document", "titel"),
        ("output", "filenam"),
        ("template", "paht"),
        ("inputs", "dirs"),
    ])
    def test_a_typo_in_a_known_block_is_fail_fast(self, tmp_path, block, bad_key):
        path = _write_config(tmp_path, f"chapters:\n  - a.md\n{block}:\n  {bad_key}: x\n")
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                load_config_file(path)
        errors = [d.message for d in c.items if d.severity == "error"]
        assert any(f"{block}.{bad_key}" in m and "unknown key" in m for m in errors)


class TestMultipleUnknownKeysAreReportedTogether:
    def test_every_bad_key_is_reported_before_exiting(self, tmp_path):
        path = _write_config(tmp_path, (
            "chapters:\n  - a.md\n"
            "document:\n  titel: x\n"
            "plugins:\n  plantuml_auto_downlaod: true\n"
        ))
        with pytest.raises(SystemExit):
            with diagnostics.collect() as c:
                load_config_file(path)
        errors = [d.message for d in c.items if d.severity == "error"]
        assert any("document.titel" in m for m in errors)
        assert any("plugins.plantuml_auto_downlaod" in m for m in errors)
        assert len(errors) == 2
