"""設定ファイルの章の一覧（chapter_list.py・ワーカーの`list_chapters`、#373）のテスト。"""
import json
import os
import time

import pytest

from text_compositor import worker
from text_compositor.chapter_list import ChapterListError, list_chapters


def write_config(tmp_path, text, name="text-compositor.config.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def names(items):
    return [(i["name"], [c["name"] for c in i["children"]]) if i["kind"] == "section" else i["name"] for i in items]


class TestListChapters:
    def test_chapters_keep_the_written_order_not_the_file_name_order(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - b.md\n  - a.md\n  - c.md\n")
        assert names(list_chapters(config)["items"]) == ["b.md", "a.md", "c.md"]

    def test_file_paths_are_resolved_from_inputs_dir_which_defaults_to_inputs(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - a.md\n")
        assert list_chapters(config)["items"][0]["path"] == str(tmp_path / "inputs" / "a.md")

    def test_inputs_dir_in_the_config_is_used(self, tmp_path):
        config = write_config(tmp_path, 'inputs:\n  dir: "."\nchapters:\n  - sub/a.md\n')
        assert list_chapters(config)["items"][0]["path"] == os.path.normpath(str(tmp_path / "sub" / "a.md"))

    def test_a_mapping_with_file_is_a_chapter(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - file: a.md\n    landscape: true\n")
        assert names(list_chapters(config)["items"]) == ["a.md"]

    def test_aggregate_is_not_listed(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - a.md\n  - aggregate: testcases\n  - b.md\n")
        result = list_chapters(config)
        assert names(result["items"]) == ["a.md", "b.md"] and result["warnings"] == []

    def test_a_section_holds_its_chapters(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - a.md\n  - section: Maintenance\n    chapters:\n      - b.md\n      - file: c.md\n")
        assert names(list_chapters(config)["items"]) == ["a.md", ("Maintenance", ["b.md", "c.md"])]

    def test_nested_sections_are_skipped_with_a_warning(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - section: A\n    chapters:\n      - section: B\n        chapters: [x.md]\n      - y.md\n")
        result = list_chapters(config)
        assert names(result["items"]) == [("A", ["y.md"])] and "Nested sections" in result["warnings"][0]

    @pytest.mark.parametrize("entry", ["42", "{}", "{section: '', chapters: [a.md]}", "{section: S}", "[a.md]"])
    def test_invalid_entries_are_skipped_with_a_warning_and_do_not_stop_the_rest(self, tmp_path, entry):
        config = write_config(tmp_path, f"chapters:\n  - {entry}\n  - ok.md\n")
        result = list_chapters(config)
        assert names(result["items"]) == ["ok.md"] and len(result["warnings"]) == 1

    def test_a_json_config_is_read(self, tmp_path):
        config = write_config(tmp_path, json.dumps({"chapters": ["a.md", {"file": "b.md"}]}), name="text-compositor.config.json")
        assert names(list_chapters(config)["items"]) == ["a.md", "b.md"]

    @pytest.mark.parametrize("text", ["", "chapters: []\n", "title: x\n", "chapters: a.md\n", "- a\n- b\n",
                                      "chapters: [a.md\n", "inputs: {dir: 3}\nchapters: [a.md]\n"])
    def test_an_unreadable_config_raises_a_message_and_never_exits(self, tmp_path, text):
        with pytest.raises(ChapterListError):
            list_chapters(write_config(tmp_path, text))

    def test_a_missing_config_raises(self, tmp_path):
        with pytest.raises(ChapterListError, match="not found"):
            list_chapters(str(tmp_path / "none.yaml"))

    def test_the_chapter_files_are_never_read(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - missing.md\n")
        assert names(list_chapters(config)["items"]) == ["missing.md"]

    def test_a_thousand_chapters_are_listed_quickly(self, tmp_path):
        lines = "".join(f"  - ch{i:04d}.md\n" for i in range(1000))
        config = write_config(tmp_path, "chapters:\n" + lines)
        started = time.perf_counter()
        result = list_chapters(config)
        elapsed = time.perf_counter() - started
        assert len(result["items"]) == 1000 and elapsed < 1.0


class TestWorkerListChapters:
    class NoSession:
        pass

    def request(self, params):
        return worker.handle_request(self.NoSession(), {"id": 7, "method": "list_chapters", "params": params})

    def test_returns_the_items(self, tmp_path):
        config = write_config(tmp_path, "chapters:\n  - a.md\n")
        response = self.request({"path": config})
        assert response["id"] == 7 and response["ok"] is True
        assert names(response["result"]["items"]) == ["a.md"] and response["result"]["warnings"] == []

    def test_a_broken_config_is_a_protocol_error_and_the_worker_survives(self, tmp_path):
        response = self.request({"path": write_config(tmp_path, "chapters: [a.md\n")})
        assert response["ok"] is False and response["error"]["code"] == "bad_config" and "_shutdown" not in response

    def test_path_is_required(self):
        assert self.request({})["error"]["code"] == "bad_request"
