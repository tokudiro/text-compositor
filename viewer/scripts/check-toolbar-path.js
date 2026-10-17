'use strict';
// ツールバーに、フォルダのパスを出さない（#497）ことを、実際にViewerを起動して確認する。Electronと、Pythonのワーカーが要る（CIでは動かさない）。
//
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-toolbar-path.js [--screenshot <png>]
//
// 右クリックのメニューは、OSのメニューで、この確認からは操作できない。メニューの項目の出し分けは、単体テスト（test/path-menu.test.js）が確認する。
//
// 確認すること（深いフォルダのファイルを開く）:
//   1. ツールバーに、フォルダのパスが出ない。ファイル名が、省略されずに出る。
//   2. ホバーのツールチップ（title）は、フルパス。
//   3. 右側のボタン（ズームなど）が、押し出されず、見えている。

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9900 + Math.floor(Math.random() * 90);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const screenshotPath = process.argv.includes('--screenshot') ? process.argv[process.argv.indexOf('--screenshot') + 1] : null;

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

async function waitTarget(match, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const targets = await (await fetch(`http://127.0.0.1:${port}/json`).catch(() => ({ json: async () => [] }))).json();
    const found = targets.find((t) => match(t.url));
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
  const call = (method, params) => new Promise((resolve) => { const n = ++id; waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); });
  return {
    eval: async (expression) => (await call('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value,
    screenshot: async (file) => fs.writeFileSync(file, Buffer.from((await call('Page.captureScreenshot', { format: 'png' })).result.data, 'base64')),
    close: () => ws.close(),
  };
}

async function waitFor(predicate, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) return true;
    await sleep(100);
  }
  return false;
}

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-path-'));
  // 深く、長い名前のフォルダ（以前は、フォルダのパスが、ファイル名の右に出て、末尾が省略された）
  const deep = path.join(root, ...Array.from({ length: 8 }, (_, i) => `very-long-folder-name-number-${i + 1}`));
  fs.mkdirSync(deep, { recursive: true });
  const md = path.join(deep, 'README.md');
  fs.writeFileSync(md, '# 深いフォルダの文書\n\n本文。\n');
  const userData = path.join(root, 'user-data');
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { stdio: 'ignore' });

  try {
    const chrome = await connect(await waitTarget((url) => url.endsWith('/chrome.html')));
    await waitFor(async () => (await chrome.eval("document.getElementById('file-name').textContent")) === 'README.md');
    await waitFor(async () => /更新/.test(await chrome.eval("document.getElementById('status').textContent")));

    check('ツールバーに、フォルダのパスの要素が無い', (await chrome.eval("document.getElementById('file-dir')")) === null);
    const shown = JSON.parse(await chrome.eval("JSON.stringify({ text: document.getElementById('file').innerText, name: document.getElementById('file-name').textContent, "
      + "truncated: document.getElementById('file-name').scrollWidth > document.getElementById('file-name').clientWidth })"));
    check('ツールバーの文字は、ファイル名だけ（フォルダの文字が、含まれない）', shown.text === 'README.md' && shown.name === 'README.md', JSON.stringify(shown));
    check('ファイル名は、省略されずに出る', shown.truncated === false);
    const title = await chrome.eval("document.getElementById('file').title");
    check('ホバーのツールチップは、フルパス', title === md, title);
    const zoomVisible = await chrome.eval("(() => { const b = document.getElementById('zoom').getBoundingClientRect(); return b.right <= window.innerWidth && b.width > 0; })()");
    check('右側のボタン（ズーム）が、見えている', zoomVisible === true);
    if (screenshotPath) { await chrome.screenshot(screenshotPath); console.log(`     画面を保存した: ${screenshotPath}`); }
    chrome.close();
  } catch (error) {
    check('確認を最後まで実行できた', false, error.message);
  } finally {
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗: ${failures}件`);
  process.exit(failures === 0 ? 0 : 1);
})();
