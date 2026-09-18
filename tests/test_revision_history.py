"""改版履歴ページ（document.revision_history、#56）のリグレッションテスト。"""
import datetime

import pytest

import text_compositor.build as build


def resolve(entries):
    return build._resolve_revision_history({"revision_history": entries})


class TestResolve:
    def test_absent_or_empty_disables_the_page(self):
        assert build._resolve_revision_history({}) is None
        assert resolve([]) is None

    def test_fills_missing_keys_with_empty_strings(self):
        assert resolve([{"version": "1.0", "description": "初版"}]) == [
            {"version": "1.0", "date": "", "description": "初版", "author": ""}]

    def test_values_are_stringified_including_yaml_dates(self):
        out = resolve([{"version": 2, "date": datetime.date(2026, 8, 1), "description": None}])
        assert out == [{"version": "2", "date": "2026-08-01", "description": "", "author": ""}]

    def test_order_is_preserved(self):
        out = resolve([{"version": "1.0"}, {"version": "1.1"}])
        assert [e["version"] for e in out] == ["1.0", "1.1"]

    @pytest.mark.parametrize("bad", [
        "1.0",
        {"version": "1.0"},
        ["1.0"],
        [{"version": "1", "discription": "typo"}],
        [{}],
        [{"version": " ", "description": ""}],
    ])
    def test_invalid_definitions_are_fatal(self, bad, capsys):
        with pytest.raises(SystemExit) as e:
            resolve(bad)
        assert e.value.code == 1
        assert "revision_history" in capsys.readouterr().out


class TestTypstArg:
    def test_none_passes_no_argument(self):
        # 引数を持たない既存の独自テンプレートとの互換のため、引数行自体を出さない
        assert build._revision_history_typst_arg(None) == ""

    def test_single_entry_is_still_an_array(self):
        arg = build._revision_history_typst_arg(resolve([{"version": "1.0"}]))
        assert arg == '  revision_history: ((version: "1.0", date: "", description: "", author: ""),),\n'

    def test_multiple_entries(self):
        arg = build._revision_history_typst_arg(resolve([{"version": "1.0"}, {"version": "1.1"}]))
        assert arg.count("(version:") == 2

    def test_quotes_backslashes_and_markup_are_escaped_as_string_data(self):
        arg = build._revision_history_typst_arg(resolve([{"description": 'say "hi" \\ #x *y*'}]))
        assert 'description: "say \\"hi\\" \\\\ #x *y*"' in arg

    def test_newlines_become_escape_sequences_not_raw_line_breaks(self):
        arg = build._revision_history_typst_arg(resolve([{"description": "a\r\nb\nc"}]))
        assert 'description: "a\\nb\\nc"' in arg
        assert arg.count("\n") == 1  # 引数行末の改行のみ


class TestPreamble:
    def build_preamble(self, doc):
        preamble, *_ = build._build_document_preamble({"document": doc}, "/t.typ", True, "/proj", "/proj")
        return preamble

    def test_argument_is_passed_to_conf_when_configured(self):
        pre = self.build_preamble({"revision_history": [{"version": "1.0", "description": "初版"}]})
        assert 'revision_history: ((version: "1.0", date: "", description: "初版", author: ""),),' in pre

    def test_no_argument_when_not_configured(self):
        assert "revision_history" not in self.build_preamble({})
        assert "revision_history" not in self.build_preamble({"revision_history": []})

    def test_argument_is_placed_among_the_optional_arguments(self):
        pre = self.build_preamble({"toc": True, "revision_history": [{"version": "1"}]})
        assert pre.index("toc: true") < pre.index("revision_history:") < pre.index("graphviz:")
