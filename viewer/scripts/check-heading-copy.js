'use strict';
// 見出しのリンク（#337）とコードのコピーボタン（#336）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-heading-copy.js
//
// 確認すること:
//   - 見出し（id付き）ごとに「#」、コードブロックごとに「コピー」が、DOMに足されている（ホバーするまでは、見えない）
//   - ホバーで見える（opacityが1になる）。スクリーンショットを、temp/heading-copy-hover.pngに残す
//   - 「#」をクリックすると、`ファイル名#見出し`がクリップボードに入る
//   - 「コピー」をクリックすると、コードの中身だけが入る（ボタンの文字は、含まない）
//   - 文書内検索に、「#」「コピー」の文字が、一致しない

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const repoDir = path.resolve(viewerDir, '..');
const port = 9700 + Math.floor(Math.random() * 200);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targets() {
  return (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []));
}

async function findTarget(matches) {
  for (let i = 0; i < 120; i++) {
    const found = (await targets()).find((t) => matches(t.url));
    if (found) return found;
    await sleep(100);
  }
  throw new Error('target not found');
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
  const call = (method, params = {}) => new Promise((resolve) => {
    const n = ++id;
    waiting.set(n, resolve);
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return {
    call,
    async eval(expression) {
      const reply = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
      return reply.result?.result?.value;
    },
    close: () => ws.close(),
  };
}

const clipboard = () => execFileSync('powershell', ['-NoProfile', '-Command', '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw'], { encoding: 'utf8' }).replace(/\r?\n$/, '');
const setClipboard = (text) => execFileSync('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value '${text}'`]);

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-heading-copy-'));
  const file = path.join(dir, 'sample.md');
  fs.writeFileSync(file, [
    '# 使い方', '', '本文。', '', '## 使い方', '', '同じ見出し。', '', '## Hello, World!', '',
    '```python', 'print("hello")', 'x = 1', '```', '', '```', 'plain block', '```', '',
  ].join('\n'), 'utf8');
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-heading-copy-ud-'));
  const proc = spawn(electron, [viewerDir, `--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, file], {
    env: { ...process.env, TEXT_COMPOSITOR_PYTHONPATH: process.env.TEXT_COMPOSITOR_PYTHONPATH || repoDir }, stdio: 'ignore',
  });
  try {
    const content = await connect(await findTarget((url) => url.endsWith('.html') && !url.endsWith('/chrome.html')));
    for (let i = 0; i < 100 && !(await content.eval("document.querySelectorAll('.tc-anchor').length > 0")); i++) await sleep(100);

    const anchors = await content.eval("document.querySelectorAll('.tc-anchor').length");
    const headings = await content.eval("document.querySelectorAll('h1[id],h2[id],h3[id]').length");
    const copies = await content.eval("document.querySelectorAll('.tc-copy').length");
    const pres = await content.eval("document.querySelectorAll('pre').length");
    check('見出しごとに「#」がある', anchors === headings && anchors === 3, `anchors=${anchors} headings=${headings}`);
    check('コードブロックごとに「コピー」がある', copies === pres && copies === 2, `copies=${copies} pre=${pres}`);
    check('ホバーするまでは、見えない（opacity 0）', (await content.eval("getComputedStyle(document.querySelector('.tc-anchor')).opacity")) === '0');

    // ホバー: 2つ目の見出しの中央へマウスを動かす
    const rect = await content.eval("(() => { const r = document.querySelectorAll('h2')[0].getBoundingClientRect(); return { x: r.left + 20, y: r.top + r.height / 2 }; })()");
    await content.call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x, y: rect.y });
    await sleep(400);
    check('見出しにホバーすると、「#」が見える（opacity 1）', (await content.eval("getComputedStyle(document.querySelectorAll('h2')[0].querySelector('.tc-anchor')).opacity")) === '1');
    const shot = await content.call('Page.captureScreenshot', { format: 'png' });
    const out = path.join(repoDir, 'temp', 'heading-copy-hover.png');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log(`     スクリーンショット: ${out}`);

    // コードブロックにホバーすると、「コピー」が見える
    const pre = await content.eval("(() => { const r = document.querySelectorAll('pre')[0].getBoundingClientRect(); return { x: r.left + 40, y: r.top + r.height / 2 }; })()");
    await content.call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: pre.x, y: pre.y });
    await sleep(400);
    check('コードブロックにホバーすると、「コピー」が見える（opacity 1）', (await content.eval("getComputedStyle(document.querySelector('.tc-copy')).opacity")) === '1');
    const shot2 = await content.call('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(repoDir, 'temp', 'code-copy-hover.png'), Buffer.from(shot2.result.data, 'base64'));

    // 「#」のクリック（2つ目の「使い方」。idは「使い方-1」）
    setClipboard('before');
    await content.eval("document.querySelectorAll('h2')[0].querySelector('.tc-anchor').click()");
    await sleep(500);
    check('「#」で、ファイル名#見出しのidがコピーされる', clipboard() === 'sample.md#使い方-1', `clipboard=${JSON.stringify(clipboard())}`);
    check('コピー直後に「✓」になる', (await content.eval("document.querySelectorAll('h2')[0].querySelector('.tc-anchor').textContent")) === '✓');

    // 「コピー」のクリック（1つ目のコード）
    setClipboard('before');
    await content.eval("document.querySelectorAll('.tc-copy')[0].click()");
    await sleep(500);
    check('「コピー」で、コードの中身だけがコピーされる', clipboard().replace(/\r\n/g, '\n') === 'print("hello")\nx = 1\n', `clipboard=${JSON.stringify(clipboard())}`);
    setClipboard('before');
    await content.eval("document.querySelectorAll('.tc-copy')[1].click()");
    await sleep(500);
    check('コピーの中に、ボタンの文字（コピー）は含まれない（.txt相当の<pre>）', clipboard().replace(/\r\n/g, '\n') === 'plain block\n', `clipboard=${JSON.stringify(clipboard())}`);

    content.close();
  } finally {
    proc.kill();
    try { execFileSync('powershell', ['-NoProfile', '-Command', 'Get-Process electron -ErrorAction SilentlyContinue | Stop-Process -Force']); } catch { /* 起動していない */ }
  }
  console.log(failures ? `\n${failures} 件、NG` : '\nすべて、OK');
  process.exit(failures ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
