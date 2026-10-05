'use strict';
// プロジェクトモード（#373）を、実際にViewerを起動して確認する（手動。CIでは動かさない）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-project.js
//   （Windowsでは、パスは、`C:/…`の形で渡す。Git Bashの`/c/…`だと、ワーカーが起動しない）
//
// 確認すること:
//   - 設定ファイル（text-compositor.config.yaml）を開くと、サイドバーが開き、章が、書いた順序で、見出しを開いた状態で出る
//   - 開けないファイル・aggregate・誤った章は出ない。誤った章は、警告の帯に出る
//   - 本文は、設定ファイルのソース。章をクリックすると、開き、ハイライトされ、モードは、そのまま
//   - 章の外のファイルを開くと、単一ファイルモードへ戻り、サイドバーが閉じる
//   - 読めない設定（構文の誤り）は、サイドバーを出さず、警告の帯に、理由が出る
//   - フォルダモードで、設定ファイルをクリックしても、モードは変わらない
//   - 数百章でも、すぐ出る（計測を表示する）

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');
const viewerDir = path.resolve(__dirname, '..');
const port = 9500 + Math.floor(Math.random() * 90);
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

async function waitFor(read, predicate, timeoutMs = 10000) {
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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-project-'));
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };
  const write = (name, text) => { const file = path.join(dir, name); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text); return file; };

  // 章のファイルは、設定ファイルと同じフォルダ（inputs.dir: "."）
  const config = write('text-compositor.config.yaml', [
    'inputs:', '  dir: "."', 'chapters:',
    '  - 02_b.md',
    '  - section: 第一編',
    '    chapters:',
    '      - 01_a.md',
    '      - file: c.csv',
    '  - aggregate: tests',
    '  - notes.docx',
    '  - 42',
    '  - 03_z.md', '',
  ].join('\n'));
  for (const name of ['02_b.md', '01_a.md', '03_z.md']) write(name, `# ${name}\n\n本文\n`);
  write('c.csv', 'a,b\n1,2\n');
  write('notes.docx', 'x');
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-project-outside-'));
  const outsideFile = path.join(outside, 'x.md');
  fs.writeFileSync(outsideFile, '# 外\n');

  let proc = null;
  let chrome = null;
  const userData = path.join(dir, 'user-data');
  fs.mkdirSync(userData, { recursive: true });
  // 自動更新は、オンにしておく（旧名称の設定の引き継ぎで、実環境の設定が入ることがあるため、明示する）
  fs.writeFileSync(path.join(userData, 'settings.json'), JSON.stringify({ autoReload: true }));
  const start = (file, env = {}) => {
    proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, file], { env: { ...process.env, ...env }, stdio: ['ignore', 'ignore', 'pipe'] });
    proc.stderr.on('data', () => {});
  };
  const stop = async () => { chrome?.close(); proc?.kill(); await sleep(1000); };

  const fileName = () => chrome.eval("document.getElementById('file-name').textContent");
  const sidebarVisible = () => chrome.eval("!document.getElementById('sidebar').hidden");
  const rootName = () => chrome.eval("document.getElementById('tree-root-name').textContent");
  const items = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tree [role=treeitem]')].filter((i) => i.offsetParent !== null).map((i) => i.getAttribute('aria-label')))").then((s) => JSON.parse(s ?? '[]'));
  const current = () => chrome.eval("JSON.stringify([...document.querySelectorAll('#tree [role=treeitem].current')].map((i) => i.getAttribute('aria-label')))").then((s) => JSON.parse(s ?? '[]'));
  const click = (label) => chrome.eval(`[...document.querySelectorAll('#tree [role=treeitem]')].find((i) => i.getAttribute('aria-label') === ${JSON.stringify(label)}).querySelector('.tree-row').click()`);
  const banner = () => chrome.eval("document.getElementById('banner').hidden ? '' : document.getElementById('banner-text').textContent");

  try {
    // -- 設定ファイルを、起動引数で開く ----------------------------------------------------
    start(config);
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === 'text-compositor.config.yaml');
    const expected = ['02_b.md', '第一編', '01_a.md', 'c.csv', '03_z.md'];
    const listed = await waitFor(items, (names) => names.length >= expected.length);
    check('設定ファイルを開くと、サイドバーが開き、章が、書いた順序で、見出しを開いた状態で出る',
      (await sidebarVisible()) === true && JSON.stringify(listed) === JSON.stringify(expected), JSON.stringify(listed));
    check('開けないファイル・aggregate・誤った章は、出ない', !listed.includes('notes.docx') && !listed.includes('42') && !listed.includes('tests'));
    check('サイドバーの見出しに、設定ファイルの名前が出る', (await rootName()) === 'text-compositor.config.yaml', await rootName());
    check('ツリーの名前が、「章の一覧」になる', (await chrome.eval("document.getElementById('tree').getAttribute('aria-label')")) === '章の一覧');
    const warning = await waitFor(banner, (text) => text.includes('章の一覧'));
    check('誤った章（42）は、警告の帯に出る', warning.includes('42'), warning);

    await click('01_a.md');
    await waitFor(fileName, (name) => name === '01_a.md');
    await waitFor(current, (names) => names.length === 1);
    check('章をクリックすると、開き、その章が、ハイライトされる', (await fileName()) === '01_a.md' && JSON.stringify(await current()) === '["01_a.md"]', JSON.stringify(await current()));
    check('章を開いても、モードは、そのまま（サイドバーも、一覧も、残る）', (await sidebarVisible()) === true && (await rootName()) === 'text-compositor.config.yaml' && (await items()).length === expected.length);

    await click('第一編');
    await sleep(200);
    check('見出しをクリックすると、章が、たたまれる', (await items()).length === 3, JSON.stringify(await items()));
    await click('第一編');
    await sleep(200);

    await chrome.eval(`window.viewer.openPath(${JSON.stringify(outsideFile)})`);
    await waitFor(fileName, (name) => name === 'x.md');
    await waitFor(sidebarVisible, (v) => v === false);
    check('プロジェクトの外のファイルを開くと、単一ファイルモードへ戻り、サイドバーが閉じる', (await sidebarVisible()) === false && (await rootName()) === '');

    await chrome.eval(`window.viewer.openPath(${JSON.stringify(config)})`);
    await waitFor(sidebarVisible, (v) => v === true);
    const again = await waitFor(items, (names) => names.length >= expected.length);
    check('設定ファイルを開き直すと、プロジェクトモードに戻る', JSON.stringify(again) === JSON.stringify(expected), JSON.stringify(again));

    // -- 設定ファイルを保存すると、一覧が更新される（#373） ----------------------------------------
    write('04_new.md', '# new\n');
    fs.writeFileSync(config, 'inputs:\n  dir: "."\nchapters:\n  - 03_z.md\n  - 04_new.md\n  - 02_b.md\n');
    const changed = await waitFor(items, (names) => names.includes('04_new.md'));
    check('設定ファイルを保存すると、章の一覧が、書いた順序で作り直される', JSON.stringify(changed) === JSON.stringify(['03_z.md', '04_new.md', '02_b.md']), JSON.stringify(changed));
    fs.writeFileSync(config, 'chapters: [a.md\n');   // 編集の途中で、構文が壊れた状態
    await sleep(1500);
    check('読めない状態で保存しても、前の一覧が残る', JSON.stringify(await items()) === JSON.stringify(['03_z.md', '04_new.md', '02_b.md']) && (await sidebarVisible()) === true, JSON.stringify(await items()));
    fs.writeFileSync(config, 'inputs:\n  dir: "."\nchapters:\n  - 04_new.md\n');
    const fixed = await waitFor(items, (names) => names.length === 1);
    check('直して保存すると、また更新される', JSON.stringify(fixed) === JSON.stringify(['04_new.md']), JSON.stringify(fixed));
    await stop();

    // -- 読めない設定 -------------------------------------------------------------------
    const broken = write('broken/text-compositor.config.yaml', 'chapters: [a.md\n');
    start(broken);
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === 'text-compositor.config.yaml');
    const message = await waitFor(banner, (text) => text.includes('章の一覧を作れません'));
    check('読めない設定は、サイドバーを出さず、警告の帯に、理由が出る', (await sidebarVisible()) === false && message.includes('章の一覧を作れません'), message);
    await stop();

    // -- フォルダモードで、設定ファイルをクリックしても、モードは変わらない --------------------------
    start(outsideFile, { VIEWER_TREE_ROOT: dir });
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === 'x.md');
    // x.mdは、ルート（dir）の外のため、起動直後に、単一ファイルモードへ戻る。ルートの中のファイルで、起動し直す
    await stop();
    start(path.join(dir, '03_z.md'), { VIEWER_TREE_ROOT: dir });
    chrome = await connect(await findTarget(/chrome\.html/));
    await waitFor(fileName, (name) => name === '03_z.md');
    await waitFor(items, (names) => names.includes('text-compositor.config.yaml'));
    await click('text-compositor.config.yaml');
    await waitFor(fileName, (name) => name === 'text-compositor.config.yaml');
    await sleep(500);
    check('フォルダモードで、設定ファイルをクリックしても、フォルダのまま（章の一覧にならない）',
      (await rootName()) === path.basename(dir) && (await items()).includes('broken') && (await chrome.eval("document.getElementById('tree').getAttribute('aria-label')")) === 'ファイルツリー');
    await stop();

    // -- 数百章の計測 --------------------------------------------------------------------
    const many = write('many/text-compositor.config.yaml', `inputs:\n  dir: "."\nchapters:\n${Array.from({ length: 500 }, (_, i) => `  - ch${String(i).padStart(3, '0')}.md\n`).join('')}`);
    for (let i = 0; i < 500; i++) fs.writeFileSync(path.join(dir, 'many', `ch${String(i).padStart(3, '0')}.md`), `# ${i}\n`);
    start(many);
    const started = Date.now();
    chrome = await connect(await findTarget(/chrome\.html/));
    const listedMany = await waitFor(() => chrome.eval("document.querySelectorAll('#tree [role=treeitem]').length"), (n) => n >= 500, 30000);
    check('500章でも、章の一覧が出る', listedMany === 500, `${listedMany} 項目`);
    console.log(`     計測: 起動から、500章の一覧が出るまで ${Date.now() - started} ms`);
    await stop();
  } catch (error) {
    console.log(`NG   確認を最後まで実行できた  ${error.stack ?? error.message}`);
    results.push(false);
  } finally {
    proc?.kill();
    await sleep(500);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.rmSync(outside, { recursive: true, force: true });
  }
  const failed = results.filter((ok) => !ok).length;
  console.log(failed ? `\n失敗: ${failed}件` : '\nすべて成功');
  process.exit(failed ? 1 : 0);
})();
