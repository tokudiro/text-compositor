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


def parse_spec(code):
    """フェンスの内容（JSON）を、仕様（dict）にして返す。壊れた仕様や、外部参照を含む仕様は、SpecErrorにする。"""
    try:
        spec = json.loads(code)
    except json.JSONDecodeError as e:
        raise SpecError(f"Invalid JSON: {e.msg} (line {e.lineno}, column {e.colno})") from None
    if not isinstance(spec, dict):
        raise SpecError("The spec must be a JSON object.")
    external = find_external_reference(spec)
    if external:
        raise SpecError(
            f"External resources are not supported ('url' at {external}). "
            "Write the data inline with \"data\": {\"values\": [...]}.")
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
