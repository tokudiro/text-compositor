'use strict';
// ファイルツリーの自動更新（#549）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-tree-refresh.js
//   （Windowsでは、パスは、`C:/…`の形で渡す。Git Bashの`/c/…`だと、ワーカーが起動しない）
//
// 確認すること:
//   - 展開中のフォルダ（ルートを含む）で、ファイルの追加・改名・削除・フォルダの作成が、数秒以内にツリーへ出る
//   - 展開している子フォルダの状態・フォーカスが、更新で、失われない
//   - フォーカスのあった項目が消えても、キー操作を続けられる（フォーカスが、bodyへ落ちない）
//   - 展開中のフォルダを消すと、ツリーから消える（エラーにならない）
//   - 設定「ファイルツリーの自動更新」を「更新しない」にすると、更新されない。「更新する」に戻すと、その間の変更も出る
//   - 折りたたんでいた間に変わったフォルダは、開き直すときに、読み直される
//   - 設定画面に、設定の行があり、既定は「更新する」

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9600 + Math.floor(Math.random() * 90);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targets() {
  return (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []));
}

async function findTarget(pattern) {
  for (let i = 0; i < 150; i++) {
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
async function waitFor(read, predicate, timeoutMs = 6000) {
  const start = performance.now();
  let last;
  while (performance.now() - start < timeoutMs) {
    try { last = await read(); } catch { last = undefined; }
    if (predicate(last)) return last;
    await sleep(50);
  }
  return last;
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-tree-refresh-'));
  const root = path.join(dir, 'docs');
  fs.mkdirSync(path.join(root, 'sub'), { recursive: true });
  const put = (relative, text) => {
    const file = path.join(root, relative);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text ?? `# ${relative}\n\n本文です。\n`);
  };
  for (const name of ['a.md', 'z.md', 'sub/s1.md']) put(name);

  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, path.join(root, 'a.md')],
    { env: { ...process.env, VIEWER_INACTIVE: '1', VIEWER_TREE_ROOT: root }, stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
  try {
    const chrome = await connect(await findTarget(/chrome\.html/));
    const fileName = () => chrome.eval("document.getElementById('file-name').textContent");
    const names = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tree [role=treeitem]')].filter((i) => i.offsetParent !== null).map((i) => i.getAttribute('aria-label')))");
    const item = (label) => `[...document.querySelectorAll('#tree [role=treeitem]')].find((i) => i.getAttribute('aria-label') === ${JSON.stringify(label)})`;
    const click = (label) => chrome.eval(`${item(label)}.querySelector('.tree-row').click()`);
    const has = async (label) => JSON.parse(await names()).includes(label);
    /** 変更してから、ツリーに出る（または消える）までの時間（ms）。出なければ、null */
    const appears = async (label, shown = true, timeout = 6000) => {
      const t0 = performance.now();
      const ok = await waitFor(() => has(label), (v) => v === shown, timeout);
      return ok === shown ? Math.round(performance.now() - t0) : null;
    };

    await waitFor(fileName, (name) => name === 'a.md');
    await waitFor(names, (v) => v !== '[]');
    check('最初のツリー', (await names()) === JSON.stringify(['sub', 'a.md', 'z.md']), await names());
    await click('sub');
    await waitFor(names, (v) => v.includes('s1.md'));

    // -- ルートの変更 -------------------------------------------------------------------------
    put('new.md');
    let ms = await appears('new.md');
    check('ルートに、ファイルを足すと、ツリーに出る', ms !== null, ms === null ? '出なかった' : `${ms} ms`);
    check('更新しても、展開していた子フォルダ（sub）は、展開のまま、中身も残る',
      (await chrome.eval(`${item('sub')}.getAttribute('aria-expanded')`)) === 'true' && (await has('s1.md')));
    check('並びは、名前順のまま（フォルダが先）', (await names()) === JSON.stringify(['sub', 's1.md', 'a.md', 'new.md', 'z.md']), await names());

    fs.renameSync(path.join(root, 'z.md'), path.join(root, 'y.md'));
    ms = await appears('y.md');
    check('ファイルの名前を変えると、新しい名前が出て、古い名前は消える', ms !== null && !(await has('z.md')), ms === null ? '出なかった' : `${ms} ms`);

    fs.mkdirSync(path.join(root, 'newdir'));
    ms = await appears('newdir');
    check('フォルダを作ると、ツリーに出る（フォルダとして）',
      ms !== null && (await chrome.eval(`${item('newdir')}.dataset.type`)) === 'directory', ms === null ? '出なかった' : `${ms} ms`);

    // -- 展開中の子フォルダの変更 ---------------------------------------------------------------
    put('sub/s2.md');
    ms = await appears('s2.md');
    check('展開中の子フォルダに、ファイルを足すと、ツリーに出る', ms !== null, ms === null ? '出なかった' : `${ms} ms`);

    // -- フォーカス ---------------------------------------------------------------------------
    await chrome.eval(`${item('a.md')}.focus()`);
    put('b.md');
    await appears('b.md');
    check('更新しても、フォーカスのあった項目（a.md）は、フォーカスのまま',
      (await chrome.eval("document.activeElement.getAttribute('aria-label')")) === 'a.md');
    await chrome.eval(`${item('new.md')}.focus()`);
    fs.unlinkSync(path.join(root, 'new.md'));
    ms = await appears('new.md', false);
    const focused = await chrome.eval("document.activeElement.getAttribute('role') + ':' + document.activeElement.getAttribute('aria-label')");
    check('フォーカスのあったファイルが消えても、フォーカスは、ツリーの項目に残る（bodyへ落ちない）',
      ms !== null && focused.startsWith('treeitem:'), `${ms === null ? '消えなかった' : `${ms} ms`} / ${focused}`);

    // -- 設定「更新しない」 ---------------------------------------------------------------------
    await chrome.eval("window.viewer.setSetting('treeAutoRefresh', false)");
    await sleep(300);
    put('off.md');
    await sleep(3000);
    check('「更新しない」の間は、ファイルを足しても、ツリーに出ない', !(await has('off.md')));
    await chrome.eval("window.viewer.setSetting('treeAutoRefresh', true)");
    ms = await appears('off.md');
    check('「更新する」に戻すと、更新しない間の変更も、ツリーに出る', ms !== null, ms === null ? '出なかった' : `${ms} ms`);

    // -- 折りたたんでいた間の変更 -------------------------------------------------------------------
    await click('newdir');
    await waitFor(names, (v) => v.includes('（開けるファイルがありません）'));
    await click('newdir');   // 折りたたむ
    put('newdir/inside.md');
    await sleep(2500);       // 折りたたみ中は、確認の対象ではない。ここでは、まだ読み直されない
    check('折りたたんでいる間は、読み直さない（確認の対象を、増やさない）',
      (await chrome.eval(`[...document.querySelectorAll('#tree [role=treeitem]')].some((i) => i.getAttribute('aria-label') === 'inside.md')`)) === false);
    await click('newdir');   // 開き直す
    ms = await appears('inside.md');
    check('折りたたんでいた間に変わったフォルダは、開き直すときに、読み直される', ms !== null, ms === null ? '出なかった' : `${ms} ms`);
    check('空のフォルダの案内（開けるファイルがありません）は、ファイルが出たら、消える', !(await has('（開けるファイルがありません）')));

    // -- 展開中のフォルダを消す -------------------------------------------------------------------
    fs.rmSync(path.join(root, 'sub'), { recursive: true });
    ms = await appears('sub', false);
    check('展開中のフォルダを消すと、ツリーから消える', ms !== null, ms === null ? '消えなかった' : `${ms} ms`);
    check('消えたフォルダの中の項目（s1.md・s2.md）も、残らない', !(await has('s1.md')) && !(await has('s2.md')));
    put('after-delete.md');
    ms = await appears('after-delete.md');
    check('フォルダを消したあとも、更新は、続く', ms !== null, ms === null ? '出なかった' : `${ms} ms`);

    // -- 設定画面 -----------------------------------------------------------------------------------
    await chrome.eval('window.viewer.toggleSettings()');
    await waitFor(() => chrome.eval("!document.getElementById('settings').hidden"), (v) => v === true);
    const row = await chrome.eval(`JSON.stringify({
      on: document.querySelector('#settings input[name="treeAutoRefresh"][value="true"]')?.checked,
      off: document.querySelector('#settings input[name="treeAutoRefresh"][value="false"]')?.checked,
      name: document.getElementById('tree-auto-refresh-name')?.textContent,
    })`);
    check('設定画面に、行があり、いまの設定（更新する）が選ばれている', JSON.parse(row).on === true && JSON.parse(row).off === false && JSON.parse(row).name === 'ファイルツリーの自動更新', row);
    await chrome.eval(`document.querySelector('#settings input[name="treeAutoRefresh"][value="false"]').click()`);
    await sleep(300);
    const saved = JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8'));
    check('設定画面で「更新しない」を選ぶと、設定として保存される', saved.treeAutoRefresh === false, JSON.stringify(saved.treeAutoRefresh));
    chrome.close();
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
