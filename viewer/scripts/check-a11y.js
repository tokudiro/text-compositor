'use strict';
// Obunzuの画面のアクセシビリティを、axe-core（開発用。配布物には入らない）と、実際の操作で、チェックする（#340）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-a11y.js
//
// 確認すること（実際のElectronを起動する。Windowsのみ。実行中は、ほかのウィンドウを操作しないこと）:
//   - axe: ツールバー・検索・設定画面・エラーの帯と一覧（ウィンドウ本体のビュー）と、文書の表示（変換済みのHTML）に、
//     違反がない。ライトとダークの両方（文字のコントラスト比を含む）。
//   - 部品の名前・役割・状態: ツールバー・検索のランドマーク、すべてのボタンの名前、エラーの帯の通知（alert）、
//     「詳細」の開閉の状態、拡大率を含む名前、読み上げ用の領域。
//   - キーボード: 設定を開くと、フォーカスが見出しへ移る。F6で、ツールバーと文書の間を、行き来できる。
// 内容のビュー（文書）は、DevTools Protocolから直接は調べられないため、同じHTMLを、別のウィンドウで開いて調べる（a11y-content.js）。
// 画面の読み上げそのもの（NVDAなど）は、自動では確かめられない。手動の確認の手順は、doc/viewer-accessibility.mdにある。
// 引数に`--report`を付けると、違反の詳細を、すべて表示する（既定は、失敗した項目だけ）。

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます（F6のキー操作に、SendKeysを使うため）。');
  process.exit(0);
}

const viewerDir = path.resolve(__dirname, '..');
const electron = require('electron');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const report = process.argv.includes('--report');
const python = process.env.TEXT_COMPOSITOR_PYTHON || 'python';

const GOOD_DOC = [
  '# アクセシビリティの確認', '', '本文です。[リンク](https://example.com)も、あります。', '',
  '## 表と一覧', '', '| 名前 | 値 |', '| --- | --- |', '| a | 1 |', '', '- 項目1', '- 項目2', '',
  '## 図', '', '```dot', 'digraph { A -> B }', '```', '',
  '## コード', '', '```python', 'def f(x):', '    return x + 1', '```', '',
].join('\n');
const ERROR_DOC = ['# エラーの確認', '', '本文。', '', '```dot', 'digraph { A -> }', '```', ''].join('\n');

// ウィンドウ本体のビューには、見出しも、メインのランドマークもない（文書は、別のビューにあり、そちらに、見出しがある）。
// そのため、この2つの規則は、ウィンドウ本体のビューでは、調べない。
const CHROME_DISABLED_RULES = ['landmark-one-main', 'page-has-heading-one'];

async function connectChrome(port) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const target = targets.find((t) => t.url.includes('chrome.html'));
  if (!target) throw new Error('ウィンドウ本体のビューが見つかりません');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve) => ws.addEventListener('open', resolve));
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => { const m = JSON.parse(event.data); pending.get(m.id)?.(m); });
  const send = (method, params = {}) => new Promise((resolve) => {
    const i = ++id;
    pending.set(i, resolve);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expression) => {
    const m = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description ?? 'evaluate failed');
    return m.result.result.value;
  };
  return { evaluate, send, close: () => ws.close() };
}

const axeRun = (rules) => `axe.run(document, { resultTypes: ['violations'], rules: ${JSON.stringify(Object.fromEntries(rules.map((r) => [r, { enabled: false }])))} })
  .then((r) => r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help,
    nodes: v.nodes.map((n) => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split(String.fromCharCode(10)).slice(0, 2).join(' / ')) })))`;

async function runAxe(view) {
  // ウィンドウ本体のビューは、CSP（script-src 'self'）で、scriptの要素を禁じている。DevTools Protocolの評価は、CSPの対象外のため、そのまま渡す。
  // 最後の式の値（axeの全体）を、返さない（巨大で、止まるため）
  await view.evaluate(`if (!window.axe) {\n${axeSource}\n}\n0`);
  return view.evaluate(axeRun(CHROME_DISABLED_RULES));
}

async function setScheme(view, scheme) {
  await view.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
  await sleep(300);
}

function sendKeys(keys) {
  const script = 'Add-Type -AssemblyName System.Windows.Forms; '
    + '(New-Object -ComObject WScript.Shell).AppActivate((Get-Process electron | ? MainWindowTitle | select -First 1).Id) | Out-Null; '
    + `Start-Sleep -Milliseconds 400; [Windows.Forms.SendKeys]::SendWait("${keys}")`;
  execFileSync('powershell', ['-NoProfile', '-Command', script]);
}

async function session(file, body, { settings = null } = {}) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-a11y-'));
  if (settings) fs.writeFileSync(path.join(userData, 'settings.json'), JSON.stringify(settings));
  const port = 9500 + Math.floor(Math.random() * 100);
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, file],
    { env: { ...process.env }, stdio: 'ignore' });
  try {
    await sleep(7000);
    const chrome = await connectChrome(port);
    await body({ chrome });
    chrome.close();
  } finally {
    proc.kill();
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
}

/** 原稿を、HTMLにする（ワーカーと同じ処理）。 */
function renderHtml(markdownPath) {
  const code = 'import sys; from text_compositor.api import render_html; '
    + 'r = render_html(sys.argv[1], plugins={"mermaid": False, "plantuml": False, "d2": False}); print(r.html_path)';
  const out = execFileSync(python, ['-c', code, markdownPath], { env: { ...process.env, PYTHONPATH: process.env.TEXT_COMPOSITOR_PYTHONPATH || path.resolve(viewerDir, '..') }, encoding: 'utf8' });
  return out.trim().split(/\r?\n/).pop();
}

function auditContent(htmlPath, scheme) {
  const out = execFileSync(electron, [path.join(__dirname, 'a11y-content.js'), htmlPath, scheme], { encoding: 'utf8', timeout: 60000 });
  return JSON.parse(out.slice(out.indexOf('A11Y_RESULT') + 'A11Y_RESULT'.length));
}

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail && (!ok || report) ? `  ${detail}` : ''}`);
}
function checkAxe(name, violations) {
  check(`axe: ${name}`, violations.length === 0, violations.map((v) => `\n      [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes.slice(0, 3).join(' | ')}`).join(''));
}

async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-a11y-docs-'));
  const good = path.join(work, 'good.md');
  const bad = path.join(work, 'err.md');
  fs.writeFileSync(good, GOOD_DOC);
  fs.writeFileSync(bad, ERROR_DOC);
  const click = (view, id) => view.evaluate(`document.getElementById('${id}').click()`);

  const html = renderHtml(good);
  checkAxe('文書の表示（ライト）', auditContent(html, 'light'));
  checkAxe('文書の表示（ダーク）', auditContent(html, 'dark'));

  await session(good, async ({ chrome }) => {
    // 文書の表示を待つ（初回は、Typstの図の描画に、時間がかかる）
    let shown = false;
    for (let i = 0; i < 60 && !shown; i += 1) {
      shown = await chrome.evaluate("/更新/.test(document.getElementById('status').textContent) && document.getElementById('empty').hidden");
      if (!shown) await sleep(1000);
    }
    check('文書が、表示される（以降の確認の前提）', shown === true,
      shown === true ? '' : await chrome.evaluate("JSON.stringify({ status: document.getElementById('status').textContent, banner: document.getElementById('banner-text').textContent, busy: !document.getElementById('busy').hidden, empty: !document.getElementById('empty').hidden })"));
    for (const scheme of ['light', 'dark']) {
      await setScheme(chrome, scheme);
      const label = scheme === 'light' ? 'ライト' : 'ダーク';
      checkAxe(`ツールバー（${label}）`, await runAxe(chrome));
      await click(chrome, 'search-button');
      await sleep(500);
      checkAxe(`検索の行を開いた状態（${label}）`, await runAxe(chrome));
      await click(chrome, 'search-close');
      await click(chrome, 'settings-button');
      await sleep(600);
      checkAxe(`設定画面（${label}）`, await runAxe(chrome));
      await click(chrome, 'settings-close');
      await sleep(300);
    }
    await setScheme(chrome, 'light');

    // 部品の名前・役割・状態
    const parts = JSON.parse(await chrome.evaluate(`JSON.stringify({
      lang: document.documentElement.lang,
      toolbar: { role: document.getElementById('toolbar').getAttribute('role'), name: document.getElementById('toolbar').getAttribute('aria-label') },
      header: document.getElementById('top').tagName,
      search: document.getElementById('search').getAttribute('role'),
      unnamed: [...document.querySelectorAll('button')].filter((b) => !(b.getAttribute('aria-label') || b.textContent.trim())).map((b) => b.id),
      zoomLabel: document.getElementById('zoom').getAttribute('aria-label'),
      live: document.getElementById('live').getAttribute('role'),
      status: document.getElementById('status').getAttribute('aria-hidden'),
    })`));
    check('<html>に、言語（lang）がある', parts.lang === 'ja', parts.lang);
    check('ツールバーが、role=toolbarで、名前がある', parts.toolbar.role === 'toolbar' && !!parts.toolbar.name, JSON.stringify(parts.toolbar));
    check('部品が、ランドマーク（header・search）に入っている', parts.header === 'HEADER' && parts.search === 'search', JSON.stringify(parts));
    check('名前のないボタンがない', parts.unnamed.length === 0, parts.unnamed.join(','));
    check('拡大率のボタンの名前に、今の倍率が入る', /現在 \d+%/.test(parts.zoomLabel), parts.zoomLabel);
    check('読み上げ用の領域（role=status）がある。画面の状態表示は、二重に読ませない', parts.live === 'status' && parts.status === 'true', JSON.stringify(parts));

    // キーボード: 設定を開いたとき、フォーカスが、見出しへ移る
    await click(chrome, 'settings-button');
    await sleep(600);
    check('設定を開くと、フォーカスが、見出し（設定）へ移る', (await chrome.evaluate('document.activeElement.id')) === 'settings-title');
    await click(chrome, 'settings-close');
    await sleep(500);

    // F6: ツールバーと文書の間を、行き来する（実際のキー操作）
    sendKeys('{F6}');
    await sleep(700);
    const afterFirst = await chrome.evaluate("document.hasFocus() && document.activeElement?.closest('#toolbar') ? document.activeElement.id : ''");
    check('F6で、文書から、ツールバーのボタンへ、フォーカスが移る', afterFirst !== '', afterFirst);
    sendKeys('{F6}');
    await sleep(700);
    const afterSecond = await chrome.evaluate("document.hasFocus() && document.activeElement?.closest('#toolbar') ? document.activeElement.id : ''");
    check('もう一度F6で、文書へ戻る（ツールバーのフォーカスが外れる）', afterSecond === '', afterSecond);
  });

  await session(bad, async ({ chrome }) => {
    await sleep(1500);
    check('エラーの帯が出る', (await chrome.evaluate("!document.getElementById('banner').hidden")) === true);
    const banner = JSON.parse(await chrome.evaluate(`JSON.stringify({
      role: document.getElementById('banner').getAttribute('role'),
      toggle: document.getElementById('banner-toggle').tagName,
      expanded: document.getElementById('banner-toggle').getAttribute('aria-expanded'),
    })`));
    check('エラーの帯が、role=alertで、すぐ読み上げられる', banner.role === 'alert', JSON.stringify(banner));
    check('「詳細」は、ボタン（キーボードで押せる）で、開閉の状態を持つ', banner.toggle === 'BUTTON' && ['true', 'false'].includes(banner.expanded), JSON.stringify(banner));
    for (const scheme of ['light', 'dark']) {
      await setScheme(chrome, scheme);
      const label = scheme === 'light' ? 'ライト' : 'ダーク';
      checkAxe(`エラーの帯と一覧（${label}）`, await runAxe(chrome));
    }
    await setScheme(chrome, 'light');
    await chrome.evaluate("document.getElementById('banner-toggle').click()");
    await sleep(400);
    const toggled = await chrome.evaluate("document.getElementById('banner-toggle').getAttribute('aria-expanded')");
    check('「詳細」を押すと、aria-expandedが切り替わる', toggled === 'true' || toggled === 'false');
    checkAxe('エラーの一覧を閉じた状態・開いた状態（ライト）', await runAxe(chrome));
  });

  // タブ列（#332）。設定「複数のタブ」をオンにして、2つのタブを開いた状態を調べる（既定のオフでは、タブ列が出ないため）
  await session(good, async ({ chrome }) => {
    await sleep(2500);
    await chrome.evaluate(`window.viewer.openPath(${JSON.stringify(bad)}, true)`);
    let visible = false;
    for (let i = 0; i < 40 && !visible; i += 1) {
      visible = await chrome.evaluate("!document.getElementById('tabs-bar').hidden && document.querySelectorAll('#tabs .tab').length === 2");
      if (!visible) await sleep(500);
    }
    check('タブが2つになり、タブ列が出る（以降の確認の前提）', visible === true);
    for (const scheme of ['light', 'dark']) {
      await setScheme(chrome, scheme);
      checkAxe(`タブ列を出した状態（${scheme === 'light' ? 'ライト' : 'ダーク'}）`, await runAxe(chrome));
    }
    await setScheme(chrome, 'light');
    const tabs = JSON.parse(await chrome.evaluate(`JSON.stringify({
      list: { role: document.getElementById('tabs').getAttribute('role'), name: document.getElementById('tabs').getAttribute('aria-label') },
      tabs: [...document.querySelectorAll('#tabs .tab')].map((t) => ({ role: t.getAttribute('role'), selected: t.getAttribute('aria-selected'), name: t.textContent.trim() })),
      closeName: document.getElementById('tab-close').getAttribute('aria-label') || '',
      tablistChildren: [...document.getElementById('tabs').querySelectorAll('button')].every((b) => b.getAttribute('role') === 'tab'),
      newName: document.getElementById('tab-new').getAttribute('aria-label'),
    })`));
    check('タブ列が、role=tablistで、名前がある', tabs.list.role === 'tablist' && !!tabs.list.name, JSON.stringify(tabs.list));
    check('各タブが、role=tabで、名前を持つ', tabs.tabs.length === 2 && tabs.tabs.every((t) => t.role === 'tab' && t.name), JSON.stringify(tabs.tabs));
    check('選ばれているタブが、ちょうど1つで、aria-selectedで伝わる', tabs.tabs.filter((t) => t.selected === 'true').length === 1 && tabs.tabs.filter((t) => t.selected === 'false').length === 1, JSON.stringify(tabs.tabs));
    check('閉じるボタンに、どのタブかが分かる名前がある。tablistの中には、tabだけがある', /「.+」を閉じる/.test(tabs.closeName) && tabs.tablistChildren === true, JSON.stringify({ closeName: tabs.closeName, tablistChildren: tabs.tablistChildren }));
    check('「新しいタブで開く」のボタンに、名前がある', !!tabs.newName, tabs.newName);
    // キーボード: タブのボタンは、フォーカスでき、Enterの代わりのクリックで、切り替わる
    await chrome.evaluate("document.querySelectorAll('#tabs .tab')[0].focus()");
    check('タブのボタンに、フォーカスできる', (await chrome.evaluate("document.activeElement?.classList.contains('tab')")) === true);
    await chrome.evaluate("document.querySelectorAll('#tabs .tab')[0].click()");
    await sleep(600);
    check('タブを押すと、選ばれるタブが切り替わる', (await chrome.evaluate("document.querySelectorAll('#tabs .tab')[0].getAttribute('aria-selected')")) === 'true');
    checkAxe('タブを切り替えたあと（ライト）', await runAxe(chrome));
  }, { settings: { enableTabs: true } });

  fs.rmSync(work, { recursive: true, force: true });
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
