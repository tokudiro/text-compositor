'use strict';
// 重ね（`::: layers`。#560）の右クリック保存を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-layers-save.js
//
// ネイティブのメニューとダイアログは、外から操作できない。そのため、メインプロセスへ`--inspect`で接続して、
// `Menu.buildFromTemplate`（メニューの中身を取り出す）と`dialog.showSaveDialog`（保存先を決めて返す）だけを差し替える。
// 右クリックそのもの（ページの`context-menu`イベント）から、位置の探索・SVGの合成・ファイルの書き出し・PNGへの変換までは、本物が動く。
//
// 確認すること:
//   - 重ねの上の右クリックで、「画像（SVG）を保存…」「画像（PNG）を保存…」が出る。重ねの外では、出ない
//   - SVGは、部品の画像が`data:`で埋め込まれた1枚で、画面用のmax-widthが無く、見出し行が代替テキストに残る
//   - PNGは、PNGの形式で、重ねの全体の大きさの2倍になる

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
    ready,
    call,
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

function png(width, height, [r, g, b]) {
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (buf) => { let c = 0xffffffff; for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const out = Buffer.alloc(8 + data.length + 4);
    out.writeUInt32BE(data.length, 0); body.copy(out, 4); out.writeUInt32BE(crc(body), 8 + data.length);
    return out;
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({ length: width }, () => [r, g, b]).flat())]);
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(Array.from({ length: height }, () => row)))), chunk('IEND', Buffer.alloc(0))]);
}

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-layers-save-'));
  const file = path.join(dir, 'sample.md');
  fs.writeFileSync(path.join(dir, 'base.png'), png(200, 120, [200, 220, 255]));
  fs.writeFileSync(file, [
    '# 重ねの保存', '',
    '::: layers 注釈つきの画面', '![](base.png)', '', '```svg {x=60 y=40}',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 40"><rect width="80" height="40" fill="red"/></svg>', '```', ':::', '',
    '重ねの外の段落。', '',
  ].join('\n'), 'utf8');
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-layers-save-ud-'));
  const proc = spawn(electron, [viewerDir, `--remote-debugging-port=${port}`, `--inspect=${inspectPort}`, `--user-data-dir=${userData}`, file], {
    env: { ...process.env, VIEWER_INACTIVE: '1', TEXT_COMPOSITOR_PYTHONPATH: process.env.TEXT_COMPOSITOR_PYTHONPATH || repoDir }, stdio: 'ignore',
  });
  try {
    const content = connect((await waitTarget(port, (t) => t.url.endsWith('.html') && !t.url.endsWith('/chrome.html'))).webSocketDebuggerUrl);
    await content.ready;
    for (let i = 0; i < 200 && !(await content.eval("!!document.querySelector('svg.layers')")); i++) await sleep(100);
    check('重ねが、1つのインラインSVGとして出ている', await content.eval("document.querySelectorAll('svg.layers').length === 1"));

    const main = connect((await waitTarget(inspectPort, () => true)).webSocketDebuggerUrl);
    await main.ready;
    const saveTo = path.join(dir, 'saved');
    fs.mkdirSync(saveTo);
    await main.eval(`(() => {
      const { Menu, dialog } = process.mainModule.require('electron');
      globalThis.__templates = [];
      Menu.buildFromTemplate = (template) => { globalThis.__templates.push(template); return { popup() {} }; };
      dialog.showSaveDialog = async (_win, options) => ({ canceled: false, filePath: ${JSON.stringify(saveTo)} + '/' + process.mainModule.require('path').basename(options.defaultPath) });
      return true;
    })()`);

    async function rightClick(x, y) {
      await main.eval('globalThis.__templates.length = 0');
      await content.call('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'right', clickCount: 1 });
      await content.call('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'right', clickCount: 1 });
      for (let i = 0; i < 50 && !(await main.eval('globalThis.__templates.length')); i++) await sleep(100);
      return JSON.parse(await main.eval('JSON.stringify((globalThis.__templates[0] || []).map((item) => item.label || item.type))'));
    }

    const box = await content.eval("(() => { const r = document.querySelector('svg.layers').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; })()");
    const outside = await content.eval("(() => { const r = [...document.querySelectorAll('p')].pop().getBoundingClientRect(); return { x: r.left + 10, y: r.top + r.height / 2 }; })()");

    const labelsOutside = await rightClick(outside.x, outside.y);
    check('重ねの外では、画像の保存が出ない', !labelsOutside.some((l) => String(l).includes('画像')), JSON.stringify(labelsOutside));

    const labels = await rightClick(box.x, box.y);
    check('重ねの上で、「画像（SVG）を保存…」「画像（PNG）を保存…」が出る',
      labels.includes('画像（SVG）を保存…') && labels.includes('画像（PNG）を保存…'), JSON.stringify(labels));

    const clickItem = (label) => main.eval(`(() => { globalThis.__templates[0].find((item) => item.label === ${JSON.stringify(label)}).click(); return true; })()`);

    await clickItem('画像（SVG）を保存…');
    const saved = (ext) => fs.readdirSync(saveTo).find((name) => name.endsWith(ext));
    for (let i = 0; i < 100 && !saved('.svg'); i++) await sleep(100);
    const svgPath = saved('.svg') && path.join(saveTo, saved('.svg'));
    check('SVGが保存される', !!svgPath);
    check('ファイル名の既定が、見出し行の文字列になる', saved('.svg') === '注釈つきの画面.svg', saved('.svg'));
    if (svgPath) {
      const svg = fs.readFileSync(svgPath, 'utf8');
      if (process.env.SHOW_SVG) console.log('--- saved svg\n' + svg.replace(/base64,[A-Za-z0-9+/=]{40,}/g, 'base64,...') + '\n--- dom\n' + (await content.eval("document.querySelector('svg.layers').outerHTML")).replace(/base64,[A-Za-z0-9+/=]{40,}/g, 'base64,...'));
      check('部品の画像が、dataとして埋め込まれている（PNGとSVG）',
        /<image href="data:image\/png;base64,/.test(svg) && /<image href="data:image\/svg\+xml;base64,/.test(svg));
      check('部品への参照が、外のファイルに残らない', !/<image href="(?!data:)/.test(svg));
      check('画面用のmax-widthが無く、代替テキストが残る', !/max-width/.test(svg) && svg.includes('aria-label="注釈つきの画面"'));
      // 保存したファイルだけで、全体が描かれる（別のページで、画像として読み込む）
      const drawn = await content.eval(`new Promise((resolve) => { const img = new Image(); img.onload = () => resolve([img.naturalWidth, img.naturalHeight]); img.onerror = () => resolve(null); img.src = 'data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}'; })`);
      check('保存したSVGを、画像として読み込める（200x120）', Array.isArray(drawn) && drawn[0] === 200 && drawn[1] === 120, JSON.stringify(drawn));
    }

    await main.eval('globalThis.__templates.length = 0');
    await rightClick(box.x, box.y);
    await clickItem('画像（PNG）を保存…');
    for (let i = 0; i < 100 && !saved('.png'); i++) await sleep(100);
    const pngPath = saved('.png') && path.join(saveTo, saved('.png'));
    check('PNGが保存される', !!pngPath);
    if (pngPath) {
      const data = fs.readFileSync(pngPath);
      const isPng = data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
      check('PNGの形式で、重ねの全体の大きさの2倍（400x240）', isPng && data.readUInt32BE(16) === 400 && data.readUInt32BE(20) === 240,
        `${data.readUInt32BE(16)}x${data.readUInt32BE(20)}`);
    }
    // 「画像をコピー」: クリップボードの画像が、重ねの全体の大きさの2倍になる
    await main.eval(`(() => { process.mainModule.require('electron').clipboard.clear(); return true; })()`);   // 前の中身が残って、通らないように
    await main.eval('globalThis.__templates.length = 0');
    const labelsForCopy = await rightClick(box.x, box.y);
    check('重ねの上で、「画像をコピー」が出る', labelsForCopy.includes('画像をコピー'), JSON.stringify(labelsForCopy));
    await clickItem('画像をコピー');
    // 貼り付け先と同じ、OS側のクリップボードを読む（STAでないと、画像を読めない）
    const readClipboardImageSize = () => {
      const out = execFileSync('powershell', ['-NoProfile', '-STA', '-Command',
        'Add-Type -AssemblyName System.Windows.Forms; $i = [Windows.Forms.Clipboard]::GetImage(); if ($i) { "$($i.Width)x$($i.Height)" }'], { encoding: 'utf8' }).trim();
      const [width, height] = out ? out.split('x').map(Number) : [0, 0];
      return { width, height };
    };
    let size = { width: 0, height: 0 };
    for (let i = 0; i < 30 && !size.width; i++) {
      await sleep(300);
      size = readClipboardImageSize();
    }
    check('クリップボードの画像が、重ねの全体の大きさの2倍（400x240）', size.width === 400 && size.height === 240, `${size.width}x${size.height}`);
    content.close();
    main.close();
  } finally {
    proc.kill();
    try { execFileSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* すでに終了している */ }
  }
  console.log(failures ? `\n${failures} 件、NG` : '\nすべて、OK');
  process.exit(failures ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
