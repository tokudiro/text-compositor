"""設定ファイルの`chapters`を、ファイルの一覧にする（Viewerのサイドバー用、#373）。

ビルド用の解析（`chapters._parse_chapter_entry`・`_expand_chapters`）は、設定に誤りがあると`sys.exit(1)`で終了する。
常駐のワーカーの中で呼ぶと、ワーカーごと終了するため、流用せず、誤りを警告として返す一覧用の関数を、別に持つ。
章のファイルの中身は、読まない（変換が走るのは、クリックして開いたファイルだけ）。
"""
import json
import os

from text_compositor.config import yaml

DEFAULT_INPUTS_DIR = "inputs"


class ChapterListError(Exception):
    """設定ファイルを読めない（存在しない・構文の誤り・`chapters`が無い）。メッセージは、利用者へ見せる。"""


def _read_config(config_path):
    if not os.path.isfile(config_path):
        raise ChapterListError(f"Config file not found: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.endswith((".yaml", ".yml")):
                if yaml is None:
                    raise ChapterListError("PyYAML is not installed; cannot read a .yaml config file.")
                loaded = yaml.safe_load(f)
            else:
                loaded = json.load(f)
    except ChapterListError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError if yaml else ValueError) as e:
        raise ChapterListError(f"Cannot read the config file: {e}") from e
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ChapterListError("The config file must be a mapping (key: value).")
    return loaded


def _file_item(name, inputs_dir):
    # 章のファイルの基準は、`config`のフォルダではなく、`inputs.dir`（`project.py`と同じ規則）
    return {"kind": "file", "name": name, "path": os.path.normpath(os.path.join(inputs_dir, name))}


def _aggregate_item(ch, inputs_dir, warnings):
    """フォルダを1つの表に集約する章（`aggregate`）の項目（#478）。1つのファイルではなく、Obunzuは表を出さない（PDFで
    確認する）ため、Viewerは、押せない項目として出す。章が、一覧から黙って消えて、抜けたように見えるのを避けるため。
    `name`は、`title`（文字列のとき）、無ければ、フォルダ名。`path`は、フォルダ（案内のための情報で、開かない）。"""
    folder = ch["aggregate"]
    if not isinstance(folder, str) or not folder:
        warnings.append(f"Invalid chapter entry: {ch!r}")
        return None
    title = ch.get("title")
    name = title if isinstance(title, str) and title.strip() else folder
    return {"kind": "aggregate", "name": name, "path": os.path.normpath(os.path.join(inputs_dir, folder))}


def _entries(chapters, inputs_dir, warnings, in_section):
    items = []
    for ch in chapters:
        if isinstance(ch, str):
            items.append(_file_item(ch, inputs_dir))
        elif isinstance(ch, dict) and "section" in ch:
            title = ch["section"]
            children = ch.get("chapters")
            if in_section:
                warnings.append(f"Nested sections are not supported: {title!r}.")
            elif not isinstance(title, str) or not title.strip() or not isinstance(children, list):
                warnings.append(f"Invalid section: {ch!r}")
            else:
                items.append({"kind": "section", "name": title, "children": _entries(children, inputs_dir, warnings, True)})
        elif isinstance(ch, dict) and "aggregate" in ch:
            item = _aggregate_item(ch, inputs_dir, warnings)
            if item is not None:
                items.append(item)
        elif isinstance(ch, dict) and isinstance(ch.get("file"), str) and ch["file"]:
            items.append(_file_item(ch["file"], inputs_dir))
        else:
            warnings.append(f"Invalid chapter entry: {ch!r}")
    return items


def list_chapters(config_path):
    """`{"items": [...], "warnings": [...]}`を返す。`items`は、設定に書いた順序で、
    `{"kind": "file", "name", "path"}`（`path`は絶対パス）、`{"kind": "section", "name", "children"}`、または
    `{"kind": "aggregate", "name", "path"}`（フォルダを表にする章。`path`はフォルダ。#478）。
    設定ファイルを読めないときは、`ChapterListError`。"""
    config_path = os.path.abspath(config_path)
    loaded = _read_config(config_path)
    chapters = loaded.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ChapterListError("No chapters are configured in the config file.")
    inputs = loaded.get("inputs")
    inputs_name = (inputs.get("dir") if isinstance(inputs, dict) else None) or DEFAULT_INPUTS_DIR
    if not isinstance(inputs_name, str):
        raise ChapterListError("'inputs.dir' must be a string.")
    inputs_dir = os.path.normpath(os.path.join(os.path.dirname(config_path), inputs_name))
    warnings = []
    return {"items": _entries(chapters, inputs_dir, warnings, False), "warnings": warnings}
