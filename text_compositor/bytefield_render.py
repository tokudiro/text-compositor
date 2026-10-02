"""```bytefieldフェンス（Clojureの記述）を、ヘッドレスブラウザ上のBytefield-svgでSVGにするための、入力の検査と描画スクリプト（#300）。

描画は、Mermaid・Vega・WaveDromと同じヘッドレスブラウザで行う（mermaid.pyのensure_bytefield_page）。ここには、ブラウザに依存しない部分を置く。
Bytefield-svgは、プロトコルの仕様書にあるような、ビット/バイトフィールドの図（パケットの構造など）を描く。
"""

LANGS = ('bytefield',)
LABEL = 'Bytefield'


class SpecError(Exception):
    """入力が空である。"""


def parse_spec(code):
    """フェンスの内容（`(draw-box ...)`などの、Clojureの記述）を返す。空の入力は、SpecErrorにする。

    WaveDromと違い、入力はJSONではなく、Bytefield-svgのDSL（SCIのインタプリタが評価する）のため、Pythonでは、構文を検査しない。
    構文の誤り・仕様の誤りは、Bytefield-svg自身が、行・桁つきのメッセージで、例外にする（RENDER_SCRIPTが、メッセージを取り出す）。
    インタプリタは、JavaScriptの呼び出し（`js/...`）を許さない（実測: `Could not resolve symbol: js/fetch`）。そのため、
    原稿の記述が、ブラウザの機能やネットワークに触れることはない。ただし、空の入力は、エラーにならず、空の図になるため、止める。"""
    if not code.strip():
        raise SpecError("The diagram source is empty. Write drawing commands such as (draw-box \"Field\" {:span 8}).")
    return code


# ブラウザで実行する描画。引数は[source]。SVGの文字列を返す。
# Bytefield-svgは、失敗したとき、Clojureのエラーを投げる。`message`に、行・桁つきの説明が入っているため、取り出して、通常の例外にする。
# async関数にするのは、ElectronのexecuteJavaScriptが、同期の例外のメッセージを捨てて、汎用の文言にするため（Promiseの拒否は、メッセージが残る）。
RENDER_SCRIPT = """async ([source]) => {
  let svg;
  try {
    svg = window.returnExports(source);
  } catch (e) {
    throw new Error((e && e.message) || String(e));
  }
  if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('Bytefield could not draw this source.');
  return svg;
}"""
