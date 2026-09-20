'use strict';
// Mermaidの図を、Electron自身のChromiumで描画する（#207）。
//
// Pythonのワーカーが、標準入出力で描画を依頼してくる（`render_mermaid`。仕様書14章）。非表示のウィンドウに、
// `mermaid.min.js`（ワーカーが取得・検証して、パスを渡す）を読み込み、`mermaid.render()`でSVGにして返す。
// Pythonの`playwright`（約106 MB）と、システムのChrome・Edgeが要らない。準備は、最初の図で、1回だけ行う
// （起動を遅くしないため）。実測: 準備 約0.3秒、描画 16〜51 ms。
//
// 設定は、Python側（`mermaid.py`のMermaidBrowser）と同じにする。Typstとは違い、HTMLの表示では、`<foreignObject>`が
// 使えるが、SVGの見た目を、PDF出力と、そろえるため、HTMLラベルは、無効にする。

const fs = require('node:fs');

const INITIALIZE = 'mermaid.initialize({ startOnLoad: false, htmlLabels: false, flowchart: { htmlLabels: false } })';
const BLANK_PAGE = 'data:text/html;charset=utf-8,<!doctype html><meta charset="utf-8"><body></body>';

/** Electronのエラーメッセージから、原因の理解に役立たない部分（内部のスタック、呼び出しの包み）を除く。 */
function cleanMessage(error) {
  const text = String(error?.message ?? error);
  return text
    .replace(/^Error invoking remote method '[^']*': /, '')
    .replace(/^(Uncaught )?(Error|ReferenceError|TypeError): /, '')
    .split('\n')
    .filter((line) => !/^\s+at /.test(line))
    .join('\n')
    .trim();
}

class MermaidHost {
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

  /** 図を描画して、SVGの文字列を返す。失敗は、例外（メッセージは、Mermaidの構文エラーなど）。 */
  render({ diagram_id: diagramId, code, js }) {
    // 描画は、1つずつ順に行う（Mermaidのグローバルな状態を、共有するため）
    const run = () => this._render(String(diagramId), String(code), String(js));
    const result = this._queue.then(run, run);
    this._queue = result.catch(() => {});
    return result;
  }

  async _render(diagramId, code, jsPath) {
    await this._ensure(jsPath);
    try {
      const svg = await this._window.webContents.executeJavaScript(
        `mermaid.render(${JSON.stringify(diagramId)}, ${JSON.stringify(code)}).then((result) => result.svg)`);
      if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('Mermaidが、SVGを返しませんでした。');
      return svg;
    } catch (error) {
      throw new Error(cleanMessage(error));
    }
  }

  /** 非表示のウィンドウと、mermaid.min.jsを、用意する（最初の図で、1回だけ）。別のjsのパスなら、読み込み直す。 */
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
      await win.webContents.executeJavaScript(INITIALIZE);
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

module.exports = { MermaidHost, cleanMessage };
