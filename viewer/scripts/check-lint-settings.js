'use strict';
// lint（原稿の警告）のON/OFF（#271）を、実際にViewerを起動して確認する。Electronと、Pythonのワーカーが要る（CIでは動かさない）。
//
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-lint-settings.js [--screenshot <png>]
//
// 手元の設定を変えないため、ユーザーデータは、使い捨てにする。
//
// 確認すること:
//   1. 既定では、効かなかった太字（`**「重要」**`）の警告が出る。設定画面に、「太字のチェック」の行があり、「出す」が選ばれている。
//   2. 「出さない」を選ぶと、settings.json に lint.bold = false が保存される。
//   3. 更新（再変換）すると、警告が出なくなる。本文は、変わらない（**が、そのまま出る）。
//   4. 「出す」に戻して更新すると、警告が、また出る。

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
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-lint-'));
  const docs = path.join(root, 'docs');
  fs.mkdirSync(docs, { recursive: true });
  const md = path.join(docs, 'doc.md');
  fs.writeFileSync(md, '# lintの確認\n\nこれは**「重要」**です。\n');
  const userData = path.join(root, 'user-data');
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { stdio: 'ignore' });

  try {
    const chrome = await connect(await waitTarget((url) => url.endsWith('/chrome.html')));
    const warnings = async () => Number(await chrome.eval('lastState?.diagnostics?.warnings ?? -1'));
    const boldWarned = async () => (await chrome.eval("JSON.stringify(lastState?.diagnostics?.items ?? [])")).includes('Bold markup');
    const content = async () => {
      const target = await waitTarget((url) => url.endsWith('.html') && !url.endsWith('/chrome.html'));
      const view = await connect(target);
      const text = await view.eval('document.body.innerText');
      view.close();
      return text;
    };
    const savedLint = () => {
      try { return JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8')).lint; } catch { return null; }
    };

    // 1. 既定
    await waitFor(async () => (await warnings()) >= 0 && /更新/.test(await chrome.eval("document.getElementById('status').textContent")));
    check('既定では、効かなかった太字の警告が出る', await boldWarned(), String(await warnings()));
    await chrome.eval('window.viewer.toggleSettings()');
    await waitFor(async () => (await chrome.eval("document.querySelectorAll('#lint-rows input').length")) === 2);
    const row = JSON.parse(await chrome.eval("JSON.stringify({ name: document.getElementById('lint-bold-name')?.textContent, "
      + "on: document.querySelector('input[name=\"lint:bold\"][value=true]')?.checked, off: document.querySelector('input[name=\"lint:bold\"][value=false]')?.checked, "
      + "labelled: document.querySelector('#lint-rows [role=radiogroup]')?.getAttribute('aria-labelledby') })"));
    check('設定画面に、「太字のチェック」の行があり、「出す」が選ばれている', row.name === '太字のチェック' && row.on === true && row.off === false && row.labelled === 'lint-bold-name', JSON.stringify(row));
    if (screenshotPath) { await chrome.eval("document.getElementById('lint-rows').scrollIntoView({ block: 'center' })"); await sleep(300); await chrome.screenshot(screenshotPath); console.log(`     画面を保存した: ${screenshotPath}`); }

    // 2. 「出さない」
    await chrome.eval("document.querySelector('input[name=\"lint:bold\"][value=false]').click()");
    check('「出さない」を選ぶと、settings.json に lint.bold = false が保存される', await waitFor(() => savedLint()?.bold === false), JSON.stringify(savedLint()));
    check('選んだ状態が、画面にも残る', (await chrome.eval("document.querySelector('input[name=\"lint:bold\"][value=false]').checked")) === true);

    // 3. 更新（設定画面を閉じてから、再変換）
    await chrome.eval('window.viewer.toggleSettings()');
    await chrome.eval('window.viewer.reload()');
    check('更新すると、警告が出なくなる', await waitFor(async () => (await warnings()) === 0 && !(await boldWarned())), String(await warnings()));
    check('本文は、変わらない（**が、そのまま出る）', (await content()).includes('**「重要」**'));

    // 4. 「出す」に戻す
    await chrome.eval('window.viewer.toggleSettings()');
    await chrome.eval("document.querySelector('input[name=\"lint:bold\"][value=true]').click()");
    await waitFor(() => savedLint()?.bold === true);
    await chrome.eval('window.viewer.toggleSettings()');
    await chrome.eval('window.viewer.reload()');
    check('「出す」に戻して更新すると、警告が、また出る', await waitFor(boldWarned));
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
