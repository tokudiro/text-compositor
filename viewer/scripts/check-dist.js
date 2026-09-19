'use strict';
// 配布物（build-distの成果物）が、Pythonのインストールなしで動くことを確認する（手動。Windowsのみ。#168）。
//   node scripts/check-dist.js [展開したフォルダ]      （省略すると、dist/stage/ のフォルダを使う）
//
// 確認すること:
//   - 環境変数（PATH・TEXT_COMPOSITOR_*・PYTHON*）から、Pythonを、すべて外して起動しても、文書が表示される。
//   - ワーカーが、同梱の python-embed/python.exe で動いている（PATH上のPythonではない）。
//   - 日本語のファイル名・フォルダ名の原稿も、表示できる。
//   - 変換エラーは、帯に出る（ワーカーが、標準出力で、エラーを返せる）。
//   - 同梱しないもの（typst・playwright）が、なくても、HTML出力は成功する。

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます。');
  process.exit(0);
}

const viewerDir = path.resolve(__dirname, '..');
const stage = path.join(viewerDir, 'dist', 'stage');
const appDir = process.argv[2] ? path.resolve(process.argv[2]) : path.join(stage, fs.readdirSync(stage).find((n) => n.startsWith('Obunzu-')));
const exe = path.join(appDir, 'obunzu.exe');
const port = 9500 + Math.floor(Math.random() * 100);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

async function connect() {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(targets.find((t) => t.url.includes('chrome.html')).webSocketDebuggerUrl);
  await new Promise((resolve) => ws.addEventListener('open', resolve));
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => { const m = JSON.parse(event.data); pending.get(m.id)?.(m); });
  return (expression) => new Promise((resolve) => {
    const i = ++id;
    pending.set(i, (m) => resolve(m.result.result.value));
    ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
  });
}

/** アプリの子プロセスのうち、Pythonの実行ファイルのパスを返す。 */
function workerPythonPaths() {
  const out = execFileSync('powershell', ['-NoProfile', '-Command',
    'Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" } | ForEach-Object { $_.ExecutablePath }'], { encoding: 'utf8' });
  return out.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

async function runCase(name, markdown, file, expect) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-dist-'));
  // 最小の環境: Windowsの基本のフォルダだけ。Pythonへの手がかりを、すべて外す。
  const env = { SystemRoot: process.env.SystemRoot, windir: process.env.windir, TEMP: process.env.TEMP, TMP: process.env.TMP,
    USERPROFILE: process.env.USERPROFILE, APPDATA: process.env.APPDATA, LOCALAPPDATA: process.env.LOCALAPPDATA,
    PATH: `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}` };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, markdown);
  const proc = spawn(exe, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, file], { env, stdio: 'ignore' });
  try {
    await sleep(6000);
    const evaluate = await connect();
    const state = JSON.parse(await evaluate("JSON.stringify({ status: document.getElementById('status').textContent, "
      + "banner: document.getElementById('banner').hidden ? '' : document.getElementById('banner-text').textContent, "
      + "file: document.getElementById('file-name').textContent })"));
    expect(state, workerPythonPaths());
  } finally {
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(`   （${name}）`);
}

async function main() {
  check('展開したアプリがある（obunzu.exe と python-embed/）', fs.existsSync(exe) && fs.existsSync(path.join(appDir, 'python-embed', 'python.exe')));
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-dist-docs-'));
  const embedded = path.join(appDir, 'python-embed', 'python.exe').toLowerCase();

  await runCase('通常の原稿', '# 配布物のテスト\n\n本文。\n\n> [!NOTE]\n> alert\n', path.join(work, 'plain.md'), (state, pythons) => {
    check('Pythonなしの環境で、文書が表示される', /更新/.test(state.status) && state.banner === '', JSON.stringify(state));
    check('ワーカーは、同梱のpython-embedで動く', pythons.length > 0 && pythons.every((p) => p.toLowerCase() === embedded), pythons.join(', '));
  });
  await runCase('日本語のフォルダ名・ファイル名', '# 日本語のパス\n\n本文。\n', path.join(work, '日本語のフォルダ', '原稿 その1.md'), (state) => {
    check('日本語のパスの原稿が、表示される', /更新/.test(state.status) && state.banner === '' && state.file === '原稿 その1.md', JSON.stringify(state));
  });
  await runCase('変換エラー', '# エラー\n\n```mermaid\ngraph TD\n  A --> B\n```\n', path.join(work, 'error.md'), (state) => {
    // Mermaidは、playwrightを同梱しないため、この配布物では、エラーとして、帯に出る（#168の記録）
    check('Mermaidは、未対応であることが、帯に出る（エラーで落ちない）', state.banner !== '', JSON.stringify(state));
  });

  fs.rmSync(work, { recursive: true, force: true });
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error) => { console.error(error); process.exit(1); });
