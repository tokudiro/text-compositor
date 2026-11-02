'use strict';
// 設定画面のバージョン表示（#567）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-app-version.js
//   （Windowsでは、パスは、`C:/…`の形で渡す）
//
// 確認すること:
//   - 設定画面に、バージョンの行が出る
//   - 値が、package.jsonのバージョン（app.getVersion()の元）と同じ
//   - 値を、選択してコピーできる（user-select: text）

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const expected = require(path.join(viewerDir, 'package.json')).version;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function findTarget(port, pattern) {
  for (let i = 0; i < 100; i++) {
    const targets = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []);
    const found = targets.find((t) => pattern.test(t.url));
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
  return async (expression) => {
    const n = ++id;
    const reply = await new Promise((resolve) => {
      waiting.set(n, resolve);
      ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
    });
    if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
    return reply.result?.result?.value;
  };
}

async function waitFor(read, predicate, timeoutMs = 10000) {
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
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-version-'));
  const doc = path.join(dir, 'a.md');
  fs.writeFileSync(doc, '# 見出し\n\n本文です。\n');
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  const port = 9900 + Math.floor(Math.random() * 900);
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, doc], { env: { ...process.env, VIEWER_INACTIVE: '1' }, stdio: ['ignore', 'ignore', 'pipe'] });
  try {
    const evalChrome = await connect(await findTarget(port, /chrome\.html/));
    await waitFor(() => evalChrome("document.getElementById('file-name').textContent"), (name) => name === 'a.md');
    await evalChrome("document.getElementById('settings-button').click()");
    const shown = await waitFor(() => evalChrome("document.getElementById('app-version').textContent"), (text) => !!text);
    check('設定画面に、バージョンが出る', !!shown, JSON.stringify(shown));
    check(`値が、package.jsonのバージョン（${expected}）と同じ`, shown === expected);
    const selectable = await evalChrome("getComputedStyle(document.getElementById('app-version')).userSelect");
    check('選択してコピーできる（user-select: text）', selectable === 'text', selectable);
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
