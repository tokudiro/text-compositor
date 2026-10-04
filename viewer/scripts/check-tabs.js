'use strict';
// 複数のタブ（#332）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-tabs.js
//
// 確認すること:
//   - 設定「複数のタブ」がオフ（既定）のときは、タブ列が出ず、新しいタブでは開かない
//   - オンのとき、Ctrlを押しながらのドロップと同じ経路（openPath）で、新しいタブが増え、タブ列が出る
//   - タブを切り替えても、見ていないタブのスクロール位置が保たれる
//   - 見ていないタブの原稿を保存すると、そのタブだけが、自動で更新される
//   - タブを閉じると（閉じるボタン・中ボタン）、隣のタブが表示される。最後の1つは、閉じられない
//   - 設定を「使わない」に戻すと、見ているタブだけが残る

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-tabs-'));
  const filler = Array.from({ length: 120 }, (_, i) => `行${i + 1}です。`).join('\n\n');
  const a = path.join(dir, 'a.md');
  const b = path.join(dir, 'b.md');
  const c = path.join(dir, 'c.md');
  fs.writeFileSync(a, `# 文書A\n\n${filler}\n`);
  fs.writeFileSync(b, '# 文書B\n\nBの本文です。\n');
  fs.writeFileSync(c, '# 文書C\n\nCの本文です。\n');

  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, a], { env: process.env, stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  try {
    const chrome = await connect(await findTarget(/chrome\.html/));
    const contentTargets = async () => (await targets()).filter((t) => t.type === 'page' && /\.html$/.test(t.url) && !/chrome\.html/.test(t.url));
    /** 本文の見出しが、指定の文字のものを探す。 */
    const contentWith = async (heading) => {
      for (const target of await contentTargets()) {
        const connection = await connect(target);
        try {
          if ((await connection.eval("document.querySelector('h1')?.textContent ?? ''")).startsWith(heading)) return connection;   // 見出しの右に、「#」が足されることがある（#337）
        } catch { /* 次へ */ }
        connection.close();
      }
      return null;
    };
    const fileName = () => chrome.eval("document.getElementById('file-name').textContent");
    const tabTitles = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tabs .tab')].map((t) => t.textContent))");
    const tabsVisible = () => chrome.eval("!document.getElementById('tabs-bar').hidden");
    const activeTitle = () => chrome.eval("document.querySelector('#tabs .tab-item.active .tab')?.textContent ?? null");

    await waitFor(fileName, (name) => name === 'a.md');
    check('起動して、Aが表示される', (await fileName()) === 'a.md');

    // -- 設定がオフ（既定） --------------------------------------------------------
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(b)}, true)`);
    await waitFor(fileName, (name) => name === 'b.md');
    check('設定がオフのとき、新しいタブでは開かず、いまのタブで開く（タブ列も出ない）',
      (await fileName()) === 'b.md' && (await tabsVisible()) === false);
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(a)}, false)`);
    await waitFor(fileName, (name) => name === 'a.md');

    // -- 設定をオンにする -------------------------------------------------------------
    await chrome.eval("window.viewer.setSetting('enableTabs', true)");
    check('設定をオンにしただけでは、タブは増えない（1つなので、タブ列は出ない）', (await tabsVisible()) === false);

    // Aを、途中までスクロールしておく
    const contentA = await waitFor(() => contentWith('文書A'), (found) => found !== null);
    await contentA.eval('window.scrollTo(0, 600)');
    await sleep(300);
    const scrollA = await contentA.eval('window.scrollY');
    check('Aを、スクロールした', scrollA > 300, `scrollY=${scrollA}`);

    // -- 新しいタブ ----------------------------------------------------------------
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(b)}, true)`);
    await waitFor(tabsVisible, (v) => v === true);
    await waitFor(fileName, (name) => name === 'b.md');
    check('新しいタブで、Bが開き、タブ列が出る', (await tabsVisible()) === true && (await fileName()) === 'b.md', await tabTitles());
    check('タブは、AとBの2つで、Bが選ばれている', (await tabTitles()) === JSON.stringify(['a.md', 'b.md']) && (await activeTitle()) === 'b.md');

    // -- 切り替え --------------------------------------------------------------------
    await chrome.eval("document.querySelectorAll('#tabs .tab')[0].click()");
    await waitFor(fileName, (name) => name === 'a.md');
    check('Aのタブを押すと、Aに戻る', (await fileName()) === 'a.md' && (await activeTitle()) === 'a.md');
    const scrollAfter = await contentA.eval('window.scrollY');
    check('切り替えても、Aのスクロール位置が保たれる', Math.abs(scrollAfter - scrollA) < 5, `${scrollA} → ${scrollAfter}`);

    // -- 見ていないタブの自動更新 -----------------------------------------------------
    fs.writeFileSync(b, '# 文書B（更新）\n\nBの本文を、書き換えました。\n');
    const contentB = await waitFor(() => contentWith('文書B（更新）'), (found) => found !== null, 10000);
    check('見ていないBを保存すると、Bだけが自動で更新される', contentB !== null);
    check('更新のあいだも、見ているタブは、Aのまま', (await fileName()) === 'a.md');

    // -- 3つ目のタブと、閉じる -----------------------------------------------------------
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(c)}, true)`);
    await waitFor(tabTitles, (titles) => titles === JSON.stringify(['a.md', 'b.md', 'c.md']));
    check('3つ目のタブ（C）が増える', (await tabTitles()) === JSON.stringify(['a.md', 'b.md', 'c.md']), await tabTitles());
    // 真ん中のB（見ていない）を、中ボタンのクリックで閉じる
    await chrome.eval("document.querySelectorAll('#tabs .tab')[1].dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true }))");
    await waitFor(tabTitles, (titles) => titles === JSON.stringify(['a.md', 'c.md']));
    check('見ていないタブ（B）を閉じても、見ているタブ（C）は、変わらない', (await tabTitles()) === JSON.stringify(['a.md', 'c.md']) && (await fileName()) === 'c.md');
    // 見ているC（右端）を、閉じるボタンで閉じると、隣（A）が見える
    await chrome.eval("document.getElementById('tab-close').click()");
    await waitFor(tabsVisible, (v) => v === false);
    await waitFor(fileName, (name) => name === 'a.md');
    check('見ているタブを閉じると、隣のタブ（A）が見える。1つだけになると、タブ列は消える',
      (await fileName()) === 'a.md' && (await tabsVisible()) === false);
    check('閉じたタブの内容のビューは、なくなる', (await contentTargets()).length === 1, `${(await contentTargets()).length}個`);

    // -- 設定を「使わない」に戻す -------------------------------------------------------
    await chrome.eval(`window.viewer.openPath(${JSON.stringify(b)}, true)`);
    await waitFor(tabTitles, (titles) => titles === JSON.stringify(['a.md', 'b.md']));
    await chrome.eval("window.viewer.setSetting('enableTabs', false)");
    await waitFor(tabsVisible, (v) => v === false);
    await sleep(300);
    check('「使わない」に戻すと、見ているタブだけが残る', (await tabsVisible()) === false && (await contentTargets()).length === 1 && (await fileName()) === 'b.md',
      `${(await contentTargets()).length}個 / ${await fileName()}`);
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
