'use strict';
// WaveDromの図を、Electron自身のChromiumで描画する（#392）。VegaHost（#351）・MermaidHost（#207）と同じ仕組み。
//
// Pythonのワーカーが、標準入出力で描画を依頼してくる（`render_wavedrom`。仕様書14章）。非表示のウィンドウに、
// スキン`default.js`と`wavedrom.min.js`（ワーカーが取得・検証して、パスを渡す）を読み込み、依頼に含まれる描画スクリプトを
// 実行して、SVGにして返す。描画スクリプトは、Python側の`wavedrom_render.RENDER_SCRIPT`を、そのまま受け取る。
// PDF出力・Pythonのブラウザ版と、同じ処理を使うため、こちらには、描画の処理を持たない。
// 準備は、最初の図で、1回だけ行う（起動を遅くしないため）。

const fs = require('node:fs');
const { cleanMessage } = require('./mermaid-host');

// WaveDromは、描画先の要素（id=`WaveDrom_Display_0`）の中へ、SVGを書き込む
const BLANK_PAGE = 'data:text/html;charset=utf-8,<!doctype html><meta charset="utf-8"><body><div id="WaveDrom_Display_0"></div></body>';

class WaveDromHost {
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

  /** 図を描画して、SVGの文字列を返す。失敗は、例外（メッセージは、WaveDromの、描けない仕様など）。 */
  render({ spec, script, js }) {
    // 描画は、1つずつ順に行う（ウィンドウと、描画先の要素を、共有するため）
    const run = () => this._render(spec, String(script), js);
    const result = this._queue.then(run, run);
    this._queue = result.catch(() => {});
    return result;
  }

  async _render(spec, script, js) {
    await this._ensure(js);
    try {
      // scriptは、`async ([spec]) => svg`という、関数の式（wavedrom_render.RENDER_SCRIPT）
      const svg = await this._window.webContents.executeJavaScript(`(${script})(${JSON.stringify([spec])})`);
      if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('WaveDromが、SVGを返しませんでした。');
      return svg;
    } catch (error) {
      throw new Error(cleanMessage(error));
    }
  }

  /** 非表示のウィンドウと、2つのjsを、用意する（最初の図で、1回だけ）。別のjsのパスなら、読み込み直す。 */
  async _ensure(js) {
    const skinPath = String(js?.skin ?? '');
    const wavedromPath = String(js?.wavedrom ?? '');
    const key = `${skinPath}\n${wavedromPath}`;
    if (this._ready && this._jsKey === key && this._window && !this._isDestroyed()) return this._ready;
    this.dispose();
    this._jsKey = key;
    this._ready = (async () => {
      const win = this._createWindow();
      this._window = win;
      await win.loadURL(BLANK_PAGE);
      // wavedrom.min.jsは、スキン（`WaveSkin`）を前提にするため、スキンを先に読み込む
      for (const jsPath of [skinPath, wavedromPath]) {
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

module.exports = { WaveDromHost };
