'use strict';
// 設定画面の開閉を、実際のキー操作で確認する（手動。Windowsのみ。#200）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-window.js
//
// 確認すること:
//   - 設定画面は、Ctrl+,・歯車・「戻る」・Esc で閉じられ、ファイルを開く・再読み込みでも閉じる。
// キーは、メインプロセスへ`--inspect`で接続し、`webContents.sendInputEvent`で送る（#551）。前面のウィンドウに依存しないので、
// 実行中も、ほかの作業ができる。

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { connectKeys } = require('./send-keys');
const { waitFor } = require('./wait-for');

const viewerDir = path.resolve(__dirname, '..');
const electron = require('electron');
const sample = path.join(viewerDir, '..', 'benchmarks', 'html-view', 'fixture', 'fixture.md');
const port = 9400 + Math.floor(Math.random() * 100);
const inspectPort = 9600 + Math.floor(Math.random() * 100);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function connect() {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(targets.find((t) => t.url.includes('chrome.html')).webSocketDebuggerUrl);
  await new Promise((resolve) => ws.addEventListener('open', resolve));
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => { const m = JSON.parse(event.data); pending.get(m.id)?.(m); });
  return (expression) => new Promise((resolve) => {
    const i = ++id;
    pending.set(i, (m) => resolve(m.result.result.value));
    ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
  });
}

async function main() {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-window-'));
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--inspect=${inspectPort}`, `--user-data-dir=${userData}`, viewerDir, sample],
    { env: { ...process.env, VIEWER_INACTIVE: '1' }, stdio: 'ignore' });
  let failures = 0;
  let keys = null;
  try {
    const evaluate = await waitFor(async () => {
      const ev = await connect();
      return (await ev("!!document.getElementById('settings-button')")) ? ev : null;
    }, { label: '画面の表示' });
    keys = await connectKeys(inspectPort);
    // `key:`で始まるaction（'key:Ctrl+,'）は、キーを送る。それ以外は、ページで実行する式
    const settings = async (label, action, expectedOpen) => {
      if (action.startsWith('key:')) await keys.press(action.slice(4));
      else await evaluate(action);
      // 期待した状態になるまで待つ。ならなければ、時間切れの時点の状態で判定する（NGとして表示される）
      await waitFor(async () => (await evaluate("!document.getElementById('settings').hidden")) === expectedOpen,
        { timeout: 3000, label }).catch(() => {});
      const open = await evaluate("!document.getElementById('settings').hidden");
      if (open !== expectedOpen) failures += 1;
      console.log(`${open === expectedOpen ? 'OK  ' : 'NG  '} ${label}`);
    };
    const click = (id) => `document.getElementById('${id}').click()`;
    await settings('Ctrl+, で設定画面が開く', 'key:Ctrl+,', true);
    await settings('Esc で閉じる', 'key:Esc', false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('「戻る」で閉じる', click('settings-close'), false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('歯車で閉じる', click('settings-button'), false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('F5（再読み込み）で閉じる', 'key:F5', false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('「開く」で閉じる', click('open'), false);
    // 「開く」で出たダイアログは、ネイティブのため、キーを送れない。下のtaskkillで、Viewerごと閉じる
  } finally {
    keys?.close();
    proc.kill();
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
