'use strict';
// 設定画面の開閉を、実際のキー操作で確認する（手動。Windowsのみ。#200）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-window.js
//
// 確認すること:
//   - 設定画面は、Ctrl+,・歯車・「戻る」・Esc で閉じられ、ファイルを開く・再読み込みでも閉じる。
// キーは、SendKeysで、前面のウィンドウへ送る。実行中は、ほかのウィンドウを操作しないこと。

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます（キー操作に、SendKeysを使うため）。');
  process.exit(0);
}

const viewerDir = path.resolve(__dirname, '..');
const electron = require('electron');
const sample = path.join(viewerDir, '..', 'benchmarks', 'html-view', 'fixture', 'fixture.md');
const port = 9400 + Math.floor(Math.random() * 100);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function sendKeys(keys) {
  const script = 'Add-Type -AssemblyName System.Windows.Forms; '
    + '(New-Object -ComObject WScript.Shell).AppActivate((Get-Process electron | ? MainWindowTitle | select -First 1).Id) | Out-Null; '
    + `Start-Sleep -Milliseconds 400; [Windows.Forms.SendKeys]::SendWait("${keys}")`;
  execFileSync('powershell', ['-NoProfile', '-Command', script]);
}

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
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, sample],
    { env: { ...process.env }, stdio: 'ignore' });
  let failures = 0;
  try {
    await sleep(6500);
    const evaluate = await connect();
    const wait = 1000;
    const settings = async (label, action, expectedOpen) => {
      if (action.startsWith('{') || action.startsWith('^')) sendKeys(action);
      else await evaluate(action);
      await sleep(wait);
      const open = await evaluate("!document.getElementById('settings').hidden");
      if (open !== expectedOpen) failures += 1;
      console.log(`${open === expectedOpen ? 'OK  ' : 'NG  '} ${label}`);
    };
    const click = (id) => `document.getElementById('${id}').click()`;
    await settings('Ctrl+, で設定画面が開く', '^,', true);
    await settings('Esc で閉じる', '{ESC}', false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('「戻る」で閉じる', click('settings-close'), false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('歯車で閉じる', click('settings-button'), false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('F5（再読み込み）で閉じる', '{F5}', false);
    await settings('歯車で開く', click('settings-button'), true);
    await settings('「開く」で閉じる', click('open'), false);
    sendKeys('{ESC}');   // 「開く」で出たダイアログを閉じる
  } finally {
    proc.kill();
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
