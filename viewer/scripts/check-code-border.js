'use strict';
// コードブロックの枠線（#511）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-code-border.js
//
// 確認すること:
//   - 既定は、枠線なし（`<pre>`の枠の太さが0）で、背景（薄いグレー）は付いている
//   - 設定`showCodeBorder`をオンにすると、`<pre>`に、1pxの枠線（色は、文書のCSSの罫線の色`--line`）が付く
//   - 文書を更新（自動更新）しても、枠線が保たれる
//   - オフに戻すと、枠線が消える
//   - 設定が、設定ファイルに保存される
// 起動したViewerだけを、終了する（`Get-Process electron`で、すべてのElectronを終了しない。ClaudeもElectronのため）。

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

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

const BORDER = "(() => { const s = getComputedStyle(document.querySelector('pre')); return { width: s.borderTopWidth, style: s.borderTopStyle, color: s.borderTopColor, bg: s.backgroundColor, line: getComputedStyle(document.documentElement).getPropertyValue('--line').trim() }; })()";

async function waitFor(content, expression, timeout = 6000) {
  for (let waited = 0; waited < timeout; waited += 100) {
    if (await content.eval(expression)) return true;
    await sleep(100);
  }
  return false;
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-code-border-'));
  const file = path.join(dir, 'sample.md');
  const write = (text) => fs.writeFileSync(file, `# サンプル\n\n${text}\n\n\`\`\`python\nprint("hello")\n\`\`\`\n`, 'utf8');
  write('本文。');
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-code-border-ud-'));
  const proc = spawn(electron, [viewerDir, `--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, file], {
    env: { ...process.env, TEXT_COMPOSITOR_PYTHONPATH: process.env.TEXT_COMPOSITOR_PYTHONPATH || repoDir }, stdio: 'ignore',
  });
  try {
    const content = await connect(await findTarget((url) => url.endsWith('.html') && !url.endsWith('/chrome.html')));
    const chrome = await connect(await findTarget((url) => url.endsWith('/chrome.html')));
    check('文書が表示される（<pre>がある）', await waitFor(content, "document.querySelectorAll('pre').length === 1", 20000));
    await sleep(500);   // content-featuresが届くまで

    const before = await content.eval(BORDER);
    check('既定は、枠線なし（太さ0）', before.width === '0px', JSON.stringify(before));
    check('背景は、いつも付いている（薄いグレー）', before.bg !== 'rgba(0, 0, 0, 0)', before.bg);

    // 設定画面の「表示する機能」に、行がある（FEATURESから作られる）。既定は「付けない」が選ばれている
    await chrome.eval('api.toggleSettings()');
    check('設定画面に、「コードブロックの枠線」の行がある',
      await waitFor(chrome, "document.querySelectorAll('#settings input[name=\"showCodeBorder\"]').length === 2")
      && await chrome.eval("document.getElementById('feature-showCodeBorder-name')?.textContent === 'コードブロックの枠線'"));
    check('既定は、「付けない」が選ばれている', await chrome.eval("document.querySelector('#settings input[name=\"showCodeBorder\"][value=\"false\"]').checked === true"));
    const labels = await chrome.eval("[...document.querySelectorAll('#settings input[name=\"showCodeBorder\"]')].map((i) => i.parentElement.textContent.trim())");
    check('選択肢の文字は、「付ける」「付けない」', JSON.stringify(labels.sort()) === JSON.stringify(['付ける', '付けない'].sort()), JSON.stringify(labels));

    await chrome.eval("document.querySelector('#settings input[name=\"showCodeBorder\"][value=\"true\"]').click()");
    check('オンにすると、1pxの枠線が付く', await waitFor(content, "getComputedStyle(document.querySelector('pre')).borderTopWidth === '1px'"));
    const on = await content.eval(BORDER);
    check('枠線の線種は、実線', on.style === 'solid', JSON.stringify(on));
    check('枠線の色は、文書のCSSの罫線の色（--line）', on.line !== '' && on.color.replace(/\s/g, '') === await content.eval(`(() => { const e = document.createElement('i'); e.style.color = '${on.line}'; document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c.replace(/\\s/g, ''); })()`), JSON.stringify(on));

    // 自動更新（ファイルを書き換える）。表示し直しても、枠線が保たれる
    write('本文（更新）。');
    check('文書が更新される', await waitFor(content, "document.body.innerText.includes('更新')", 15000));
    await sleep(500);
    const after = await content.eval(BORDER);
    check('更新しても、枠線が保たれる', after.width === '1px', JSON.stringify(after));

    const saved = JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8'));
    check('設定が、設定ファイルに保存される', saved.showCodeBorder === true, `saved=${saved.showCodeBorder}`);

    await chrome.eval("document.querySelector('#settings input[name=\"showCodeBorder\"][value=\"false\"]').click()");
    check('オフに戻すと、枠線が消える', await waitFor(content, "getComputedStyle(document.querySelector('pre')).borderTopWidth === '0px'"));

    content.close();
    chrome.close();
  } finally {
    // 起動したViewerだけを終了する（プロセスの木ごと）。ほかのElectron（Claude本体など）は、終了しない
    try { execFileSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* すでに終了している */ }
  }
  console.log(failures ? `\n${failures} 件、NG` : '\nすべて、OK');
  process.exit(failures ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
