'use strict';
// サイドバーのファイルツリー（#339）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-tree.js
//   （Windowsでは、パスは、`C:/…`の形で渡す。Git Bashの`/c/…`だと、ワーカーが起動しない）
//
// 確認すること:
//   - フォルダを開いていないとき（単一のファイルを開いただけ）は、ツリーが出ず、案内だけが出る
//   - ルートを決めると、直下だけが出る（フォルダが先・名前順。開けないファイル・隠すフォルダは出ない）
//   - フォルダを開く（クリック）まで、その中は、読まない。開くと、その直下だけが出る
//   - ファイルをクリックすると、開き、今開いているファイルが、ハイライトされる
//   - 矢印キー・Enterで操作できる
//   - ツリーの外のファイルを開いても、ツリーは残り、ハイライトは、どれにも付かない
//   - ルートの外のフォルダは、画面から頼んでも、一覧できない

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

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

/** 条件が満たされるまで、待つ。満たされなければ、最後の値を返す。 */
async function waitFor(read, predicate, timeoutMs = 8000) {
  const start = performance.now();
  let last;
  while (performance.now() - start < timeoutMs) {
    try { last = await read(); } catch { last = undefined; }   // 画面が、まだ準備できていないときの例外は、待ち直す
    if (predicate(last)) return last;
    await sleep(50);
  }
  return last;
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-tree-'));
  const root = path.join(dir, 'docs');
  for (const folder of ['sub/deep', '.git', 'node_modules']) fs.mkdirSync(path.join(root, folder), { recursive: true });
  const write = (relative, text = '') => fs.writeFileSync(path.join(root, relative), text || `# ${relative}\n\n本文です。\n`);
  for (const name of ['01_intro.md', '02_install.md', '10_last.md', 'notes.txt', 'image.png', 'sub/inner.md', 'sub/deep/deep.md', '.git/config.md', 'node_modules/x.md']) write(name);
  const outside = path.join(dir, 'outside.md');
  fs.writeFileSync(outside, '# 外のファイル\n\n本文です。\n');

  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  fs.writeFileSync(path.join(userData, 'settings.json'), JSON.stringify({ sidebarOpen: true }));

  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };
  const start = (file, env = {}) => {
    const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, file], { env: { ...process.env, ...env }, stdio: ['ignore', 'ignore', 'pipe'] });
    proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
    return proc;
  };

  let proc = start(path.join(root, '01_intro.md'));
  try {
    let chrome = await connect(await findTarget(/chrome\.html/));
    const fileName = () => chrome.eval("document.getElementById('file-name').textContent");
    const names = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tree [role=treeitem]')].filter((i) => i.offsetParent !== null).map((i) => i.getAttribute('aria-label')))");
    const item = (label) => `[...document.querySelectorAll('#tree [role=treeitem]')].find((i) => i.getAttribute('aria-label') === ${JSON.stringify(label)})`;
    const click = (label) => chrome.eval(`${item(label)}.querySelector('.tree-row').click()`);
    const current = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tree [aria-current=true]')].map((i) => i.getAttribute('aria-label')))");

    // -- フォルダを開いていない（単一のファイルを開いただけ） ------------------------------------
    await waitFor(fileName, (name) => name === '01_intro.md');
    check('フォルダを開いていないときは、ツリーが出ず、案内だけが出る',
      (await chrome.eval("document.getElementById('tree').hidden")) === true && (await chrome.eval("!document.getElementById('tree-hint').hidden")) === true);
    chrome.close();
    proc.kill();
    await sleep(800);

    // -- ルートを決める --------------------------------------------------------------------
    proc = start(path.join(root, '01_intro.md'), { VIEWER_TREE_ROOT: root });
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === '01_intro.md');
    const top = await waitFor(names, (v) => v !== '[]');
    check('直下だけが出る（フォルダが先、名前順。png・.git・node_modulesは出ない）',
      top === JSON.stringify(['sub', '01_intro.md', '02_install.md', '10_last.md', 'notes.txt']), top);
    check('案内は消え、ルートのフォルダ名が出る',
      (await chrome.eval("document.getElementById('tree-hint').hidden")) === true && (await chrome.eval("document.getElementById('tree-root-name').textContent")) === 'docs');
    check('今開いているファイル（01_intro.md）が、ハイライトされる', (await current()) === JSON.stringify(['01_intro.md']));
    check('フォルダは、開くまで、中を読まない', (await chrome.eval("document.querySelectorAll('#tree li li').length")) === 0);

    // -- フォルダを開く ---------------------------------------------------------------------
    await click('sub');
    const expanded = await waitFor(names, (v) => v.includes('inner.md'));
    check('フォルダを押すと、その直下だけが出る（さらに下は、まだ読まない）',
      expanded === JSON.stringify(['sub', 'deep', 'inner.md', '01_intro.md', '02_install.md', '10_last.md', 'notes.txt']), expanded);
    check('開いたフォルダは、aria-expandedがtrue', (await chrome.eval(`${item('sub')}.getAttribute('aria-expanded')`)) === 'true');
    await click('sub');
    check('もう一度押すと、閉じる', (await waitFor(names, (v) => !v.includes('inner.md'))) === top);
    await click('sub');
    await waitFor(names, (v) => v.includes('inner.md'));

    // -- ファイルを開く ---------------------------------------------------------------------
    await click('inner.md');
    await waitFor(fileName, (name) => name === 'inner.md');
    check('ファイルを押すと、開く', (await fileName()) === 'inner.md');
    check('今開いているファイルだけが、ハイライトされる', (await waitFor(current, (v) => v === JSON.stringify(['inner.md']))) === JSON.stringify(['inner.md']), await current());

    // -- キーボード -------------------------------------------------------------------------
    await chrome.eval(`${item('inner.md')}.focus()`);
    await chrome.eval(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))`);
    check('↓で、次の項目へフォーカスが移る', (await chrome.eval("document.activeElement.getAttribute('aria-label')")) === '01_intro.md');
    await chrome.eval(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))`);
    await waitFor(fileName, (name) => name === '01_intro.md');
    check('Enterで、ファイルが開く', (await fileName()) === '01_intro.md');
    await chrome.eval(`${item('sub')}.focus()`);
    await chrome.eval(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))`);
    check('←で、開いているフォルダが閉じる', (await chrome.eval(`${item('sub')}.getAttribute('aria-expanded')`)) === 'false');
    await chrome.eval(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))`);
    check('→で、閉じているフォルダが開く', (await waitFor(() => chrome.eval(`${item('sub')}.getAttribute('aria-expanded')`), (v) => v === 'true')) === 'true');

    // -- ツリーの外 -------------------------------------------------------------------------
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(outside)}, false)`);
    await waitFor(fileName, (name) => name === 'outside.md');
    check('ツリーの外のファイルを開いても、ツリーは残り、ハイライトは、どれにも付かない',
      (await names()).includes('10_last.md') && (await current()) === '[]');
    const denied = await chrome.eval(`window.viewer.listDirectory(${JSON.stringify(dir)}).then((r) => JSON.stringify(r))`);
    check('ルートの外のフォルダは、一覧できない', JSON.parse(denied).ok === false, denied);
    const inside = await chrome.eval(`window.viewer.listDirectory(${JSON.stringify(path.join(root, 'sub'))}).then((r) => r.ok)`);
    check('ルートの中のフォルダは、一覧できる', inside === true);
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
