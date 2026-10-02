"""```wavedromフェンス（JSONの仕様）を、ヘッドレスブラウザ上のWaveDromでSVGにするための、仕様の検査と描画スクリプト（#299）。

描画は、Mermaid・Vegaと同じヘッドレスブラウザで行う（mermaid.pyのensure_wavedrom_page）。ここには、ブラウザに依存しない部分を置く。
"""
import json

LANGS = ('wavedrom',)
LABEL = 'WaveDrom'

# 描ける図を決めるトップレベルのキー。`signal`はタイミング図、`reg`はレジスタ・ビットフィールド図（WaveDrom 3.xに同梱のbit-field）。
_DRAWABLE_KEYS = ('signal', 'reg')


class SpecError(Exception):
    """仕様がJSONとして壊れている、または、WaveDromが描けない形をしている。"""


def parse_spec(code):
    """フェンスの内容（JSON）を、仕様（dict）にして返す。壊れた仕様や、描く対象のキーがない仕様は、SpecErrorにする。

    WaveDrom本家は、入力を`eval`で読み、`{ signal: [...] }`のような、キーに引用符のない記法も許す。
    ここでは、JSONだけを受け付ける。原稿の文字列を、ブラウザ上でコードとして実行しないため。
    また、WaveDromは、描けない入力でも、例外にせず、空の図を返す。そのため、描く前に、形を検査して、Fail-fastにする。"""
    try:
        spec = json.loads(code)
    except json.JSONDecodeError as e:
        raise SpecError(f"Invalid JSON: {e.msg} (line {e.lineno}, column {e.colno}). "
                        "Only strict JSON is accepted: quote the keys and strings, and remove trailing commas.") from None
    if not isinstance(spec, dict):
        raise SpecError("The spec must be a JSON object.")
    for key in _DRAWABLE_KEYS:
        if key in spec:
            if not isinstance(spec[key], list) or not spec[key]:
                raise SpecError(f"'{key}' must be a non-empty array.")
            return spec
    raise SpecError("The spec must have a 'signal' array (timing diagram) or a 'reg' array (register diagram).")


# ブラウザで実行する描画。引数は[spec]。SVGの文字列を返す。
# WaveDromは、描画先の要素（id=接頭辞+番号）の中へ、SVGを書き込む。図の数だけ要素を作らず、1つを使い回す。
# async関数にするのは、ElectronのexecuteJavaScriptが、同期の例外のメッセージを捨てて、汎用の文言にするため（Promiseの拒否は、メッセージが残る）。
RENDER_SCRIPT = """async ([spec]) => {
  const el = document.getElementById('WaveDrom_Display_0');
  el.innerHTML = '';
  WaveDrom.RenderWaveForm(0, spec, 'WaveDrom_Display_');
  const svg = el.innerHTML;
  if (!svg.startsWith('<svg')) throw new Error('WaveDrom could not draw this spec.');
  return svg;
}"""
