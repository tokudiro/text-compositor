"""`aggregate`章の表（列の設定#65、テスト仕様と結果の結合#66）をTypstへ変換する。"""
import os
import re
import sys
import json
from collections import Counter

from text_compositor.config import yaml
from text_compositor.log import _error, _warn
from text_compositor.typst_literal import insert_soft_break_hints

# columns省略時の列。#65以前の固定の5列と、見出し・幅・揃え・描画を同じにする（後方互換）。
_DEFAULT_AGGREGATE_COLUMNS = [
    {"key": "id", "title": "ID", "width": "auto", "align": "center", "markdown": False},
    {"key": "title", "title": "Title", "width": "1fr", "align": "left", "markdown": False},
    {"key": "priority", "title": "Priority", "width": "auto", "align": "center", "markdown": False},
    {"key": "steps", "title": "Steps", "width": "2fr", "align": "left", "markdown": True},
    {"key": "expected", "title": "Expected", "width": "2fr", "align": "left", "markdown": True},
]
_AGGREGATE_ALIGNS = ("left", "center", "right")
_AGGREGATE_WIDTH_RE = re.compile(r"auto|\d+(\.\d+)?fr")
_JOIN_KEYS = ("aggregate", "key", "runs", "missing", "columns", "skip_missing", "summary")
_JOIN_RUNS = ("latest", "all")
_SUMMARY_KEYS = ("show", "position", "title", "by", "order", "missing_label", "rate", "classes", "group_by")
_SUMMARY_CLASSES = ("pass", "fail", "pending", "excluded")
_UNFILLED_LABEL = "（未記入）"   # 集計で、`by`のキーに値が無い結果を数える区分

def _parse_aggregate_columns(value, where):
    """aggregateの`columns`（#65）を検証し、正規化した列のリストを返す。省略（None）は既定の5列。
    誤りは描画の前にFail-fastで報告する（keyなし・width/alignの不正・keyの重複・空のリスト）。"""
    if value is None:
        return [dict(c) for c in _DEFAULT_AGGREGATE_COLUMNS]
    if not isinstance(value, list) or not value:
        _error(f"{where}: columns must be a non-empty list.")
        sys.exit(1)
    columns, seen = [], set()
    for i, col in enumerate(value, 1):
        label = f"{where}: columns[{i}]"
        if not isinstance(col, dict):
            _error(f"{label} must be a mapping with a 'key'.")
            sys.exit(1)
        unknown = sorted(str(k) for k in col if k not in ("key", "title", "width", "align", "markdown"))
        if unknown:
            _error(f"{label}: unknown key(s): {', '.join(unknown)}. Allowed: key, title, width, align, markdown.")
            sys.exit(1)
        key = col.get("key")
        if not isinstance(key, str) or not key:
            _error(f"{label}: 'key' is required (a non-empty string).")
            sys.exit(1)
        if key in seen:
            _error(f"{label}: duplicate key {key!r}.")
            sys.exit(1)
        seen.add(key)
        width = col.get("width", "1fr")
        if not isinstance(width, str) or not _AGGREGATE_WIDTH_RE.fullmatch(width):
            _error(f"{label}: width must be 'auto' or a fraction such as '1fr' or '2fr' (got {width!r}).")
            sys.exit(1)
        align = col.get("align", "left")
        if align not in _AGGREGATE_ALIGNS:
            _error(f"{label}: align must be one of {', '.join(_AGGREGATE_ALIGNS)} (got {align!r}).")
            sys.exit(1)
        markdown = col.get("markdown", False)
        if not isinstance(markdown, bool):
            _error(f"{label}: markdown must be true or false (got {markdown!r}).")
            sys.exit(1)
        columns.append({"key": key, "title": str(col.get("title", key)), "width": width,
                        "align": align, "markdown": markdown})
    return columns

def _parse_aggregate_join(value, where):
    """aggregateの`join`（#66）を検証し、正規化したdictを返す。結果の列（columns）は必須で、
    既定の列は無い（結果のキーは、利用者ごとに違うため）。"""
    where = f"{where}: join"
    if not isinstance(value, dict):
        _error(f"{where} must be a mapping.")
        sys.exit(1)
    unknown = sorted(str(k) for k in value if k not in _JOIN_KEYS)
    if unknown:
        _error(f"{where}: unknown key(s): {', '.join(unknown)}. Allowed: {', '.join(_JOIN_KEYS)}.")
        sys.exit(1)
    directory = value.get("aggregate")
    if not isinstance(directory, str) or not directory:
        _error(f"{where}: 'aggregate' is required (the results directory).")
        sys.exit(1)
    key = value.get("key", "id")
    if not isinstance(key, str) or not key:
        _error(f"{where}: key must be a non-empty string (got {key!r}).")
        sys.exit(1)
    runs = value.get("runs", "latest")
    if runs not in _JOIN_RUNS:
        _error(f"{where}: runs must be one of {', '.join(_JOIN_RUNS)} (got {runs!r}).")
        sys.exit(1)
    missing = value.get("missing", "")
    if not isinstance(missing, str):
        _error(f"{where}: missing must be a string (got {missing!r}).")
        sys.exit(1)
    if value.get("columns") is None:
        _error(f"{where}: 'columns' is required (the columns taken from the results).")
        sys.exit(1)
    skip_missing = value.get("skip_missing", False)
    if not isinstance(skip_missing, bool):
        _error(f"{where}: skip_missing must be true or false (got {skip_missing!r}).")
        sys.exit(1)
    summary = _parse_summary(value.get("summary"), where)
    return {"aggregate": directory, "key": key, "runs": runs, "missing": missing,
            "columns": _parse_aggregate_columns(value["columns"], where),
            "skip_missing": skip_missing, "summary": summary}

def _parse_summary(value, where):
    """`join.summary`（集計の表示、#66）を検証し、正規化したdictを返す。省略・falseでも、`by`と
    `missing_label`の既定値は必要（skip_missingが使う）ため、`show`だけがfalseのdictを返す。
    rate: trueなのにclasses.passが無い、同じ値が複数の区分にある、などは、描画の前にFail-fastで止める。"""
    where = f"{where}.summary"
    if value is None or value is False:
        value = {"show": False}
    elif value is True:
        value = {}
    elif not isinstance(value, dict):
        _error(f"{where} must be true, false or a mapping.")
        sys.exit(1)
    unknown = sorted(str(k) for k in value if k not in _SUMMARY_KEYS)
    if unknown:
        _error(f"{where}: unknown key(s): {', '.join(unknown)}. Allowed: {', '.join(_SUMMARY_KEYS)}.")
        sys.exit(1)
    cfg = {"show": value.get("show", True), "position": value.get("position", "bottom"),
           "title": value.get("title", "集計"), "by": value.get("by", "status"),
           "order": value.get("order", []), "missing_label": value.get("missing_label", "未実施"),
           "rate": value.get("rate", False), "group_by": value.get("group_by")}
    for name in ("show", "rate"):
        if not isinstance(cfg[name], bool):
            _error(f"{where}: {name} must be true or false (got {cfg[name]!r}).")
            sys.exit(1)
    if cfg["position"] not in ("top", "bottom"):
        _error(f"{where}: position must be top or bottom (got {cfg['position']!r}).")
        sys.exit(1)
    for name in ("title", "by", "missing_label"):
        if not isinstance(cfg[name], str):
            _error(f"{where}: {name} must be a string (got {cfg[name]!r}).")
            sys.exit(1)
    if not cfg["by"] or not cfg["missing_label"]:
        _error(f"{where}: by and missing_label must not be empty.")
        sys.exit(1)
    if cfg["group_by"] is not None and (not isinstance(cfg["group_by"], str) or not cfg["group_by"]):
        _error(f"{where}: group_by must be a non-empty string (got {cfg['group_by']!r}).")
        sys.exit(1)
    cfg["order"] = _string_list(cfg["order"], f"{where}: order")
    classes_raw = value.get("classes") or {}
    if not isinstance(classes_raw, dict):
        _error(f"{where}: classes must be a mapping.")
        sys.exit(1)
    unknown = sorted(str(k) for k in classes_raw if k not in _SUMMARY_CLASSES)
    if unknown:
        _error(f"{where}: unknown class(es): {', '.join(unknown)}. Allowed: {', '.join(_SUMMARY_CLASSES)}.")
        sys.exit(1)
    classes, owner = {}, {}
    for name, values in classes_raw.items():
        classes[name] = _string_list(values, f"{where}: classes.{name}")
        for v in classes[name]:
            if owner.setdefault(v, name) != name:
                _error(f"{where}: the value {v!r} is in both classes.{owner[v]} and classes.{name}.")
                sys.exit(1)
    cfg["classes"] = classes
    if cfg["rate"] and not classes.get("pass"):
        _error(f"{where}: rate: true needs classes.pass (which values count as passed).")
        sys.exit(1)
    return cfg

def _string_list(value, where):
    if not isinstance(value, list) or not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
        _error(f"{where} must be a list of values.")
        sys.exit(1)
    return [str(v) for v in value]

def _aggregate_cell(renderer, value, column, tc_path):
    """aggregateの1セル分のTypst断片を返す。キーが無い・nullは空欄。markdown: trueはMarkdownとして描画し、
    リストは各要素を改行で連結する（#65以前のsteps/expectedと同じ）。それ以外は文字をそのまま出し、
    リストは読点で連結する。幅がautoでない列には、長い識別子の折り返し用ソフト改行点を入れる（#269）。"""
    if value is None:
        return ""
    if column["markdown"]:
        text = "\n".join(str(v) for v in value) if isinstance(value, list) else str(value)
        return renderer.render(text, filepath=tc_path).strip()
    text = "、".join(str(v) for v in value) if isinstance(value, list) else str(value)
    if column["width"] != "auto":
        text = insert_soft_break_hints(text)
    return renderer.escape_typst(text)

def _load_records(agg_path):
    """ディレクトリ直下の.yaml/.yml/.jsonを名前順に読み、[(パス, dict), ...]を返す。構文エラーのファイルと、
    トップレベルがマッピングでないファイルは、警告して飛ばす。"""
    records = []
    for name in sorted(f for f in os.listdir(agg_path) if f.endswith(('.yaml', '.yml', '.json'))):
        path = os.path.join(agg_path, name)
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = (json.load(f) if name.endswith('.json') else yaml.safe_load(f)) or {}
            except Exception as e:
                _warn(f"Failed to parse {name}: {e}")
                continue
        if not isinstance(data, dict):
            _warn(f"Skipped {name}: the top level must be a mapping.")
            continue
        records.append((path, data))
    return records

def _result_runs(records, key):
    """結果のファイル群を、{id文字列: [実施の記録, ...]}にそろえる（#66）。実施の記録は{"data", "path"}。
    書き方1（1回=1ファイル）も、書き方2（`runs`リスト）も、同じ形になる。`runs`の外側のキーは全回の共通値で、
    各回に同じキーがあれば各回の値が優先する。並びは`tested_at`の昇順で、無い・同じときは、ファイル名順、
    `runs`内の並び順（YAMLの日付はISO形式の文字列にして比べる）。最後の1件が「最新」になる。"""
    entries = []
    for path, data in records:
        name = os.path.basename(path)
        rid = data.get(key)
        if rid is None or not str(rid).strip():
            _warn(f"Skipped result {name}: no '{key}' to match against the tests.")
            continue
        common = {k: v for k, v in data.items() if k != "runs"}
        if "runs" in data:
            runs = data["runs"]
            if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
                _warn(f"Skipped result {name}: 'runs' must be a list of mappings.")
                continue
            items = [{**common, **r, key: rid} for r in runs]
        else:
            items = [common]
        for index, item in enumerate(items):
            tested_at = "" if item.get("tested_at") is None else str(item["tested_at"])
            entries.append((str(rid), (tested_at, name, index), item, path))
    entries.sort(key=lambda e: e[1])
    by_id = {}
    for rid, (tested_at, _, _), item, path in entries:
        by_id.setdefault(rid, []).append({"data": item, "path": path, "tested_at": tested_at})
    for rid, runs in by_id.items():
        for tested_at, count in Counter(r["tested_at"] for r in runs).items():
            if count > 1:
                _warn(f"{count} result records have the same id {rid!r} and tested_at "
                      f"{tested_at or '(none)'}; they may be duplicates of one run.")
    return by_id

def _run_status(run, join):
    value = run["data"].get(join["summary"]["by"])
    return None if value is None else str(value)

def _latest_run(runs, join):
    """テストごとの「最新の1件」を返す（無ければNone）。`skip_missing: true`のときは、`by`の値が
    `missing_label`と等しい記録（再実施の予定を先に「未実施」と書いたもの）を除いてから選ぶ。
    `runs: latest`の表と集計が、この関数を共有するので、2つの数が食い違わない（#66）。"""
    if join["skip_missing"]:
        runs = [r for r in runs if _run_status(r, join) != join["summary"]["missing_label"]]
    return runs[-1] if runs else None

def _joined_rows(spec_records, results, join):
    """仕様と結果を結合した行を、[(仕様のdictまたはNone, 仕様のパス, 結果の記録またはNone), ...]で返す（#66）。
    `runs: all`は、実施の数だけ行を出し、仕様は最初の行にだけ付ける。結果が無いテストは、結果をNoneにして
    1行出す（未実施。エラーにしない）。仕様が無い結果は、警告して、最後に仕様なしで足す（黙って捨てない）。"""
    key = join["key"]
    rows, spec_ids = [], set()
    for path, data in spec_records:
        sid = None if data.get(key) is None else str(data[key])
        if sid is None:
            _warn(f"{os.path.basename(path)} has no '{key}', so it cannot be matched with results.")
        elif sid in spec_ids:
            _warn(f"Duplicate test {key} {sid!r} in the spec ({os.path.basename(path)}).")
        if sid is not None:
            spec_ids.add(sid)
        runs = results.get(sid, [])
        if join["runs"] == "latest":
            latest = _latest_run(runs, join)
            runs = [latest] if latest else []
        for i, run in enumerate(runs or [None]):
            rows.append((data if i == 0 else None, path if i == 0 else None, run))
    for rid, runs in results.items():
        if rid in spec_ids:
            continue
        _warn(f"Result for {key} {rid!r} has no matching test in the spec; added at the end of the table.")
        for run in (runs[-1:] if join["runs"] == "latest" else runs):
            rows.append((None, None, run))
    return rows

def _class_of(label, cfg):
    """集計の区分（pass/fail/pending/excluded）を返す。書かれていない値はNone（区分なし）。
    結果が無いテストの表示名（missing_label）は、classesに書かれていなければpending。"""
    for name, values in cfg["classes"].items():
        if label in values:
            return name
    return "pending" if label == cfg["missing_label"] else None

def _summary_tally(rows, cfg):
    """[(区分の表示名, 区分), ...]から、集計の1行分（合計・値ごとの件数・対象外・合格率の元）を作る。"""
    counts = Counter(label for label, _ in rows)
    classes = Counter(cls for _, cls in rows)
    return {"counts": counts, "excluded": classes["excluded"], "pass": classes["pass"],
            "fail": classes["fail"], "total": len(rows) - classes["excluded"]}

def _summary_table(spec_records, results, join, renderer):
    """集計の表（#table）と見出しのTypstコードを返す（#66）。単位はテスト（id）の数で、テストごとに「最新の
    1件」だけで数える（再実施で合計が水増しされない）。結果が無いテストはmissing_label、`by`の値が無い結果は
    （未記入）に数える。仕様が無い結果は含めない。excludedは合計に含めず、件数だけ別の列に出す。
    合格率 ＝ pass ÷ （pass＋fail）で、分母が0なら「-」。"""
    cfg, key = join["summary"], join["key"]
    tests, seen = [], set()
    for _, data in spec_records:
        sid = None if data.get(key) is None else str(data[key])
        if sid is not None:
            if sid in seen:
                continue   # 重複したidは1件に数える（警告は表の側で出している）
            seen.add(sid)
        run = _latest_run(results.get(sid, []), join) if sid is not None else None
        if run is None:
            label = cfg["missing_label"]
        else:
            label = _run_status(run, join)
            if label is None or not label.strip():
                label = _UNFILLED_LABEL
        group = None
        if cfg["group_by"]:
            gv = data.get(cfg["group_by"])
            group = _UNFILLED_LABEL if gv is None else str(gv)
        tests.append((group, label, _class_of(label, cfg)))

    # 列: orderに書いた値、続いて出てきた順（missing_labelは最後）。excludedの値は「対象外」の列にまとめる。
    seen_labels = []
    for _, label, _cls in tests:
        if label not in seen_labels:
            seen_labels.append(label)
    extras = [v for v in seen_labels if v not in cfg["order"] and v != cfg["missing_label"]]
    if cfg["missing_label"] in seen_labels and cfg["missing_label"] not in cfg["order"]:
        extras.append(cfg["missing_label"])
    labels = [v for v in cfg["order"] + extras if _class_of(v, cfg) != "excluded"]
    has_excluded = bool(cfg["classes"].get("excluded"))

    groups = []
    if cfg["group_by"]:
        for group, _l, _c in tests:
            if group not in groups:
                groups.append(group)
    lines = [(g, [(l, c) for gg, l, c in tests if gg == g]) for g in groups]
    lines.append(("全体" if cfg["group_by"] else None, [(l, c) for _g, l, c in tests]))

    headers = ([cfg["group_by"]] if cfg["group_by"] else []) + ["合計"] + labels
    if has_excluded:
        headers.append("対象外")
    if cfg["rate"]:
        headers.append("合格率")
    esc = renderer.escape_typst
    code = ""
    if cfg["title"]:
        code += f'*{esc(cfg["title"])}*\n\n'
    code += f'#table(\n  columns: ({", ".join(["auto"] * len(headers))}),\n'
    aligns = ["center"] * len(headers)
    if cfg["group_by"]:
        aligns[0] = "left"
    code += f'  align: ({", ".join(aligns)}),\n'
    code += '  stroke: 0.5pt + luma(150),\n  fill: (col, row) => if row == 0 { luma(240) } else { none },\n'
    code += '  ' + ', '.join(f'[*{esc(h)}*]' for h in headers) + ',\n'
    for name, rows in lines:
        t = _summary_tally(rows, cfg)
        cells = ([esc(name)] if cfg["group_by"] else []) + [str(t["total"])]
        cells += [str(t["counts"][v]) for v in labels]
        if has_excluded:
            cells.append(str(t["excluded"]))
        if cfg["rate"]:
            done = t["pass"] + t["fail"]
            cells.append(f'{t["pass"] / done * 100:.0f}%（{t["pass"]}/{done}）' if done else "-")
        code += '  ' + ', '.join(f'[{c}]' for c in cells) + ',\n'
    return code + ')\n\n'

def render_aggregate_table(ch_dict, ch_file, agg_path, inputs_dir, renderer):
    """aggregateの表（#table(...)）のTypstコードを返す。agg_pathは、仕様のディレクトリ（存在確認済み）。"""
    where = f"chapter {ch_file!r}"
    columns = _parse_aggregate_columns(ch_dict.get("columns"), where)
    join = _parse_aggregate_join(ch_dict["join"], where) if "join" in ch_dict else None
    all_columns = columns + (join["columns"] if join else [])

    code = f'#table(\n  columns: ({", ".join(c["width"] for c in all_columns)}),\n'
    code += f'  align: ({", ".join(c["align"] for c in all_columns)}),\n'
    code += '  stroke: 0.5pt + luma(150),\n'
    code += '  fill: (col, row) => if row == 0 { luma(240) } else { none },\n'
    code += '  ' + ', '.join(f'[*{renderer.escape_typst(c["title"])}*]' for c in all_columns) + ',\n'

    spec_records = _load_records(agg_path)
    summary_code = ""
    if join is None:
        rows = [(data, path, None) for path, data in spec_records]
    else:
        results_path = os.path.join(inputs_dir, join["aggregate"])
        if not os.path.isdir(results_path):
            _error(f"Aggregate directory not found: {results_path}")
            sys.exit(1)
        results = _result_runs(_load_records(results_path), join["key"])
        rows = _joined_rows(spec_records, results, join)
        if join["summary"]["show"]:
            summary_code = _summary_table(spec_records, results, join, renderer)

    for spec, spec_path, run in rows:
        cells = [_aggregate_cell(renderer, spec.get(c["key"]), c, spec_path) if spec is not None else ""
                 for c in columns]
        if join is not None:
            if run is None:
                cells += [renderer.escape_typst(join["missing"]) if join["missing"] else ""] * len(join["columns"])
            else:
                cells += [_aggregate_cell(renderer, run["data"].get(c["key"]), c, run["path"])
                          for c in join["columns"]]
        code += '  ' + ', '.join(f'[{cell}]' for cell in cells) + ',\n'
    code += ')\n\n'
    if summary_code:
        code = summary_code + code if join["summary"]["position"] == "top" else code + summary_code
    return code + '#pagebreak(weak: true)\n'
