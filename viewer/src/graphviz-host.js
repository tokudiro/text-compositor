'use strict';
// Graphvizの図を、Electron自身のChromiumで描画する（#181）。
//
// Pythonのワーカーが、標準入出力で描画を依頼してくる（`render_graphviz`。仕様書14章）。非表示のウィンドウに、
// `viz-global.js`（Viz.js。Graphvizを、WebAssemblyにしたもの。ワーカーが取得・検証して、パスを渡す）を読み込み、
// DOTをSVGにして返す。システムのGraphviz（`dot`）が要らない。準備は、最初の図で、1回だけ行う（起動を遅くしないため）。
// 実測: 準備 約0.2秒、描画 数ms。
//
// 文字幅の補正: Graphvizは、文字の幅を、内蔵の見積もり（Times系）で計算する。日本語（全角）の長いラベルは、
// 見積もりが実際より約2割狭く、文字が箱からはみ出す。そこで、いったん描画したSVGを、Chromium上で、
// 実際のフォントで測り、はみ出したノードだけに、`width=`を足して、描き直す（1回だけ）。
// 補正の方法を変えたときは、Python側の`GRAPHVIZ_FIT_REVISION`を上げる（描画結果のキャッシュを、無効にするため）。

const fs = require('node:fs');
const { cleanMessage } = require('./mermaid-host');

// Viz.jsは、`new URL('viz-global.js', document.baseURI)`を実行する。`data:`のページは、基準のURLになれず、
// `Invalid URL`で失敗する（Promiseが、拒否されるだけで、待ち続けたように見える）ため、形だけの`<base>`を置く。
// WebAssemblyは、`viz-global.js`に、埋め込まれており、このURLのファイルは、読まれない。
const BLANK_PAGE = 'data:text/html;charset=utf-8,<!doctype html><meta charset="utf-8"><base href="file:///viz/"><body></body>';

/** ノードの内側の余白（Graphvizの既定の`margin`0.11インチ×2 ≒ 16）。ラベルの幅に足して、箱の幅を決める。 */
const NODE_PADDING = 16;
/** 楕円は、内側に入る長方形が、幅の 1/√2 になる。 */
const ELLIPSE_FACTOR = 1.42;

/**
 * 非表示のページの中で動く処理。`Function.prototype.toString()`で、文字列にして、ページへ渡す（Nodeのスコープの変数は、使えない）。
 * `window.__renderDot(code)`を作る。戻り値: `{svg}`または`{error}`（メッセージ）。
 */
function installRenderer() {
  let instancePromise = null;

  // 描画したSVGの、ノードごとに、文字の幅と、箱の幅を比べ、足りないノードの、必要な幅（pt）を返す
  function findOverflowingNodes(svgText, padding, ellipseFactor) {
    const holder = document.createElement('div');
    holder.style.cssText = 'position:absolute;left:-99999px;top:0;visibility:hidden';
    holder.innerHTML = svgText;
    document.body.appendChild(holder);
    const fixes = [];
    try {
      for (const node of holder.querySelectorAll('g.node')) {
        const title = node.querySelector(':scope > title');
        const shapes = node.querySelectorAll(':scope > polygon, :scope > ellipse');
        // 記録（record）・HTMLラベル・多重の枠（doublecircleなど）は、対象外（箱の構造が、単純でない）
        if (!title || shapes.length !== 1 || node.querySelector('polyline')) continue;
        const name = title.textContent;
        if (name.includes('\\') || name.includes('\n')) continue;
        let textWidth = 0;
        for (const text of node.querySelectorAll(':scope > text')) textWidth = Math.max(textWidth, text.getBBox().width);
        if (!textWidth) continue;
        const isEllipse = shapes[0].tagName.toLowerCase() === 'ellipse';
        const needed = (textWidth + padding) * (isEllipse ? ellipseFactor : 1);
        if (needed > shapes[0].getBBox().width + 1) fixes.push({ name, points: needed });
      }
    } finally {
      holder.remove();
    }
    return fixes;
  }

  // 最後の`}`の前に、`"ノード名" [width=…];`を足す。ノード名は、グラフ全体で、一意なので、クラスタの中のノードにも効く
  function withWidths(code, fixes) {
    const end = code.lastIndexOf('}');
    if (end < 0) return null;
    const lines = fixes.map(({ name, points }) =>
      `"${name.replace(/"/g, '\\"')}" [width=${Math.ceil((points / 72) * 1000) / 1000}];`);
    return `${code.slice(0, end)}\n${lines.join('\n')}\n${code.slice(end)}`;
  }

  window.__renderDot = async (code, padding, ellipseFactor) => {
    try {
      instancePromise = instancePromise || Viz.instance();
      const viz = await instancePromise;
      const first = viz.renderString(code, { format: 'svg' });
      const fixes = findOverflowingNodes(first, padding, ellipseFactor);
      if (!fixes.length) return { svg: first };
      try {
        const patched = withWidths(code, fixes);
        return { svg: patched === null ? first : viz.renderString(patched, { format: 'svg' }) };
      } catch (_error) {
        return { svg: first };   // 補正に失敗しても、補正なしの図を返す（補正は、見た目の改善）
      }
    } catch (error) {
      return { error: String((error && error.message) || error) };
    }
  };
}

const INSTALL_SCRIPT = `(${installRenderer.toString()})()`;

class GraphvizHost {
  /**
   * @param {{createWindow: () => {loadURL: Function, webContents: {executeJavaScript: Function}, destroy: Function, isDestroyed?: Function}, readFile?: (p: string) => string}} options
   */
  constructor({ createWindow, readFile = (p) => fs.readFileSync(p, 'utf8') }) {
    this._createWindow = createWindow;
    this._readFile = readFile;
    this._ready = null;
    this._jsPath = null;
    this._window = null;
    this._queue = Promise.resolve();
  }

  /** 図を描画して、SVGの文字列を返す。失敗は、例外（メッセージは、Graphvizの構文エラーなど）。 */
  render({ code, js }) {
    // 描画は、1つずつ順に行う
    const run = () => this._render(String(code), String(js));
    const result = this._queue.then(run, run);
    this._queue = result.catch(() => {});
    return result;
  }

  async _render(code, jsPath) {
    await this._ensure(jsPath);
    let reply;
    try {
      reply = await this._window.webContents.executeJavaScript(
        `window.__renderDot(${JSON.stringify(code)}, ${NODE_PADDING}, ${ELLIPSE_FACTOR})`);
    } catch (error) {
      throw new Error(cleanMessage(error));
    }
    if (reply?.error) throw new Error(cleanMessage(reply.error));
    if (typeof reply?.svg !== 'string' || !reply.svg.includes('<svg')) throw new Error('Graphvizが、SVGを返しませんでした。');
    return reply.svg;
  }

  /** 非表示のウィンドウと、viz-global.jsを、用意する（最初の図で、1回だけ）。別のjsのパスなら、読み込み直す。 */
  async _ensure(jsPath) {
    if (this._ready && this._jsPath === jsPath && this._window && !this._isDestroyed()) return this._ready;
    this.dispose();
    this._jsPath = jsPath;
    this._ready = (async () => {
      const win = this._createWindow();
      this._window = win;
      await win.loadURL(BLANK_PAGE);
      const source = this._readFile(jsPath);
      await win.webContents.executeJavaScript(
        `(() => { const script = document.createElement('script'); script.textContent = ${JSON.stringify(source)}; document.head.appendChild(script); })()`);
      await win.webContents.executeJavaScript(INSTALL_SCRIPT);
    })();
    try {
      await this._ready;
    } catch (error) {
      this.dispose();   // 準備に失敗したら、次の依頼で、作り直す
      throw error;
    }
    return this._ready;
  }

  _isDestroyed() {
    return typeof this._window?.isDestroyed === 'function' ? this._window.isDestroyed() : false;
  }

  /** ウィンドウを片付ける（アプリの終了時。非表示でも、ウィンドウが残ると、アプリが終了しないため）。 */
  dispose() {
    const win = this._window;
    this._window = null;
    this._ready = null;
    this._jsPath = null;
    if (win && !(typeof win.isDestroyed === 'function' && win.isDestroyed())) win.destroy();
  }
}

module.exports = { GraphvizHost, BLANK_PAGE, INSTALL_SCRIPT };
