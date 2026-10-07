'use strict';
// 図の拡大表示（#338）を、実際にViewerを起動して確認する（手動。Windowsのみ。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-lightbox.js
//   （Windowsでは、パスは、`C:/…`の形で渡す）
//
// 確認すること:
//   - 図（Mermaid）をクリックすると、オーバーレイが開く。ホイールで拡大し、ドラッグでパンし、ダブルクリックで収める大きさに戻る
//   - Escと、背景のクリックで閉じる。図の上のクリックでは、閉じない
//   - オーバーレイの図に、ダークのときだけ、反転フィルター（#209）が掛かる

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます。');
  process.exit(0);
}

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9900 + Math.floor(Math.random() * 900);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targets() {
  return (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []));
}

async function findTarget(pattern) {
  for (let i = 0; i < 100; i++) {
    const found = (await targets()).find((t) => pattern.test(t.url));
    if (found) return found;
    await sleep(100);
  }
  throw new Error(`target not found: ${pattern}`);
}

async function connect(target) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const waiting = new Map();
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
  };
  const send = (method, params = {}) => new Promise((resolve) => { const n = ++id; waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); });
  return {
    send,
    async eval(expression) {
      const reply = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
      return reply.result?.result?.value;
    },
  };
}

async function waitFor(read, predicate, timeoutMs = 20000) {
  const start = performance.now();
  let last;
  while (performance.now() - start < timeoutMs) {
    try { last = await read(); } catch { last = undefined; }
    if (predicate(last)) return last;
    await sleep(100);
  }
  return last;
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-lightbox-'));
  const doc = path.join(dir, 'a.md');
  fs.writeFileSync(doc, '# 図\n\n```mermaid\nflowchart LR\n  A[開始] --> B[終了]\n```\n\n本文です。\n');
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, doc], { env: process.env, stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  try {
    const content = await connect(await waitFor(async () => (await targets()).find((t) => t.type === 'page' && /\.html$/.test(t.url) && !/chrome\.html/.test(t.url)), (t) => Boolean(t)));
    await waitFor(() => content.eval("document.querySelector('.diagram img')?.naturalWidth ?? 0"), (n) => n > 0);

    const click = async (x, y, clickCount = 1) => {
      await content.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount });
      await content.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount });
    };
    const imageCenter = () => content.eval("(() => { const r = document.querySelector('.diagram:not(.tc-lightbox *) img').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()");
    const transform = () => content.eval("document.querySelector('.tc-lightbox .diagram')?.style.transform ?? null");
    const parse = (t) => { const m = /translate\(([-\d.e]+)px, ([-\d.e]+)px\) scale\(([-\d.e]+)\)/.exec(t ?? ''); return m ? { x: +m[1], y: +m[2], scale: +m[3] } : null; };
    const isOpen = () => content.eval("Boolean(document.querySelector('.tc-lightbox'))");

    // -- 開く ------------------------------------------------------------------------------------
    check('図の上は、拡大できることを示すカーソル（zoom-in）', (await content.eval("getComputedStyle(document.querySelector('.diagram img')).cursor")) === 'zoom-in');
    const [cx, cy] = await imageCenter();
    await click(cx, cy);
    check('図をクリックすると、オーバーレイが開く', await waitFor(isOpen, (open) => open === true));
    const fitWidth = await content.eval("document.querySelector('.tc-lightbox img').getBoundingClientRect().width");
    const viewport = await content.eval('[window.innerWidth, window.innerHeight]');
    check('開いたときは、画面に収まる大きさで、中央にある', fitWidth > 0 && fitWidth <= viewport[0] && parse(await transform())?.scale === 1, `幅 ${Math.round(fitWidth)} / 画面 ${viewport[0]}`);

    // -- ホイールで拡大 --------------------------------------------------------------------------
    await content.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: viewport[0] / 2, y: viewport[1] / 2, deltaX: 0, deltaY: -300 });
    const zoomed = parse(await waitFor(transform, (t) => parse(t)?.scale > 1));
    check('ホイールを上へ回すと、拡大する', zoomed?.scale > 1, `倍率 ${zoomed?.scale?.toFixed(2)}`);
    await content.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: viewport[0] / 2, y: viewport[1] / 2, deltaX: 0, deltaY: 100000 });
    const minimum = parse(await waitFor(transform, (t) => parse(t)?.scale <= 0.5 + 1e-9));
    check('縮小は、0.5倍まで', minimum?.scale === 0.5, `倍率 ${minimum?.scale}`);
    await content.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: viewport[0] / 2, y: viewport[1] / 2, deltaX: 0, deltaY: -100000 });
    const maximum = parse(await waitFor(transform, (t) => parse(t)?.scale >= 32 - 1e-9));
    check('拡大は、32倍まで', maximum?.scale === 32, `倍率 ${maximum?.scale}`);

    // -- ダブルクリックで戻す、ドラッグでパン -----------------------------------------------------
    await click(viewport[0] / 2, viewport[1] / 2, 2);
    const reset = parse(await waitFor(transform, (t) => parse(t)?.scale === 1));
    check('ダブルクリックで、画面に収める大きさに戻る', reset?.scale === 1 && reset.x === 0 && reset.y === 0);
    await content.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 200, y: 200, button: 'left', clickCount: 1 });
    await content.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 260, y: 230, button: 'left', buttons: 1 });
    await content.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 260, y: 230, button: 'left', clickCount: 1 });
    const panned = parse(await transform());
    check('ドラッグで、パンする', panned?.x === 60 && panned?.y === 30, JSON.stringify(panned));
    check('ドラッグの後のクリックでは、閉じない', await isOpen());

    // -- ダークの反転フィルター ------------------------------------------------------------------
    const filterOf = () => content.eval("getComputedStyle(document.querySelector('.tc-lightbox img')).filter");
    await content.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });
    check('ライトでは、オーバーレイの図に、フィルターが掛からない', (await filterOf()) === 'none', await filterOf());
    await content.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
    check('ダークでは、オーバーレイの図に、反転フィルター（invert）が掛かる', /invert/.test(await filterOf()), await filterOf());
    await content.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });

    // -- 閉じる ----------------------------------------------------------------------------------
    await click(viewport[0] / 2 + 60, viewport[1] / 2 + 30);   // 図の上（パンで動かした位置）のクリックでは、閉じない
    check('図の上のクリックでは、閉じない', await isOpen());
    await content.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await content.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    check('Escで、閉じる', await waitFor(isOpen, (open) => open === false) === false);

    await click(cx, cy);
    await waitFor(isOpen, (open) => open === true);
    await click(5, 5);
    check('背景のクリックで、閉じる', await waitFor(isOpen, (open) => open === false) === false);
  } catch (error) {
    console.log(`NG   確認を最後まで実行できた  ${error.message}`);
    results.push(false);
  } finally {
    proc.kill();
    await sleep(300);
    fs.rmSync(dir, { recursive: true, force: true });
  }
  const failed = results.filter((ok) => !ok).length;
  console.log(failed ? `\n失敗: ${failed}件` : '\nすべて成功');
  process.exit(failed ? 1 : 0);
})();
