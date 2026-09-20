'use strict';
// 配布物（build-distの成果物）が、Pythonのインストールなしで動くことを確認する（手動。Windowsのみ。#168）。
//   node scripts/check-dist.js [展開したフォルダ]      （省略すると、dist/stage/ のフォルダを使う）
//
// 確認すること:
//   - 環境変数（PATH・TEXT_COMPOSITOR_*・PYTHON*）から、Pythonを、すべて外して起動しても、文書が表示される。
//   - ワーカーが、同梱の python-embed/python.exe で動いている（PATH上のPythonではない）。
//   - 日本語のファイル名・フォルダ名の原稿も、表示できる。
//   - Mermaidの図が、playwrightもシステムのブラウザもなしで、ElectronのChromiumで描画され、表示される（#207）。
//   - Mermaidの構文エラーは、原稿の行つきで、帯・一覧に出る。
//   - Graphviz（dot・graphviz）が、システムのGraphvizなしで、ElectronのChromiumで描画され、構文エラーは、原稿の行つきで出る（#181）。
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

/** 文書のビューのURL。変換したHTMLは、アプリの領域の`html/<ハッシュ>.html`（設定が「原稿の隣」のときは`preview.html`）。ツールバーの`chrome.html`は除く。 */
const isContent = (url) => url.endsWith('.html') && !url.endsWith('/chrome.html');

async function connect(match = 'chrome.html') {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const matches = typeof match === 'function' ? match : (url) => url.includes(match);
  const ws = new WebSocket(targets.find((t) => matches(t.url)).webSocketDebuggerUrl);
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

async function runCase(name, markdown, file, expect, wait = 6000, extraEnv = {}) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-dist-'));
  // 最小の環境: Windowsの基本のフォルダだけ。Pythonへの手がかりを、すべて外す。
  const env = { SystemRoot: process.env.SystemRoot, windir: process.env.windir, TEMP: process.env.TEMP, TMP: process.env.TMP,
    USERPROFILE: process.env.USERPROFILE, APPDATA: process.env.APPDATA, LOCALAPPDATA: process.env.LOCALAPPDATA,
    PATH: `${process.env.SystemRoot}\\System32;${process.env.SystemRoot}`, ...extraEnv };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, markdown);
  const proc = spawn(exe, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, file], { env, stdio: 'ignore' });
  try {
    await sleep(wait);
    const evaluate = await connect();
    const content = await connect(isContent).catch(() => null);   // 文書のビュー（表示できなかったときは、無い）
    const state = JSON.parse(await evaluate("JSON.stringify({ status: document.getElementById('status').textContent, "
      + "banner: document.getElementById('banner').hidden ? '' : document.getElementById('banner-text').textContent, "
      + "file: document.getElementById('file-name').textContent })"));
    await expect(state, workerPythonPaths(), { chrome: evaluate, content });
  } finally {
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(`   （${name}）`);
}

// 同梱の typst・フォント・Typstのパッケージだけで、ネットワークなしで、Typstを通した処理が動くこと（#263）。
// ネットワークは、使えないプロキシを指定して、遮断する。ユーザーのキャッシュ（LOCALAPPDATA）は、空の使い捨てのフォルダにして、
// 開発機に取得済みのフォント・パッケージに、頼っていないことも確かめる。対照として、同じ環境で、同梱のフォルダを教えないときは、失敗する。
const OFFLINE_TYPST_SCRIPT = `import os, sys, tempfile
from text_compositor.compiler import typst_lib, typst_package_options
from text_compositor.deps import ensure_fonts
d = tempfile.mkdtemp()
src = os.path.join(d, 'doc.typ')
with open(src, 'w', encoding='utf-8') as f:
    f.write('#import "@preview/diagraph:0.3.7": render\\n#import "@preview/note-me:0.6.0": note\\n'
            '#set text(font: "Noto Sans JP")\\n#note[日本語の注記]\\n#render("digraph { あ -> い }")\\n')
fonts = ensure_fonts()
pdf = typst_lib.compile(src, root=d, font_paths=[fonts], ignore_system_fonts=True, **typst_package_options())
print(fonts)
print(len(pdf) > 1000)
`;

function checkOfflineTypst(work) {
  const python = path.join(appDir, 'python-embed', 'python.exe');
  const script = path.join(work, 'offline-typst.py');
  fs.writeFileSync(script, OFFLINE_TYPST_SCRIPT, 'utf8');
  const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-offline-'));
  const baseEnv = { SystemRoot: process.env.SystemRoot, windir: process.env.windir, TEMP: process.env.TEMP, TMP: process.env.TMP,
    USERPROFILE: isolated, APPDATA: isolated, LOCALAPPDATA: isolated, PATH: `${process.env.SystemRoot}\\System32`,
    HTTPS_PROXY: 'http://127.0.0.1:9', HTTP_PROXY: 'http://127.0.0.1:9', https_proxy: 'http://127.0.0.1:9', http_proxy: 'http://127.0.0.1:9' };
  const fonts = path.join(appDir, 'fonts');
  const packages = path.join(appDir, 'typst-packages');
  check('fonts/ に、Noto Sans JPのRegularとBoldがある', ['NotoSansJP-Regular.otf', 'NotoSansJP-Bold.otf'].every((name) => fs.existsSync(path.join(fonts, name))));
  check('typst-packages/ に、diagraphとnote-meがある', ['diagraph/0.3.7', 'note-me/0.6.0'].every((name) => fs.existsSync(path.join(packages, 'preview', ...name.split('/'), 'typst.toml'))));
  try {
    const out = execFileSync(python, [script], { encoding: 'utf8', env: { ...baseEnv, TEXT_COMPOSITOR_FONT_DIR: fonts, TEXT_COMPOSITOR_TYPST_PACKAGES: packages } }).trim().split(/\r?\n/);
    check('同梱のtypst・フォント・パッケージだけで、ネットワークなしで、Typstをコンパイルできる（diagraph・note-me・日本語）',
      out[0] === fonts && out[1] === 'True', out.join(' / '));
  } catch (error) {
    check('同梱のtypst・フォント・パッケージだけで、ネットワークなしで、Typstをコンパイルできる', false, String(error.stderr || error.message).split(/\r?\n/).filter(Boolean).slice(-2).join(' / '));
  }
  let controlFailed = false;
  try {
    // フォントは同梱を使い、パッケージだけ教えない。空のキャッシュでは、ダウンロードが要るため、遮断した環境では、失敗する
    execFileSync(python, [script], { encoding: 'utf8', stdio: 'pipe', env: { ...baseEnv, TEXT_COMPOSITOR_FONT_DIR: fonts } });
  } catch { controlFailed = true; }
  check('（対照）パッケージのフォルダを教えないと、同じ環境で失敗する（遮断が効いていて、ユーザーのキャッシュに頼っていない）', controlFailed);
  try { fs.rmSync(isolated, { recursive: true, force: true }); } catch { /* 一時ファイルが残るだけ */ }
}

async function main() {
  check('展開したアプリがある（obunzu.exe と python-embed/）', fs.existsSync(exe) && fs.existsSync(path.join(appDir, 'python-embed', 'python.exe')));
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-dist-docs-'));
  const embedded = path.join(appDir, 'python-embed', 'python.exe').toLowerCase();

  await runCase('通常の原稿', '# 配布物のテスト\n\n本文。\n\n> [!NOTE]\n> alert\n', path.join(work, 'plain.md'), (state, pythons) => {
    check('Pythonなしの環境で、文書が表示される', /更新/.test(state.status) && state.banner === '', JSON.stringify(state));
    check('ワーカーは、同梱のpython-embedで動く', pythons.length > 0 && pythons.every((p) => p.toLowerCase() === embedded), pythons.join(', '));
    // 既定では、原稿のフォルダに、何も書かない（変換したHTMLと図のキャッシュは、アプリの領域。#258）
    check('原稿のフォルダに、.text-compositor/ が作られない', !fs.existsSync(path.join(work, '.text-compositor')), fs.readdirSync(work).join(', '));
  });
  await runCase('日本語のフォルダ名・ファイル名', '# 日本語のパス\n\n本文。\n', path.join(work, '日本語のフォルダ', '原稿 その1.md'), (state) => {
    check('日本語のパスの原稿が、表示される', /更新/.test(state.status) && state.banner === '' && state.file === '原稿 その1.md', JSON.stringify(state));
  });
  // Mermaid（#207）。playwrightもシステムのブラウザも使わず、ElectronのChromiumで描画される。
  // 初回の図は、mermaid.min.jsの取得（未取得なら、数秒）と、描画用のウィンドウの準備を含むため、長めに待つ。
  const mermaidDoc = '# Mermaid\n\n```mermaid\ngraph LR\n  A[開始] --> B[終了]\n```\n\n'
    + '```mermaid\nsequenceDiagram\n  Viewer->>Worker: render_html\n  Worker-->>Viewer: SVG\n```\n';
  await runCase('Mermaidの図', mermaidDoc, path.join(work, 'mermaid.md'), async (state, _pythons, { content }) => {
    check('Mermaidを含む文書が、表示される（エラーの帯がない）', /更新/.test(state.status) && state.banner === '', JSON.stringify(state));
    const images = content ? JSON.parse(await content("JSON.stringify([...document.querySelectorAll('.diagram-mermaid img')].map((i) => i.complete && i.naturalWidth > 0))")) : [];
    check('2つのMermaidの図が、画像として読み込まれている', images.length === 2 && images.every(Boolean), JSON.stringify(images));
    console.log(`   初回の変換（Mermaid 2図、準備を含む）: ${state.status}`);
  }, 12000);
  // キャッシュがない環境（初めて使う人）: mermaid.min.js（約3.4 MB）を、組込版Pythonが、HTTPSで取得できること。
  // （キャッシュの場所は、環境変数ではなく、Windowsのフォルダ設定で決まるため、取得の処理を、直接呼んで確認する）
  const fetchCheck = 'import hashlib, os, tempfile; from text_compositor import deps\n'
    + 'p = os.path.join(tempfile.mkdtemp(), "m.js"); deps._download(deps.MERMAID_JS_URL, p)\n'
    + 'print(hashlib.sha256(open(p, "rb").read()).hexdigest() == deps.MERMAID_JS_SHA256)';
  const fetched = execFileSync(path.join(appDir, 'python-embed', 'python.exe'), ['-c', fetchCheck], {
    encoding: 'utf8', env: { SystemRoot: process.env.SystemRoot, TEMP: process.env.TEMP, TMP: process.env.TMP, USERPROFILE: process.env.USERPROFILE,
      APPDATA: process.env.APPDATA, LOCALAPPDATA: process.env.LOCALAPPDATA, PATH: `${process.env.SystemRoot}\\System32` } });
  check('組込版Pythonが、HTTPSで、mermaid.min.jsを取得でき、SHA256が一致する（初回の取得）', fetched.trim() === 'True', fetched.trim());
  checkOfflineTypst(work);
  await runCase('Mermaidの構文エラー', '# エラー\n\n本文。\n\n```mermaid\ngraph TD\n  A --> \n  B[[[\n```\n', path.join(work, 'error.md'), async (state, _pythons, { chrome }) => {
    const item = JSON.parse(await chrome("JSON.stringify({ head: document.querySelector('#details .item .head')?.textContent ?? '', detail: document.querySelector('#details .item pre')?.textContent ?? '' })"));
    check('構文エラーが、原稿の行つきで、一覧に出る', state.banner.includes('変換エラー') && item.head.includes('error.md:5'), JSON.stringify(item.head));
    check('Mermaidのエラーの内容が、詳細に出る', /Parse error/.test(item.detail), item.detail.split('\n')[0]);
  }, 12000);

  // Graphviz（#181）。システムの`dot`を使わず、Viz.jsを、ElectronのChromiumで動かして描画する。
  const graphvizDoc = '# Graphviz\n\n```dot\ndigraph { rankdir=LR; 開始 -> 処理 -> 終了 }\n```\n\n```graphviz\ngraph { a -- b }\n```\n';
  await runCase('Graphvizの図', graphvizDoc, path.join(work, 'graphviz.md'), async (state, _pythons, { content }) => {
    check('Graphvizを含む文書が、表示される（エラーの帯がない）', /更新/.test(state.status) && state.banner === '', JSON.stringify(state));
    const images = content ? JSON.parse(await content("JSON.stringify([...document.querySelectorAll('.diagram img')].map((i) => i.complete && i.naturalWidth > 0))")) : [];
    check('2つのGraphvizの図が、画像として読み込まれている', images.length === 2 && images.every(Boolean), JSON.stringify(images));
    console.log(`   初回の変換（Graphviz 2図、準備を含む）: ${state.status}`);
  }, 12000);
  const vizFetchCheck = 'import hashlib, os, tempfile; from text_compositor import deps\n'
    + 'p = os.path.join(tempfile.mkdtemp(), "v.js"); deps._download(deps.VIZ_JS_URL, p)\n'
    + 'print(hashlib.sha256(open(p, "rb").read()).hexdigest() == deps.VIZ_JS_SHA256)';
  const vizFetched = execFileSync(path.join(appDir, 'python-embed', 'python.exe'), ['-c', vizFetchCheck], {
    encoding: 'utf8', env: { SystemRoot: process.env.SystemRoot, TEMP: process.env.TEMP, TMP: process.env.TMP, USERPROFILE: process.env.USERPROFILE,
      APPDATA: process.env.APPDATA, LOCALAPPDATA: process.env.LOCALAPPDATA, PATH: `${process.env.SystemRoot}\\System32` } });
  check('組込版Pythonが、HTTPSで、viz-global.jsを取得でき、SHA256が一致する（初回の取得）', vizFetched.trim() === 'True', vizFetched.trim());
  await runCase('Graphvizの構文エラー', '# エラー\n\n本文。\n\n```dot\ngraph { a -- b -- }\n```\n', path.join(work, 'dot-error.md'), async (state, _pythons, { chrome }) => {
    const item = JSON.parse(await chrome("JSON.stringify({ head: document.querySelector('#details .item .head')?.textContent ?? '', detail: document.querySelector('#details .item pre')?.textContent ?? '' })"));
    check('Graphvizの構文エラーが、原稿の行つきで、一覧に出る', state.banner.includes('変換エラー') && item.head.includes('dot-error.md:5'), JSON.stringify(item.head));
    check('Graphvizのエラーの内容が、詳細に出る', /syntax error/.test(item.detail), item.detail.split('\n')[0]);
  }, 12000);

  fs.rmSync(work, { recursive: true, force: true });
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error) => { console.error(error); process.exit(1); });
