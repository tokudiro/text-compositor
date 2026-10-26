'use strict';
// 確認スクリプト用: 起動したViewerのメインプロセスへ`--inspect`で接続し、キーを送る（#551）。
//
// SendKeysは、Windowsの前面のウィンドウへ送るため、実行中にほかの作業を奪い、前面を取り損ねると、キーがほかのウィンドウへ届く。
// 代わりに、キーを2通りで届ける。
//   - メニューのショートカット（Ctrl+,・F5・Ctrl+F・F6など）: メニュー項目を、メインプロセスから直接呼ぶ。
//     `webContents.sendInputEvent`でも届くが、ウィンドウにフォーカスがないと、メニューのショートカットは効かない
//     （ほかのウィンドウを操作している間に、確認が落ちる）。無効な項目は、実際のキー操作と同じく、何も起きない。
//   - それ以外（設定画面のEscなど。`before-input-event`で受ける）: `webContents.sendInputEvent`で送る。フォーカスがなくても届く。
// DevTools Protocolの`Input.dispatchKeyEvent`は、ページ内のハンドラにしか届かないので使わない。
//
// 通らないもの: OSからChromiumへ届く最初の段階（IMEや、OSが先に取るキー）と、キーそのものがメニューの項目に結びつく段階。
// ネイティブのダイアログへも届かない。
//
//   Viewerの起動に`--inspect=<port>`を付ける
//   const keys = await connectKeys(port);
//   await keys.press('Ctrl+,');

const MODIFIERS = { ctrl: 'control', control: 'control', shift: 'shift', alt: 'alt', option: 'alt', meta: 'meta', command: 'meta', cmd: 'meta' };
const KEY_ALIASES = { esc: 'Escape', plus: '+', return: 'Enter' };

/**
 * 'Ctrl+,'・'Esc'・'F5' のような指定を、`sendInputEvent`の引数（keyCodeと修飾キー）へ直す。
 * メニューのaccelerator（'CommandOrControl+,'）も読める。`CommandOrControl`は、macOSではCmd、それ以外ではCtrl。
 */
function parseKey(spec, platform = process.platform) {
  // 末尾が'+'なら、キー自身が'+'（'Ctrl++'・'+'）。区切りの'+'と見分けるため、先に取り除く
  const plusKey = spec.endsWith('+');
  const parts = (plusKey ? spec.slice(0, -1) : spec).split('+').filter(Boolean);
  const key = plusKey ? '+' : parts.pop();
  const modifiers = parts.map((name) => {
    const lower = name.toLowerCase();
    if (lower === 'commandorcontrol' || lower === 'cmdorctrl') return platform === 'darwin' ? 'meta' : 'control';
    const modifier = MODIFIERS[lower];
    if (!modifier) throw new Error(`知らない修飾キー: ${name}（${spec}）`);
    return modifier;
  });
  return { keyCode: KEY_ALIASES[key.toLowerCase()] ?? key, modifiers };
}

/** 表記のゆれ（大文字小文字・修飾キーの順・別名）をなくした、比べるための形。 */
function shortcutId(spec, platform) {
  const { keyCode, modifiers } = parseKey(spec, platform);
  return `${[...new Set(modifiers)].sort().join('+')}+${keyCode.toLowerCase()}`;
}

/**
 * メニューの項目（`{path, accelerator, enabled}`の一覧）から、指定のキーに当たる項目を探す。なければ`null`。
 * 同じキーの項目が複数あるときは、有効なものを先にする。読めないacceleratorの項目は、飛ばす。
 */
function findMenuShortcut(items, spec, platform = process.platform) {
  const wanted = shortcutId(spec, platform);
  const hits = items.filter((item) => {
    try { return shortcutId(item.accelerator, platform) === wanted; } catch { return false; }
  });
  return hits.find((item) => item.enabled) ?? hits[0] ?? null;
}

async function openInspector(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('メインプロセスのインスペクターへ接続できません')));
  });
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => { const m = JSON.parse(event.data); pending.get(m.id)?.(m); });
  const evaluate = (expression) => new Promise((resolve, reject) => {
    const i = ++id;
    pending.set(i, (m) => {
      pending.delete(i);
      const failure = m.result?.exceptionDetails;
      if (failure) reject(new Error(failure.exception?.description ?? failure.text));
      else resolve(m.result.result.value);
    });
    ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
  });
  return { evaluate, close: () => ws.close() };
}

const electronInMain = "process.mainModule.require('electron')";

/** メインプロセスで、メニューの全項目（サブメニューを含む）のacceleratorを集める。 */
const LIST_MENU_ITEMS = `(() => {
  const menu = ${electronInMain}.Menu.getApplicationMenu();
  const found = [];
  const walk = (items, path) => items.forEach((item, index) => {
    const here = [...path, index];
    if (item.accelerator) found.push({ path: here, accelerator: String(item.accelerator), enabled: item.enabled });
    if (item.submenu) walk(item.submenu.items, here);
  });
  if (menu) walk(menu.items, []);
  return JSON.stringify(found);
})()`;

/**
 * メインプロセスへ接続して、キーを送る関数を返す。
 * @param {number} inspectPort Viewerを`--inspect=<port>`で起動したときのport
 * @param {{ pageUrl?: string, settleMs?: number }} [options] `pageUrl`: キーを受けるウィンドウのURLの一部（既定: chrome.html）。`settleMs`: 送ったあとの待ち
 */
async function connectKeys(inspectPort, { pageUrl = 'chrome.html', settleMs = 300 } = {}) {
  let target;
  // 起動直後は、インスペクターが、まだ待ち受けていないことがある
  for (let attempt = 0; !target; attempt++) {
    try {
      target = (await (await fetch(`http://127.0.0.1:${inspectPort}/json`)).json())[0];
    } catch {
      if (attempt >= 50) throw new Error('メインプロセスのインスペクターが起動しません');
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
  const inspector = await openInspector(target.webSocketDebuggerUrl);
  const findWindowContents = `${electronInMain}.webContents.getAllWebContents().find((w) => w.getURL().includes(${JSON.stringify(pageUrl)}))`;
  return {
    /**
     * キーを1回押す（'Ctrl+,'・'Esc'・'F5' など）。メニューのショートカットなら項目を呼び、それ以外はキーを送る。
     * @returns {Promise<'menu'|'menu-disabled'|'key'>} どの経路で処理したか
     */
    async press(spec) {
      const hit = findMenuShortcut(JSON.parse(await inspector.evaluate(LIST_MENU_ITEMS)), spec);
      let how;
      if (hit && !hit.enabled) {
        how = 'menu-disabled';   // 実際のキー操作でも、無効な項目のショートカットは、何も起こさない
      } else if (hit) {
        const clicked = await inspector.evaluate(`(() => {
          const { Menu, BrowserWindow } = ${electronInMain};
          let item = { submenu: Menu.getApplicationMenu() };
          for (const index of ${JSON.stringify(hit.path)}) item = item.submenu.items[index];
          const wc = ${findWindowContents};
          item.click({}, wc ? BrowserWindow.fromWebContents(wc) : undefined, wc);
          return true;
        })()`);
        if (!clicked) throw new Error(`メニュー項目を呼べません（${spec}）`);
        how = 'menu';
      } else {
        const { keyCode, modifiers } = parseKey(spec);
        const sent = await inspector.evaluate(`(() => {
          const wc = ${findWindowContents};
          if (!wc) return false;
          for (const type of ['keyDown', 'keyUp']) wc.sendInputEvent({ type, keyCode: ${JSON.stringify(keyCode)}, modifiers: ${JSON.stringify(modifiers)} });
          return true;
        })()`);
        if (!sent) throw new Error(`キーを受けるウィンドウが見つかりません（${pageUrl}）`);
        how = 'key';
      }
      await new Promise((resolve) => setTimeout(resolve, settleMs));
      return how;
    },
    close: () => inspector.close(),
  };
}

module.exports = { connectKeys, parseKey, findMenuShortcut };
