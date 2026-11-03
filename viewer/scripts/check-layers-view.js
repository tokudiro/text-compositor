'use strict';
// 重ね（`::: layers`。#560）の、Viewerでの見え方を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-layers-view.js
//
// 確認すること:
//   - ダークでは、部品がすべて図の重ねだけ、反転する（画像が混じる重ねは、反転しない）
//   - 重ねをクリックすると、拡大表示が開く。中の重ねは、反転のクラスと、原寸の比率を保つ。Escで閉じる
//   - 拡大表示の中で右クリックすると、合成した1枚の保存・コピーのメニューが出る
// ダークのスクリーンショットは、temp/layers-dark.pngに残す。

const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const repoDir = path.resolve(viewerDir, '..');
const port = 9700 + Math.floor(Math.random() * 100);
const inspectPort = port + 100;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const waiting = new Map();
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
  };
  const ready = new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const call = (method, params = {}) => new Promise((resolve) => {
    const n = ++id;
    waiting.set(n, resolve);
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return {
    ready, call,
    async eval(expression) {
      const reply = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.exception?.description ?? reply.result.exceptionDetails.text);
      return reply.result?.result?.value;
    },
    close: () => ws.close(),
  };
}

async function waitTarget(p, matches) {
  for (let i = 0; i < 150; i++) {
    const found = (await fetch(`http://127.0.0.1:${p}/json`).then((r) => r.json()).catch(() => [])).find(matches);
    if (found) return found;
    await sleep(100);
  }
  throw new Error(`target not found (port ${p})`);
}

function crc32(buf) {
  let crc = 0xffffffff;
  for (const b of buf) { let c = (crc ^ b) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; crc = (crc >>> 8) ^ c; }
  return (crc ^ 0xffffffff) >>> 0;
}
function pngFile(w, h) {
  const rows = [];
  for (let y = 0; y < h; y++) {
    const row = Buffer.alloc(1 + w * 3);
    for (let x = 0; x < w; x++) { row[1 + x * 3] = 255 - Math.floor(x * 255 / w); row[2 + x * 3] = 120 + Math.floor(y * 100 / h); row[3 + x * 3] = Math.floor(x * 255 / w); }
    rows.push(row);
  }
  const chunk = (type, data) => { const body = Buffer.concat([Buffer.from(type), data]); const out = Buffer.alloc(12 + data.length); out.writeUInt32BE(data.length, 0); body.copy(out, 4); out.writeUInt32BE(crc32(body), 8 + data.length); return out; };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))), chunk('IEND', Buffer.alloc(0))]);
}

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

const SVG_FENCE = (word) => ['```svg', `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"><rect width="120" height="60" fill="#fff"/><text x="10" y="35" fill="#000" font-size="20">${word}</text></svg>`, '```'];

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-layers-view-'));
  fs.writeFileSync(path.join(dir, 'photo.png'), pngFile(240, 140));
  const file = path.join(dir, 'sample.md');
  fs.writeFileSync(file, [
    '# 見え方', '',
    '::: layers 図だけの重ね', ...SVG_FENCE('fences'), ':::', '',
    '::: layers 写真が混じる重ね', '![](photo.png)', '', ...SVG_FENCE('photo'), ':::', '',
  ].join('\n'), 'utf8');
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-layers-view-ud-'));
  const proc = spawn(electron, [viewerDir, `--remote-debugging-port=${port}`, `--inspect=${inspectPort}`, `--user-data-dir=${userData}`, file], {
    env: { ...process.env, VIEWER_INACTIVE: '1', TEXT_COMPOSITOR_PYTHONPATH: process.env.TEXT_COMPOSITOR_PYTHONPATH || repoDir }, stdio: 'ignore',
  });
  try {
    const content = connect((await waitTarget(port, (t) => t.url.endsWith('.html') && !t.url.endsWith('/chrome.html'))).webSocketDebuggerUrl);
    await content.ready;
    for (let i = 0; i < 200 && !(await content.eval("document.querySelectorAll('svg.layers').length === 2")); i++) await sleep(100);
    const main = connect((await waitTarget(inspectPort, () => true)).webSocketDebuggerUrl);
    await main.ready;
    await main.eval(`(() => {
      const { Menu } = process.mainModule.require('electron');
      globalThis.__templates = [];
      Menu.buildFromTemplate = (template) => { globalThis.__templates.push(template); return { popup() {} }; };
      return true;
    })()`);

    // ダーク
    await content.call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
    await sleep(500);
    const filters = await content.eval("[...document.querySelectorAll('svg.layers')].map((s) => getComputedStyle(s).filter)");
    check('ダーク: 図だけの重ねは、反転する', filters[0].startsWith('invert'), filters[0]);
    check('ダーク: 写真が混じる重ねは、反転しない', filters[1] === 'none', filters[1]);
    const shot = await content.call('Page.captureScreenshot', { format: 'png' });
    const out = path.join(repoDir, 'temp', 'layers-dark.png');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log(`     スクリーンショット: ${out}`);

    // 拡大表示
    const center = (selector, index) => content.eval(`(() => { const r = document.querySelectorAll(${JSON.stringify(selector)})[${index}].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    const mouse = async (type, p, button = 'left') => content.call('Input.dispatchMouseEvent', { type, x: p.x, y: p.y, button, clickCount: 1 });
    check('マウスを重ねると、拡大のカーソルになる', (await content.eval("getComputedStyle(document.querySelector('svg.layers')).cursor")) === 'zoom-in');
    const point = await center('svg.layers', 0);
    await mouse('mousePressed', point); await mouse('mouseReleased', point);
    await sleep(400);
    check('クリックで、拡大表示が開く', await content.eval("!!document.querySelector('.tc-lightbox svg.layers')"));
    const zoomed = await content.eval(`(() => { const s = document.querySelector('.tc-lightbox svg.layers'); if (!s) return null; const r = s.getBoundingClientRect();
      return { w: r.width, h: r.height, ratio: r.width / r.height, filter: getComputedStyle(s).filter, window: innerWidth, hasStyleMax: s.style.maxWidth }; })()`);
    check('拡大表示の中の重ねは、本文より大きく、縦横比（2:1）を保つ', zoomed && zoomed.w > 120 && Math.abs(zoomed.ratio - 2) < 0.02, JSON.stringify(zoomed));
    check('拡大表示の中でも、反転が掛かる', zoomed && zoomed.filter.startsWith('invert'));

    // 拡大表示の中で右クリック
    await main.eval('globalThis.__templates.length = 0');
    const inside = await content.eval("(() => { const r = document.querySelector('.tc-lightbox svg.layers').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()");
    await mouse('mousePressed', inside, 'right'); await mouse('mouseReleased', inside, 'right');
    for (let i = 0; i < 50 && !(await main.eval('globalThis.__templates.length')); i++) await sleep(100);
    const labels = JSON.parse(await main.eval('JSON.stringify((globalThis.__templates[0] || []).map((item) => item.label || item.type))'));
    check('拡大表示の中の右クリックで、保存・コピーのメニューが出る', labels.includes('画像（SVG）を保存…') && labels.includes('画像をコピー'), JSON.stringify(labels));

    await content.eval("document.querySelector('.tc-lightbox-close').click()");
    await sleep(300);
    check('閉じる', await content.eval("!document.querySelector('.tc-lightbox')"));

    // 写真が混じる重ねも、開ける
    const second = await center('svg.layers', 1);
    await mouse('mousePressed', second); await mouse('mouseReleased', second);
    await sleep(400);
    check('写真が混じる重ねも、拡大表示が開く', await content.eval("!!document.querySelector('.tc-lightbox svg.layers')"));
    content.close();
    main.close();
  } finally {
    proc.kill();
    try { execFileSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* すでに終了している */ }
  }
  console.log(failures ? `\n${failures} 件、NG` : '\nすべて、OK');
  process.exit(failures ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
