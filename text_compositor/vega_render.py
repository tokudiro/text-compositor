"""```vega-lite・```vegaフェンス（JSONの仕様）を、ヘッドレスブラウザ上のVega・Vega-LiteでSVGにするための、仕様の検査と描画スクリプト（#211）。

描画は、Mermaidと同じヘッドレスブラウザで行う（mermaid.pyのensure_vega_page）。ここには、ブラウザに依存しない部分を置く。
"""
import json

LANGS = ('vega-lite', 'vega')
LABELS = {'vega-lite': 'Vega-Lite', 'vega': 'Vega'}

# データを、行の並びとして埋め込むキー。中の行は、原稿のデータであり、`url`という名前の列があっても、外部参照ではない。
_INLINE_DATA_KEYS = ('values', 'datasets')


class SpecError(Exception):
    """仕様がJSONとして壊れている、または、許可していない記述を含む。"""


def find_external_reference(node, path='$'):
    """仕様の中の、外部リソースを指すキー`url`を探し、最初に見つかった場所（JSONのパス）を返す。無ければ、None。
    Vega・Vega-Liteの`data.url`は、既定では、ネットワークにも出る（外部画像を既定でブロックする方針、#238と衝突する）。
    さらに、失敗しても例外にならず、空のチャートが返る。そのため、描画の前に、仕様を検査して、Fail-fastにする。
    `image`マークの`url`も、同じキー名のため、同時に止まる。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'url':
                return f"{path}.url"
            if key in _INLINE_DATA_KEYS:
                continue
            found = find_external_reference(value, f"{path}.{key}")
            if found:
                return found
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found = find_external_reference(value, f"{path}[{index}]")
            if found:
                return found
    return None


# データファイルとして読める拡張子と、そのVegaの形式名（#350）。これ以外の拡張子は、読まない（プロジェクトの中の、
# 別の種類のファイルを、図の入力として取り込まないため）。
DATA_EXTENSIONS = {'.csv': 'csv', '.tsv': 'tsv', '.json': 'json'}
# データファイル1つの、大きさの上限（バイト）。原稿のdiffと、描画の時間を、現実的な範囲に保つ。
MAX_DATA_BYTES = 10 * 1024 * 1024


def inline_data_files(spec, load, path='$'):
    """仕様のデータ定義（`data`キーの下の`url`）を、ファイルの中身に置き換える（#350）。仕様を、その場で書き換える。

    ブラウザには、ファイルを読ませない。ワーカー（Python）が、`load(url)`でファイルを読み、中身の文字列を`values`へ、
    形式を`format.type`へ入れる。Vega・Vega-Liteは、文字列の`values`を、`format`に従って、自分で解釈する
    （CSVの数値の型の判定も、そのまま働く。実測済み）。そのため、描画側のloader（すべて拒否）は、緩めない。
    `load(url)`は、`(文字列, 形式名)`を返し、置き換えられない`url`は、SpecErrorにする。
    `data`の外の`url`（`image`マークなど）は、置き換えず、後段の検査（find_external_reference）が止める。
    戻り値: 置き換えたデータ定義の数。"""
    count = 0
    if isinstance(spec, dict):
        for key, value in spec.items():
            if key in _INLINE_DATA_KEYS:
                continue
            if key == 'data':
                definitions = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
                for index, definition in enumerate(definitions):
                    if isinstance(definition, dict) and 'url' in definition:
                        where = f"{path}.data" if isinstance(value, dict) else f"{path}.data[{index}]"
                        _inline_one(definition, load, where)
                        count += 1
            count += inline_data_files(value, load, f"{path}.{key}")
    elif isinstance(spec, list):
        for index, value in enumerate(spec):
            count += inline_data_files(value, load, f"{path}[{index}]")
    return count


def _inline_one(definition, load, where):
    url = definition['url']
    if not isinstance(url, str) or not url:
        raise SpecError(f"'url' at {where} must be a file path (a string).")
    if 'values' in definition:
        raise SpecError(f"{where} has both 'url' and 'values'. Use only one of them.")
    fmt = definition.get('format')
    if fmt is not None and not isinstance(fmt, dict):
        raise SpecError(f"'format' at {where} must be an object.")
    try:
        text, detected = load(url)
    except OSError as e:
        raise SpecError(f"Cannot read '{url}' (at {where}): {e.strerror or e}") from None
    del definition['url']
    definition['values'] = text
    # 仕様が`format.type`を、明示していれば、それを優先する（例: 拡張子が`.txt`ではなく、拡張子で決まる形式と違うとき）
    definition.setdefault('format', {}).setdefault('type', detected)


def parse_spec(code, load=None):
    """フェンスの内容（JSON）を、仕様（dict）にして返す。壊れた仕様や、外部参照を含む仕様は、SpecErrorにする。
    loadを渡すと、データ定義の`url`（ローカルのファイル）を、ファイルの中身に置き換える（inline_data_files。#350）。
    渡さないときは、`url`は、すべて外部参照として、エラーにする。"""
    try:
        spec = json.loads(code)
    except json.JSONDecodeError as e:
        raise SpecError(f"Invalid JSON: {e.msg} (line {e.lineno}, column {e.colno})") from None
    if not isinstance(spec, dict):
        raise SpecError("The spec must be a JSON object.")
    if load is not None:
        inline_data_files(spec, load)
    external = find_external_reference(spec)
    if external:
        hint = ("Only data files inside the project can be referenced, by 'data.url' with a relative path. "
                "Image URLs and other external resources are not allowed." if load is not None else
                "Write the data inline with \"data\": {\"values\": [...]}.")
        raise SpecError(f"External resources are not supported ('url' at {external}). {hint}")
    return spec


# ブラウザで実行する描画。引数は[lang, spec]。SVGの文字列を返す。
# - Vega-Liteは、Vegaの仕様へコンパイルしてから、描く（vegaLite.compileが、仕様の誤りを例外にする）。
# - loaderは、すべての読み込みを拒否する。仕様の検査（parse_spec）をすり抜けた経路があっても、ネットワークへは出ない。
# - Vegaは、読み込みや式の評価の失敗を、例外にせず、ログへ出して、空のチャートを返す。ロガーで集めて、例外にする。
RENDER_SCRIPT = """async ([lang, spec]) => {
  const errors = [];
  const logger = {
    level: () => logger,
    error: (...args) => { errors.push(args.map(String).join(' ')); return logger; },
    warn: () => logger, info: () => logger, debug: () => logger,
  };
  const blocked = () => {
    errors.push('External resources are blocked.');
    throw new Error('External resources are blocked.');
  };
  const loader = { load: blocked, sanitize: blocked, http: blocked, file: blocked };
  const vgSpec = lang === 'vega-lite' ? vegaLite.compile(spec).spec : spec;
  const view = new vega.View(vega.parse(vgSpec), { renderer: 'none', loader, logger });
  try {
    const svg = await view.toSVG();
    if (errors.length) throw new Error(errors.join('\\n'));
    return svg;
  } finally {
    view.finalize();
  }
}"""
