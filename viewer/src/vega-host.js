'use strict';
// Vega・Vega-Liteの図を、Electron自身のChromiumで描画する（#351）。MermaidHost（#207）と同じ仕組み。
//
// Pythonのワーカーが、標準入出力で描画を依頼してくる（`render_vega`。仕様書14章）。非表示のウィンドウに、
// `vega.min.js`と`vega-lite.min.js`（ワーカーが取得・検証して、パスを渡す）を読み込み、依頼に含まれる描画スクリプトを
// 実行して、SVGにして返す。描画スクリプト（loaderの全拒否・エラーの例外化を含む）は、Python側の`vega_render.RENDER_SCRIPT`を、
// そのまま受け取る。PDF出力・Pythonのブラウザ版と、同じ処理を使うため、こちらには、描画の処理を持たない。
// 準備は、最初の図で、1回だけ行う（起動を遅くしないため）。

const fs = require('node:fs');
const { cleanMessage } = require('./mermaid-host');

const BLANK_PAGE = 'data:text/html;charset=utf-8,<!doctype html><meta charset="utf-8"><body></body>';

class VegaHost {
  /**
   * @param {{createWindow: () => {loadURL: Function, webContents: {executeJavaScript: Function}, destroy: Function, isDestroyed?: Function}, readFile?: (p: string) => string}} options
   */
  constructor({ createWindow, readFile = (p) => fs.readFileSync(p, 'utf8') }) {
    this._createWindow = createWindow;
    this._readFile = readFile;
    this._ready = null;
    this._jsKey = null;
    this._window = null;
    this._queue = Promise.resolve();
  }

  /** 図を描画して、SVGの文字列を返す。失敗は、例外（メッセージは、Vegaの、仕様の誤りなど）。 */
  render({ lang, spec, script, js }) {
    // 描画は、1つずつ順に行う（ウィンドウを、共有するため）
    const run = () => this._render(String(lang), spec, String(script), js);
    const result = this._queue.then(run, run);
    this._queue = result.catch(() => {});
    return result;
  }

  async _render(lang, spec, script, js) {
    await this._ensure(js);
    try {
      // scriptは、`async ([lang, spec]) => svg`という、関数の式（vega_render.RENDER_SCRIPT）
      const svg = await this._window.webContents.executeJavaScript(
        `(${script})(${JSON.stringify([lang, spec])})`);
      if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('Vegaが、SVGを返しませんでした。');
      return svg;
    } catch (error) {
      throw new Error(cleanMessage(error));
    }
  }

  /** 非表示のウィンドウと、2つのjsを、用意する（最初の図で、1回だけ）。別のjsのパスなら、読み込み直す。 */
  async _ensure(js) {
    const vegaPath = String(js?.vega ?? '');
    const vegaLitePath = String(js?.vega_lite ?? '');
    const key = `${vegaPath}\n${vegaLitePath}`;
    if (this._ready && this._jsKey === key && this._window && !this._isDestroyed()) return this._ready;
    this.dispose();
    this._jsKey = key;
    this._ready = (async () => {
      const win = this._createWindow();
      this._window = win;
      await win.loadURL(BLANK_PAGE);
      // vega-liteは、vegaを前提にするため、vegaを先に読み込む
      for (const jsPath of [vegaPath, vegaLitePath]) {
        const source = this._readFile(jsPath);
        await win.webContents.executeJavaScript(
          `(() => { const script = document.createElement('script'); script.textContent = ${JSON.stringify(source)}; document.head.appendChild(script); })()`);
      }
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
    this._jsKey = null;
    if (win && !(typeof win.isDestroyed === 'function' && win.isDestroyed())) win.destroy();
  }
}

module.exports = { VegaHost };
