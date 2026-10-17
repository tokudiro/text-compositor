'use strict';
// 目次（アウトライン）パネル（#329）を、実際にViewerを起動して確認する。Electronと、Pythonのワーカーが要る（CIでは動かさない）。
//
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-outline.js [--screenshot <png>]
//
// 手元の設定を変えないため、ユーザーデータは、使い捨てにする。
//
// 確認すること:
//   1. 単一のファイルで、サイドバーを開くと、目次が出る（見出しの階層・文字。「#」のリンクの文字は、含まれない）。
//   2. 見出しを押すと、内容が、その見出しの位置へスクロールする。矢印キー・Enterでも、移れる。
//   3. 「ファイル」「目次」のタブで、切り替えられる。
//   4. 見出しのない文書は、「見出しがありません」と出る。
//   5. 原稿を書き換えると（自動更新）、目次も更新される。
//   6. 設定「目次」を「出さない」にすると、タブが消え、ファイルだけになる。メニューの項目も隠れる。

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

const isContent = (url) => url.endsWith('.html') && !url.endsWith('/chrome.html');

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
    key: async (key) => {
      for (const type of ['keyDown', 'keyUp']) await call('Input.dispatchKeyEvent', { type, key, code: key, windowsVirtualKeyCode: { ArrowDown: 40, ArrowUp: 38, Enter: 13, Home: 36, End: 35 }[key] ?? 0 });
    },
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
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-outline-'));
  const md = path.join(root, 'doc.md');
  const filler = (n) => Array.from({ length: n }, (_, i) => `段落${i + 1}。これは、スクロールが必要な長さにするための、本文です。`).join('\n\n');
  const body = ['# 全体の題', filler(30), '## 概要', filler(30), '### 詳細な説明', filler(30), '## まとめ', filler(30), ''].join('\n\n');
  fs.writeFileSync(md, body);
  const plain = path.join(root, 'plain.txt');
  fs.writeFileSync(plain, '見出しのない、ただの文章です。\n');
  const userData = path.join(root, 'user-data');
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { stdio: 'ignore' });

  try {
    const chrome = await connect(await waitTarget((url) => url.endsWith('/chrome.html')));
    const content = async () => connect(await waitTarget(isContent));
    const items = async () => JSON.parse(await chrome.eval("JSON.stringify([...document.querySelectorAll('#outline [role=treeitem]')].map((i) => [i.getAttribute('aria-label'), i.getAttribute('aria-level')]))") ?? '[]');
    const scrollOf = async () => { const view = await content(); const y = await view.eval('window.scrollY'); view.close(); return y; };
    await waitFor(async () => /更新/.test(await chrome.eval("document.getElementById('status').textContent")));

    // 1. 目次
    check('起動した直後は、サイドバーが閉じている', (await chrome.eval("document.getElementById('sidebar').hidden")) === true);
    await chrome.eval('window.viewer.toggleSidebar()');
    check('サイドバーを開くと、単一のファイルでは、目次が出る', await waitFor(async () => (await items()).length === 4), JSON.stringify(await items()));
    check('見出しの文字と階層が、そのまま出る（「#」のリンクの文字は、含まれない）',
      JSON.stringify(await items()) === JSON.stringify([['全体の題', '1'], ['概要', '2'], ['詳細な説明', '3'], ['まとめ', '2']]), JSON.stringify(await items()));
    const tabs = JSON.parse(await chrome.eval("JSON.stringify({ visible: !document.getElementById('sidebar-tabs').hidden, outline: document.getElementById('sidebar-tab-outline').getAttribute('aria-selected'), files: document.getElementById('sidebar-tab-files').getAttribute('aria-selected'), outlineTab: document.getElementById('sidebar-tab-outline').tabIndex, filesTab: document.getElementById('sidebar-tab-files').tabIndex })"));
    check('「ファイル」「目次」のタブが出て、目次が選ばれている（Tabストップは、選ばれたタブ1つ）',
      tabs.visible && tabs.outline === 'true' && tabs.files === 'false' && tabs.outlineTab === 0 && tabs.filesTab === -1, JSON.stringify(tabs));
    const stops = await chrome.eval("[...document.querySelectorAll('#outline [role=treeitem]')].filter((i) => i.tabIndex === 0).length");
    check('目次の項目の、Tabストップは、1つ', stops === 1, String(stops));
    if (screenshotPath) { await chrome.screenshot(screenshotPath); console.log(`     画面を保存した: ${screenshotPath}`); }

    // 2. ジャンプ
    check('最初は、先頭にいる', (await scrollOf()) === 0);
    await chrome.eval("[...document.querySelectorAll('#outline [role=treeitem]')].find((i) => i.getAttribute('aria-label') === '詳細な説明').click()");
    const jumped = await waitFor(async () => (await scrollOf()) > 500);
    const view = await content();
    const top = await view.eval("Math.round(document.querySelector('h3').getBoundingClientRect().top) + 0");
    view.close();
    check('見出しを押すと、その見出しの位置へ、スクロールする', jumped && Math.abs(top) <= 4, `scrollY=${await scrollOf()} top=${top}`);
    await chrome.eval("document.querySelector('#outline [role=treeitem]').focus()");
    await chrome.key('End');
    const lastFocused = await chrome.eval("document.activeElement?.getAttribute('aria-label')");
    check('Endキーで、最後の項目へ移る', lastFocused === 'まとめ', String(lastFocused));
    await chrome.key('Enter');
    // Math.round(-0.4)は-0になり、CDPの値として返らない（undefined）ため、+ 0で0にする
    const h2Top = async () => { const v = await content(); const t = await v.eval("Math.round(document.querySelectorAll('main h2')[1].getBoundingClientRect().top) + 0"); v.close(); return t; };
    check('Enterで、その見出しへ移る', await waitFor(async () => Math.abs(await h2Top()) <= 4), `top=${await h2Top()}`);

    // 3. タブ
    await chrome.eval("document.getElementById('sidebar-tab-files').click()");
    await waitFor(async () => (await chrome.eval("document.getElementById('outline-panel').hidden")) === true);
    check('「ファイル」のタブを押すと、目次が隠れて、ファイルの案内が出る',
      (await chrome.eval("document.getElementById('outline-panel').hidden")) === true && (await chrome.eval("document.getElementById('sidebar-files').hidden")) === false);
    await chrome.eval("document.getElementById('sidebar-tab-outline').click()");
    check('「目次」のタブで、戻る', await waitFor(async () => (await items()).length === 4));

    // 5. 自動更新
    fs.appendFileSync(md, '\n\n## 追加した見出し\n\n本文。\n');
    check('原稿を保存すると、目次が、更新される', await waitFor(async () => (await items()).length === 5 && (await items())[4][0] === '追加した見出し'), JSON.stringify(await items()));

    // 4. 見出しのない文書
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(plain)})`);
    check('見出しのない文書は、「見出しがありません」と出る',
      await waitFor(async () => (await chrome.eval("document.getElementById('outline-hint').hidden")) === false && (await items()).length === 0));

    // 6. 設定「目次」を出さない
    await chrome.eval("window.viewer.setSetting('showOutline', false)");
    const off = await waitFor(async () => (await chrome.eval("document.getElementById('sidebar-tabs').hidden")) === true);
    check('設定「目次」を「出さない」にすると、タブが消え、ファイルだけになる',
      off && (await chrome.eval("document.getElementById('outline-panel').hidden")) === true && (await chrome.eval("document.getElementById('sidebar-files').hidden")) === false);
    await chrome.eval("window.viewer.setSetting('showOutline', true)");
    check('「出す」に戻すと、タブが、また出る', await waitFor(async () => (await chrome.eval("document.getElementById('sidebar-tabs').hidden")) === false));

    // ファイルツリーだけを「出さない」にしても、目次が使えるので、サイドバーは使える（タブは、出ない）
    await chrome.eval("window.viewer.setSetting('showFileTree', false)");
    await chrome.eval('window.viewer.openPath(' + JSON.stringify(md) + ')');
    await waitFor(async () => (await items()).length === 5);
    const onlyOutline = JSON.parse(await chrome.eval("JSON.stringify({ sidebarHidden: document.getElementById('sidebar').hidden, button: !document.getElementById('sidebar-button').hidden, tabsHidden: document.getElementById('sidebar-tabs').hidden, outlineShown: !document.getElementById('outline-panel').hidden, filesHidden: document.getElementById('sidebar-files').hidden })"));
    check('ファイルツリーだけを「出さない」にすると、タブなしで、目次だけが出る（サイドバーのボタンも残る）',
      onlyOutline.sidebarHidden === false && onlyOutline.button && onlyOutline.tabsHidden && onlyOutline.outlineShown && onlyOutline.filesHidden, JSON.stringify(onlyOutline));
    // 目次も「出さない」にすると、サイドバーが使えなくなる
    await chrome.eval("window.viewer.setSetting('showOutline', false)");
    check('目次も「出さない」にすると、サイドバーもボタンも出ない',
      await waitFor(async () => (await chrome.eval("document.getElementById('sidebar').hidden")) === true && (await chrome.eval("document.getElementById('sidebar-button').hidden")) === true));
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
