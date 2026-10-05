'use strict';
// サイドバー（#339）の開閉を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-sidebar.js
//
// 確認すること:
//   - 既定では、サイドバーが出ず、内容のビューが、ウィンドウの全幅を使う
//   - 開くと、サイドバーが出て、内容のビューが、その幅の分だけ、右へ寄る（狭くなる）
//   - 閉じると、元の幅に戻る
//   - 設定画面を開いている間は、サイドバーが隠れ、閉じると戻る
//   - 開閉は、覚えない（#373）。再起動すると、閉じている（単一ファイルモード）
//   - モード（#373）: ルートを決めて起動すると、開く。ルートの中のファイルを開いても、モードを保つ。外のファイルを開くと、
//     単一ファイルモードへ戻り、閉じる

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-sidebar-'));
  const doc = path.join(dir, 'a.md');
  fs.writeFileSync(doc, '# 文書A\n\n本文です。\n');
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });

  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };
  const start = (env = {}) => {
    const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, doc], { env: { ...process.env, ...env }, stdio: ['ignore', 'ignore', 'pipe'] });
    proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
    return proc;
  };
  const savedOpen = () => { try { return JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8')).sidebarOpen; } catch { return undefined; } };

  let proc = start();
  try {
    let chrome = await connect(await findTarget(/chrome\.html/));
    const contentTarget = async () => (await targets()).find((t) => t.type === 'page' && /\.html$/.test(t.url) && !/chrome\.html/.test(t.url));
    /** 内容のビューの横幅（CSSピクセル）。ズームは100%のため、ウィンドウ本体の幅との差が、サイドバーの幅になる。 */
    const contentWidth = async () => {
      const target = await contentTarget();
      if (!target) return undefined;
      const connection = await connect(target);
      try { return await connection.eval('window.innerWidth'); } finally { connection.close(); }
    };
    const chromeWidth = () => chrome.eval('window.innerWidth');
    const sidebarVisible = () => chrome.eval("!document.getElementById('sidebar').hidden");
    const pressed = () => chrome.eval("document.getElementById('sidebar-button').getAttribute('aria-pressed')");
    const fileName = () => chrome.eval("document.getElementById('file-name').textContent");

    await waitFor(fileName, (name) => name === 'a.md');
    await waitFor(contentWidth, (w) => typeof w === 'number' && w > 0);
    const full = await chromeWidth();
    check('既定では、サイドバーが出ず、内容のビューが、全幅を使う',
      (await sidebarVisible()) === false && (await pressed()) === 'false' && (await contentWidth()) === full, `内容 ${await contentWidth()} / 全体 ${full}`);

    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === true);
    await waitFor(contentWidth, (w) => w === full - 240);
    check('開くと、サイドバーが出て、ボタンが押された状態になる', (await sidebarVisible()) === true && (await pressed()) === 'true');
    check('内容のビューが、サイドバーの幅（240）だけ狭くなる', (await contentWidth()) === full - 240, `内容 ${await contentWidth()} / 全体 ${full}`);
    await sleep(500);
    check('開閉は、設定として保存されない（#373）', savedOpen() === undefined, JSON.stringify(savedOpen()));

    await chrome.eval('window.viewer.toggleSettings()');
    await waitFor(sidebarVisible, (v) => v === false);
    check('設定画面を開いている間は、サイドバーが隠れる', (await sidebarVisible()) === false);
    await chrome.eval('window.viewer.toggleSettings()');
    await waitFor(sidebarVisible, (v) => v === true);
    await waitFor(contentWidth, (w) => w === full - 240);
    check('設定画面を閉じると、サイドバーと内容の幅が、戻る', (await sidebarVisible()) === true && (await contentWidth()) === full - 240);

    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === false);
    await waitFor(contentWidth, (w) => w === full);
    check('閉じると、元の幅に戻る', (await sidebarVisible()) === false && (await contentWidth()) === full);

    // -- 開いたまま終了しても、再起動すると、閉じている（覚えない。単一ファイルモード） ----------
    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === true);
    chrome.close();
    proc.kill();
    await sleep(800);
    proc = start();
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === 'a.md');
    await sleep(500);
    check('再起動すると、サイドバーは、閉じている（開閉を覚えない）', (await sidebarVisible()) === false);
    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === true);
    check('単一ファイルモードでも、Ctrl+B（切り替え）で、案内つきの空のサイドバーを開ける',
      (await sidebarVisible()) === true && (await chrome.eval("!document.getElementById('tree-hint').hidden")) === true);

    // -- モード（#373）。ルートを決めて起動すると、サイドバーは、開いている ------------------------
    chrome.close();
    proc.kill();
    await sleep(800);
    const other = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-sidebar-outside-'));   // ルート（dir）の外（子フォルダではない）
    const outside = path.join(other, 'c.md');
    fs.writeFileSync(outside, '# 文書C\n');
    const inside = path.join(dir, 'b.md');
    fs.writeFileSync(inside, '# 文書B\n');
    proc = start({ VIEWER_TREE_ROOT: dir });
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === 'a.md');
    await waitFor(sidebarVisible, (v) => v === true);
    const rootName = () => chrome.eval("document.getElementById('tree-root-name').textContent");
    check('ルートを決めて起動すると、サイドバーが開き、フォルダ名が出る（フォルダモード）',
      (await sidebarVisible()) === true && (await rootName()) === path.basename(dir), await rootName());

    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === false);
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(inside)})`);
    await waitFor(fileName, (name) => name === 'b.md');
    await sleep(300);
    check('ルートの中のファイルを開いても、モードは保たれ、手動で閉じたサイドバーは、閉じたまま',
      (await rootName()) === path.basename(dir) && (await sidebarVisible()) === false);

    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === true);
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(outside)})`);
    await waitFor(fileName, (name) => name === 'c.md');
    await waitFor(sidebarVisible, (v) => v === false);
    check('ルートの外のファイルを開くと、単一ファイルモードへ戻り、サイドバーが閉じる',
      (await sidebarVisible()) === false && (await rootName()) === '');
    await chrome.eval('window.viewer.toggleSidebar()');
    await waitFor(sidebarVisible, (v) => v === true);
    check('単一ファイルモードに戻ったあとは、ルートは捨てられ、案内が出る',
      (await chrome.eval("!document.getElementById('tree-hint').hidden")) === true && (await rootName()) === '');
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
