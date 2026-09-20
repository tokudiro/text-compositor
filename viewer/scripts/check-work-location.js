'use strict';
// 変換ファイルの置き場所（#258）を、実際にViewerを起動して確認する。Electronと、Pythonのワーカーが要る（CIでは動かさない）。
//
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-work-location.js [--screenshot <png>]
//
// 手元の設定・キャッシュを変えないため、ユーザーデータと、アプリの領域（Windowsでは、LOCALAPPDATA）は、使い捨てにする。
//
// 確認すること:
//   1. 既定では、原稿のフォルダに、何も作られない（.text-compositor/が無い）。
//   2. HTMLと図のSVGは、アプリの領域に作られ、画像（図のSVGと、原稿の隣の画像）が読み込まれる。
//   3. 設定画面に、キャッシュの使用量と、削除のボタンが出る。「ファイルを作らない」は、選べない。
//   4. 削除すると、アプリの領域が空になり、表示中の文書は、変換し直され、原稿のフォルダには、まだ何も作られない。
//   5. 設定を「原稿の隣」にすると、原稿の隣に.text-compositor/が作られ、そこから表示される。

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

/** 文書のビューのURL。変換したHTMLは、アプリの領域の`html/<ハッシュ>.html`か、`preview.html`。ツールバーの`chrome.html`は除く。 */
const isContent = (url) => url.endsWith('.html') && !url.endsWith('/chrome.html');

async function targetUrl(match) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`).catch(() => ({ json: async () => [] }))).json();
  return targets.find((t) => match(t.url));
}

async function waitTarget(match, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const found = await targetUrl(match);
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

const listing = (directory) => (fs.existsSync(directory) ? fs.readdirSync(directory).sort() : null);

async function waitFor(predicate, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await predicate()) return true;
    await sleep(100);
  }
  return false;
}

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-work-'));
  const docs = path.join(root, 'docs');
  const local = path.join(root, 'local');   // LOCALAPPDATA の代わり。アプリの領域は、この下の text-compositor/Cache/viewer/
  fs.mkdirSync(docs, { recursive: true });
  fs.mkdirSync(local, { recursive: true });
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20"><rect width="40" height="20" fill="#3572b0"/></svg>';
  // 1x1の、赤いPNG
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==', 'base64');
  const md = path.join(docs, 'doc.md');
  fs.writeFileSync(md, `# 置き場所の確認\n\n本文。\n\n\`\`\`svg\n${svg}\n\`\`\`\n\n![pic](pic.png)\n`);
  fs.writeFileSync(path.join(docs, 'pic.png'), png);

  const appRoot = path.join(local, 'text-compositor', 'Cache', 'viewer');
  const userData = path.join(root, 'user-data');
  const env = { ...process.env, LOCALAPPDATA: local, XDG_CACHE_HOME: local };
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { env, stdio: 'ignore' });

  try {
    const chrome = await connect(await waitTarget((url) => url.endsWith('/chrome.html')));
    const contentTarget = await waitTarget(isContent);
    const content = await connect(contentTarget);
    const images = () => content.eval("JSON.stringify([...document.querySelectorAll('img')].map((i) => i.complete && i.naturalWidth > 0))");
    await waitFor(async () => /更新/.test(await chrome.eval("document.getElementById('status').textContent")));

    // 1・2. 既定（アプリの領域）
    check('既定では、原稿のフォルダに、何も作られない', JSON.stringify(listing(docs)) === JSON.stringify(['doc.md', 'pic.png']), JSON.stringify(listing(docs)));
    const html = listing(path.join(appRoot, 'html')) ?? [];
    const cache = listing(path.join(appRoot, 'cache')) ?? [];
    check('HTMLが、アプリの領域の html/ に作られる', html.length === 1 && /^[0-9a-f]{16}\.html$/.test(html[0]), html.join(','));
    check('図のSVGが、アプリの領域の cache/ に作られる', cache.some((name) => /^svg_.*\.svg$/.test(name)), cache.join(','));
    check('文書のビューは、アプリの領域のHTMLを表示している', contentTarget.url.includes('/viewer/html/'), contentTarget.url);
    check('図のSVGと、原稿の隣の画像が、どちらも読み込まれている（別のフォルダからの読み込み）', (await images()) === '[true,true]', await images());

    // 3. 設定画面
    await chrome.eval('window.viewer.toggleSettings()');
    await waitFor(async () => (await chrome.eval("document.getElementById('cache-size').textContent")) !== '');
    const settings = JSON.parse(await chrome.eval("JSON.stringify({ size: document.getElementById('cache-size').textContent, clearDisabled: document.getElementById('clear-cache').disabled, "
      + "app: document.querySelector('input[name=workLocation][value=app]').checked, beside: document.querySelector('input[name=workLocation][value=beside]').checked, "
      + "noneDisabled: document.querySelector('input[name=workLocation][value=none]').disabled })"));
    check('設定画面に、キャッシュの使用量が出て、削除のボタンが押せる', /^\d+(\.\d)? (KB|MB)$/.test(settings.size) && !settings.clearDisabled, JSON.stringify(settings));
    check('保存場所は、「アプリの領域」が選ばれている', settings.app && !settings.beside);
    check('「ファイルを作らない」は、選べない（未対応）', settings.noneDisabled);
    if (screenshotPath) { await chrome.screenshot(screenshotPath); console.log(`     画面を保存した: ${screenshotPath}`); }

    // 4. 削除
    fs.writeFileSync(path.join(appRoot, 'cache', 'stale.svg'), 'x');   // 削除の対象か、確かめるための、余計なファイル
    await chrome.eval("document.getElementById('clear-cache').click()");
    check('削除すると、古いキャッシュのファイルが消える（表示中の文書は、変換し直され、新しく作られる）',
      await waitFor(() => !fs.existsSync(path.join(appRoot, 'cache', 'stale.svg')) && (listing(path.join(appRoot, 'html')) ?? []).length === 1));
    await waitFor(async () => (await images()) === '[true,true]');
    check('削除の後も、図と画像が表示される', (await images()) === '[true,true]', await images());
    check('削除しても、原稿のフォルダには、何も作られない', JSON.stringify(listing(docs)) === JSON.stringify(['doc.md', 'pic.png']), JSON.stringify(listing(docs)));

    // 5. 「原稿の隣」
    await chrome.eval("document.querySelector('input[name=workLocation][value=beside]').click()");
    await sleep(300);
    await chrome.eval('window.viewer.reload()');
    const beside = await waitFor(() => fs.existsSync(path.join(docs, '.text-compositor', 'preview.html')));
    check('「原稿の隣」にすると、原稿の隣の .text-compositor/ に作られる', beside, JSON.stringify(listing(path.join(docs, '.text-compositor'))));
    const saved = JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8'));
    check('設定は、settings.json に保存される', saved.workLocation === 'beside', String(saved.workLocation));
    const besideTarget = await waitFor(async () => Boolean(await targetUrl((url) => url.endsWith('/.text-compositor/preview.html'))));
    check('文書のビューは、原稿の隣の preview.html を表示している', besideTarget);
    content.close();
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
