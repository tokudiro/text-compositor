'use strict';
// 文書の選択（#409）を、実際にViewerを起動して確認する（手動。Windowsのみ。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-selection.js
//   （Windowsでは、パスは、`C:/…`の形で渡す。Git Bashの`/c/…`だと、ワーカーが起動しない）
//
// 確認すること（右クリックのメニューそのものは、OSのメニューのため、自動では押せない。項目の内容は、単体テストで確認している）:
//   - アプリのメニューに「編集」が無くても、`Ctrl+C`で、選択範囲が、クリップボードへ入る
//   - `Ctrl+A`で、文書全体が選択される

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます（クリップボードの読み取りに、PowerShellを使うため）。');
  process.exit(0);
}

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9900 + Math.floor(Math.random() * 90);
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
    close: () => ws.close(),
  };
}

async function waitFor(read, predicate, timeoutMs = 8000) {
  const start = performance.now();
  let last;
  while (performance.now() - start < timeoutMs) {
    try { last = await read(); } catch { last = undefined; }
    if (predicate(last)) return last;
    await sleep(50);
  }
  return last;
}

// 出力の文字コードを、UTF-8にそろえる（既定のままだと、日本語が、文字化けする）
const powershell = (command) => execFileSync('powershell', ['-NoProfile', '-Command', `[Console]::OutputEncoding = [Text.Encoding]::UTF8; ${command}`], { encoding: 'utf8' });

/** Ctrl+<文字>を、内容のビューへ、キー入力として送る（メニューの割り当てを通らない、Chromiumの既定の動きを見るため）。 */
async function pressCtrl(view, key, code, keyCode) {
  const base = { modifiers: 2, key, code, windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode };
  await view.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base });
  await view.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-selection-'));
  const doc = path.join(dir, 'a.md');
  fs.writeFileSync(doc, '# 見出しの文字\n\n1つ目の段落です。\n\n2つ目の段落です。\n');
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, doc], { env: process.env, stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  try {
    const chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(() => chrome.eval("document.getElementById('file-name').textContent"), (name) => name === 'a.md');
    const content = await connect(await waitFor(async () => (await targets()).find((t) => t.type === 'page' && /\.html$/.test(t.url) && !/chrome\.html/.test(t.url)), (t) => Boolean(t)));
    await waitFor(() => content.eval("document.querySelector('h1')?.textContent ?? ''"), (text) => text.startsWith('見出しの文字'));

    // -- Ctrl+C --------------------------------------------------------------------------------
    powershell("Set-Clipboard -Value 'SENTINEL'");
    await content.eval(`(() => { const p = document.querySelectorAll('p')[0]; const range = document.createRange(); range.selectNodeContents(p); const s = getSelection(); s.removeAllRanges(); s.addRange(range); })()`);
    await pressCtrl(content, 'c', 'KeyC', 67);
    const copied = await waitFor(() => powershell('Get-Clipboard -Raw').trim(), (text) => text !== 'SENTINEL');
    check('Ctrl+Cで、選択した文字が、クリップボードへ入る', copied === '1つ目の段落です。', JSON.stringify(copied));

    // -- Ctrl+A --------------------------------------------------------------------------------
    await content.eval('getSelection().removeAllRanges()');
    await pressCtrl(content, 'a', 'KeyA', 65);
    const selected = await waitFor(() => content.eval('getSelection().toString()'), (text) => typeof text === 'string' && text.includes('2つ目'));
    check('Ctrl+Aで、文書全体が選択される', /見出しの文字/.test(selected) && /1つ目/.test(selected) && /2つ目/.test(selected), JSON.stringify(selected));
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
