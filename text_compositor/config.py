"""config（YAML/JSON）の読み込み・既定値・変数展開と、プロジェクトのディレクトリ解決。"""
import os
import re
import sys
import json
from text_compositor.log import _error, _warn

try:
    import yaml
except ImportError:
    yaml = None

def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def default_config():
    return {
        "document": {
            "title": "System_Specification",
            "subtitle": "自動生成ドキュメント",
            "author": "開発チーム",
            "date": "auto",
            "diagnostics": {
                "line_mapping": "block"
            }
        },
        "output": {
            "filename": "System_Specification.pdf",
            "dir": "outputs"
        },
        "template": {
            "path": "template"
        },
        "inputs": {
            "dir": "inputs",
            "files": None
        }
    }

def resolve_template_path(template_path_value, tool_dir, project_dir):
    """template.pathを「名前」と「パス」で区別して解決する（5章、#23）。
    拡張子(.typ)を含まない値（例: template, slide）は「名前」とみなし、ツール同梱の
    tool_dir/templates/<name>.typ から解決する。.typで終わる値は「パス」とみなし、
    他の相対パスと同じ規則（5章）でproject_dir基準で解決し、プロジェクト独自の
    テンプレートを持ち込めるようにする（サブディレクトリの有無を問わない）。
    絶対パスはos.path.joinの挙動によりそのまま使われる。"""
    if template_path_value.endswith('.typ'):
        return os.path.normpath(os.path.join(project_dir, template_path_value))
    return os.path.join(tool_dir, "templates", template_path_value + ".typ")

def load_config_file(config_path):
    """指定された1ファイル(yaml/json)から設定を読み込む。存在しなければFail-fast。"""
    config = default_config()
    if not os.path.exists(config_path):
        _error(f"Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        if config_path.endswith(('.yaml', '.yml')):
            if yaml is None:
                _error("PyYAML is not installed; cannot read a .yaml config file.")
                sys.exit(1)
            loaded = yaml.safe_load(f) or {}
        else:
            loaded = json.load(f) or {}
    deep_update(config, loaded)
    return config

def _resolve_variables(config):
    """configの`variables:`（#72）から{{KEY}}の置換表{KEY: 文字列}を作る。キーが無ければNone
    （置換機構を無効にする）。値は次のいずれか。
      * スカラー（文字列・数値・真偽値）: そのまま文字列化して使う。
      * {env: 環境変数名, default: 既定値}: ビルド時の環境変数から取得する。未設定でdefaultも無ければ
        エラー終了する（CI等で値の渡し忘れに気づけるように）。
    コマンド実行による取得は設けない。configの記述だけで任意コマンドが動くのは安全性の面で
    望ましくなく、出力を環境変数に入れて渡せば同じことができるため。
    値は1行に限る。改行を許すと、行番号による診断（#27のsrcmap）が元のMarkdownの行とずれる。"""
    raw = config.get("variables")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _error("'variables' must be a mapping of KEY: value.")
        sys.exit(1)
    variables = {}
    for key, spec in raw.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(key)):
            _error(f"variables.{key}: the key must consist of letters, digits and '_' "
                  f"(and not start with a digit).")
            sys.exit(1)
        if isinstance(spec, dict):
            unknown = set(spec) - {"env", "default"}
            if "env" not in spec or unknown:
                _error(f"variables.{key}: a mapping value must have 'env' (and optionally 'default'); "
                      f"got keys {sorted(map(str, spec))}.")
                sys.exit(1)
            value = os.environ.get(str(spec["env"]))
            if value is None:
                if "default" not in spec:
                    _error(f"variables.{key}: environment variable {spec['env']} is not set "
                          f"and no 'default' is given.")
                    sys.exit(1)
                value = spec["default"]
        elif isinstance(spec, (list, tuple)):
            _error(f"variables.{key}: a list is not supported; use a scalar or {{env: NAME}}.")
            sys.exit(1)
        else:
            value = spec
        value = "" if value is None else str(value)
        if "\n" in value or "\r" in value:
            _error(f"variables.{key}: the value must be a single line.")
            sys.exit(1)
        variables[str(key)] = value
    return variables

def _resolve_project_image_path(path, base_dir, typst_root, label):
    """document.background/chapters[].background（#55）、document.logo/chapters[].logo（#54）の
    相対パスを、project_dir基準からtypst_root起点のルート絶対パスへ変換する（5章: config.yaml内の
    相対パスはproject_dir基準。Markdown内画像の_resolve_asset()とは基準ディレクトリが異なる）。
    仕様9章のFail-fast方針に従い、画像欠損は即エラーとする。"""
    if not path:
        return None
    abs_path = os.path.normpath(os.path.join(base_dir, path))
    if not os.path.exists(abs_path):
        _error(f"{label} image not found: {abs_path}")
        sys.exit(1)
    return "/" + os.path.relpath(abs_path, typst_root).replace(os.sep, '/')

def find_config_in_cwd():
    """--config省略時、カレントディレクトリ直下の推奨ファイル名を探す（ツール本体ディレクトリは見ない）。"""
    for name in ("text-compositor.config.yaml", "text-compositor.config.json"):
        path = os.path.join(os.getcwd(), name)
        if os.path.exists(path):
            return path
    return None

def _read_config_list(list_path):
    """--config-listのファイルを読み、configファイルパスのリストを返す（コメント行・空行を除く）。"""
    list_path = os.path.abspath(list_path)
    base_dir = os.path.dirname(list_path)
    paths = []
    with open(list_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            paths.append(line if os.path.isabs(line) else os.path.join(base_dir, line))
    return paths

def _load_project_config(config_path):
    """configパス（Noneならカレントディレクトリから探索）から設定ファイルを読み込み、(project_dir, config, chapters)を返す。"""
    if config_path:
        config_path = os.path.abspath(config_path)
    else:
        config_path = find_config_in_cwd()
        if not config_path:
            _error("--config not specified, and no text-compositor.config.yaml/.json found in the current directory.")
            sys.exit(1)
    project_dir = os.path.dirname(config_path)
    config = load_config_file(config_path)

    chapters = config.get("chapters", [])
    # 【修正】章が空の場合は正常終了せずFail-fastでエラー終了させる
    if not chapters:
        _error("No chapters configured in config.yaml. Aborting.")
        sys.exit(1)
    return project_dir, config, chapters

def _resolve_project_dirs(project_dir, config, create_outputs=True):
    """出力先・入力元・作業ディレクトリと、それらを跨ぐ--root（typst_root）を解決する。
    create_outputs=False（Python API、#167）なら、出力先ディレクトリを作らず、--rootにも含めない
    （PDFは呼び出し側が指定した場所へ、作業ディレクトリから移すため。原稿の隣に`outputs/`を作らない）。"""
    outputs_dir = os.path.normpath(os.path.join(project_dir, config["output"]["dir"]))
    if create_outputs:
        os.makedirs(outputs_dir, exist_ok=True)
    # 【修正】ハードコードをやめ config の inputs.dir を実際に使用する
    inputs_dir = os.path.normpath(os.path.join(project_dir, config.get("inputs", {}).get("dir") or "inputs"))

    work_dir = os.path.join(project_dir, ".text-compositor")
    os.makedirs(work_dir, exist_ok=True)

    # project_dir・inputs_dir・outputs_dir・work_dirすべてを跨いでtypstから参照できるよう、
    # それら全ての共通の親ディレクトリを --root にする（tool_dirは含めない）
    roots = [project_dir, inputs_dir, work_dir] + ([outputs_dir] if create_outputs else [])
    typst_root = os.path.commonpath(roots)
    return outputs_dir, inputs_dir, work_dir, typst_root

def _resolve_line_mapping(config):
    """document.diagnostics.line_mapping: "block"（既定。#27）。Typstコンパイルエラーの行番号を
    元のMarkdownの行番号へ逆引きする精度を読み取る。"fine"（リスト項目・テーブル行単位）は
    未実装の将来課題のため、指定されても現時点では"block"にフォールバックする。
    document.diagnosticsキー自体は存在するが値が空（YAMLで`diagnostics:`とだけ書いてNoneに
    なる場合）でも例外を出さないよう、`or {}`でNoneをdictに読み替える。"""
    line_mapping = (config.get("document", {}).get("diagnostics") or {}).get("line_mapping", "block")
    if line_mapping not in ("off", "block"):
        _warn(f"document.diagnostics.line_mapping: {line_mapping!r} is not supported yet; falling back to 'block'.")
        line_mapping = "block"
    return line_mapping

def _output_pdf_path(project_dir, config):
    """出力PDFの絶対パス。ディレクトリは作らない（_resolve_project_dirsと違い副作用を持たない）。"""
    return os.path.normpath(os.path.join(project_dir, config["output"]["dir"], config["output"]["filename"]))
