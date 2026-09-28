'use strict';
// 文書内検索（#325）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-search.js
//
// 確認すること:
//   - 通常の文字列検索: 件数・現在位置の表示、次候補・前候補への移動、ハイライト（<mark>）
//   - 正規表現モード: 通常検索と違う件数になること、不正な正規表現でエラーが出ること
//   - 大文字・小文字の区別トグル
//   - Ctrl+F（実際のキー操作）で開き、Escで閉じてハイライトが消えること（Windowsのみ、SendKeysを使うため）

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9700 + Math.floor(Math.random() * 200);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targets() {
  return (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []));
}

async function findTarget(pattern) {
  for (let i = 0; i < 80; i++) {
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
  return {
    async eval(expression) {
      const n = ++id;
      const reply = await new Promise((resolve) => { waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } })); });
      if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
      return reply.result?.result?.value;
    },
    close: () => ws.close(),
  };
}

function sendKeys(keys) {
  const script = 'Add-Type -AssemblyName System.Windows.Forms; '
    + '(New-Object -ComObject WScript.Shell).AppActivate((Get-Process electron | ? MainWindowTitle | select -First 1).Id) | Out-Null; '
    + `Start-Sleep -Milliseconds 400; [Windows.Forms.SendKeys]::SendWait("${keys}")`;
  execFileSync('powershell', ['-NoProfile', '-Command', script]);
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-search-'));
  const md = path.join(dir, 'doc.md');
  // 「文図」を本文に6回（うち大文字・小文字が意味を持つよう、見出しに"Obunzu"も）、日付らしき文字列を2回入れる
  fs.writeFileSync(md, [
    '# Obunzu 検索の確認',
    '',
    '文図は、文書と図を表す造語です。文図、文図、文図と、くり返します。',
    '',
    '日付の例: 2026-01-01、および 2026-12-31。',
    '',
    'obunzu（小文字）も、1回だけ入れておきます。',
  ].join('\n'));

  const userData = path.join(dir, 'user-data');
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { env: process.env, stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  try {
    const content = await connect(await findTarget(/(?<!chrome)\.html$/));
    const chrome = await connect(await findTarget(/chrome\.html/));
    for (let i = 0; i < 100; i++) {
      if (await content.eval("document.querySelector('h1')?.textContent ?? ''")) break;
      await sleep(100);
    }

    const setValue = async (id, value) => chrome.eval(`(() => { const el = document.getElementById('${id}'); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    const click = async (id) => chrome.eval(`document.getElementById('${id}').click()`);
    const text = async (id) => chrome.eval(`document.getElementById('${id}').textContent`);
    const waitCount = async (predicate, timeoutMs = 4000) => {
      const start = performance.now();
      let last;
      while (performance.now() - start < timeoutMs) {
        last = await text('search-count');
        if (predicate(last)) return last;
        await sleep(30);
      }
      return last;
    };
    const markCount = async () => content.eval("document.querySelectorAll('mark.tc-search-mark').length");
    const currentMarkText = async () => content.eval("document.querySelector('mark.tc-search-current')?.textContent ?? null");

    // -- 通常の文字列検索 --------------------------------------------------------
    await click('search-button');
    check('検索ボタンで、検索欄が開く', (await chrome.eval("document.getElementById('search').hidden")) === false);

    await setValue('search-input', '文図');
    const count1 = await waitCount((s) => s.includes('/'));
    check('件数が表示される（"文図"は4回）', count1 === '1 / 4', count1);
    check('内容のビューに、一致した数だけ<mark>が入る', (await markCount()) === 4, `marks=${await markCount()}`);

    await click('search-next');
    await sleep(100);
    check('次候補への移動', (await text('search-count')) === '2 / 4');
    await click('search-prev');
    await sleep(100);
    check('前候補への移動', (await text('search-count')) === '1 / 4');

    // -- 大文字・小文字の区別 -----------------------------------------------------
    await setValue('search-input', 'obunzu');
    const countCi = await waitCount((s) => s === '1 / 2');
    check('大文字・小文字を区別しない既定では2件（Obunzu, obunzu）', countCi === '1 / 2', countCi);
    await click('search-case');
    const countCs = await waitCount((s) => s === '1 / 1');
    check('大文字・小文字を区別すると1件（obunzu）になる', countCs === '1 / 1', countCs);
    await click('search-case');   // 元に戻す

    // -- 正規表現モード -----------------------------------------------------------
    await setValue('search-input', '\\d{4}-\\d{2}-\\d{2}');
    const plainNoMatch = await waitCount((s) => s === '見つかりません');
    check('正規表現を使わないと、記号がそのまま扱われ、一致しない', plainNoMatch === '見つかりません', plainNoMatch);

    await click('search-regex');
    const regexCount = await waitCount((s) => s.includes('/'));
    check('正規表現を有効にすると、日付が2件見つかる', regexCount === '1 / 2', regexCount);

    await setValue('search-input', '[');
    const invalid = await waitCount((s) => s.includes('不正'));
    check('不正な正規表現は、エラー表示になる（検索は実行しない）', invalid.includes('不正'), invalid);
    await click('search-regex');   // 元に戻す

    // -- Escで閉じる（マウス操作） -------------------------------------------------
    await setValue('search-input', '文図');
    await waitCount((s) => s.includes('/'));
    await close_via_escape_button();
    async function close_via_escape_button() { await click('search-close'); }
    await sleep(150);
    check('閉じるボタンで、検索欄が閉じる', (await chrome.eval("document.getElementById('search').hidden")) === true);
    check('閉じると、内容のビューのハイライトも消える', (await markCount()) === 0, `marks=${await markCount()}`);

    // -- Ctrl+F・Esc（実際のキー操作。Windowsのみ） --------------------------------
    if (process.platform === 'win32') {
      sendKeys('^f');
      await sleep(300);
      check('Ctrl+Fで、検索欄が開き、フォーカスが当たる', (await chrome.eval("document.getElementById('search').hidden")) === false
        && (await chrome.eval("document.activeElement?.id")) === 'search-input');
      sendKeys('{ESC}');
      await sleep(300);
      check('文書側にフォーカスがあっても、Escで検索欄が閉じる', (await chrome.eval("document.getElementById('search').hidden")) === true);
    } else {
      console.log('     Ctrl+F・Escの実キー操作は、Windowsのみ確認します（SendKeysのため）。スキップしました。');
    }

    content.close();
    chrome.close();
  } catch (error) {
    console.error('FAILED', error);
    results.push(false);
  } finally {
    proc.kill();
    if (process.platform === 'win32') spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(results.every(Boolean) ? '\nすべて成功' : '\n失敗あり');
  process.exit(results.every(Boolean) ? 0 : 1);
})();
