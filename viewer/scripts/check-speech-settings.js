'use strict';
// 読み上げの設定（#430）を、実際にViewerを起動して確認する（手動。Windowsのみ。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-speech-settings.js
//   （Windowsでは、パスは、`C:/…`の形で渡す）
//
// 確認すること:
//   - 設定画面に、読み上げの声と速さの行が出る。声の選択肢は、OSの日本語の声（実行時に取得したもの）
//   - 声と速さを選ぶと、設定ファイル（settings.json）に保存される
//   - OSに無い声が保存されていても、設定画面は壊れず、「自動」が選ばれて見える

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます（読み上げが、Windowsだけのため）。');
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
    async eval(expression) {
      const reply = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
      return reply.result?.result?.value;
    },
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

async function run(settings, steps) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-speech-'));
  const doc = path.join(dir, 'a.md');
  fs.writeFileSync(doc, '# 見出し\n\n本文です。\n');
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  if (settings) fs.writeFileSync(path.join(userData, 'settings.json'), JSON.stringify(settings));
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, doc], { env: process.env, stdio: ['ignore', 'ignore', 'pipe'] });
  try {
    const chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(() => chrome.eval("document.getElementById('file-name').textContent"), (name) => name === 'a.md');
    await chrome.eval("document.getElementById('settings-button').click()");
    // 声の一覧は、起動時に、裏で取得する。選択肢が入るまで待つ
    await waitFor(() => chrome.eval("document.getElementById('speech-voice').options.length"), (n) => n > 1);
    await steps(chrome, () => JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8')));
  } finally {
    proc.kill();
    await sleep(300);
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

(async () => {
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };
  try {
    await run(null, async (chrome, saved) => {
      const rows = await chrome.eval("[!document.getElementById('speech-voice-row').hidden, !document.getElementById('speech-rate-row').hidden]");
      check('読み上げの声と速さの行が、設定画面に出る', rows[0] && rows[1], JSON.stringify(rows));
      const options = await chrome.eval("[...document.getElementById('speech-voice').options].map((o) => o.value)");
      check('声の選択肢は、「自動」と、OSの日本語の声', options[0] === '' && options.length > 1, JSON.stringify(options));
      const testButton = await chrome.eval("document.getElementById('speech-test')?.textContent");
      check('「試し聞き」のボタンがあり、押しても、エラーにならない', testButton === '試し聞き' && (await chrome.eval("document.getElementById('speech-test').click(), true")) === true);
      const voice = options[options.length - 1];
      await chrome.eval(`(() => { const s = document.getElementById('speech-voice'); s.value = ${JSON.stringify(voice)}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
      await chrome.eval("document.querySelector('input[name=speechRate][value=fast]').click()");
      const file = await waitFor(() => saved(), (s) => s.speechVoice === voice && s.speechRate === 'fast');
      check('声と速さを選ぶと、settings.jsonに保存される', file.speechVoice === voice && file.speechRate === 'fast', JSON.stringify([file.speechVoice, file.speechRate]));
    });
    await run({ speechVoice: 'Microsoft Nobody', speechRate: 'slow' }, async (chrome) => {
      const shown = await chrome.eval("[document.getElementById('speech-voice').value, document.querySelector('input[name=speechRate]:checked')?.value]");
      check('OSに無い声が保存されていても、「自動」が選ばれて見える（速さは、保存どおり）', shown[0] === '' && shown[1] === 'slow', JSON.stringify(shown));
    });
  } catch (error) {
    console.log(`NG   確認を最後まで実行できた  ${error.message}`);
    results.push(false);
  }
  const failed = results.filter((ok) => !ok).length;
  console.log(failed ? `\n失敗: ${failed}件` : '\nすべて成功');
  process.exit(failed ? 1 : 0);
})();
