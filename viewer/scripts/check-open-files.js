'use strict';
// Markdown以外のファイル（.txt・.csv・.svg・図の単体ファイル・対象外の拡張子・文字コード・フォルダ・存在しない・大きなファイル）を、
// コマンドライン引数で渡して、実際のアプリで、表示・案内が出ることを確認する（手動。#196）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-open-files.js
// 配布物を確認するときは、引数に、展開したフォルダ（obunzu.exeがある場所）を渡す。

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const viewerDir = path.resolve(__dirname, '..');
const packaged = process.argv[2] ? path.resolve(process.argv[2]) : null;
const electron = packaged ? path.join(packaged, 'obunzu.exe') : require('electron');
const port = 9700 + Math.floor(Math.random() * 100);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

async function connect(match) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const target = targets.find((t) => t.url.includes(match));
  if (!target) return null;
  const ws = new WebSocket(target.webSocketDebuggerUrl);
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

/** ファイルを引数にして起動し、少し待って、画面の状態（帯・状態・文書の中身）を読む。 */
async function open(arg, wait = 4500, act = null) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-open-'));
  const args = packaged ? [] : [viewerDir];
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, ...args, arg], { env: { ...process.env }, stdio: 'ignore' });
  const started = Date.now();
  try {
    await sleep(wait);
    const chrome = await connect('chrome.html');
    if (act) { await act(chrome); await sleep(3000); }
    const state = JSON.parse(await chrome("JSON.stringify({ status: document.getElementById('status').textContent, "
      + "banner: document.getElementById('banner').hidden ? '' : document.getElementById('banner-text').textContent, "
      + "detail: document.querySelector('#details .item')?.textContent ?? '' })"));
    const content = await connect('preview.html');
    const page = content ? JSON.parse(await content("JSON.stringify({ text: document.querySelector('pre.plain-text')?.textContent ?? null, "
      + "notes: [...document.querySelectorAll('.text-note')].map((n) => n.textContent), headings: document.querySelectorAll('h1,h2,ul').length, "
      + "images: [...document.querySelectorAll('img')].map((i) => i.complete && i.naturalWidth > 0), "
      + "tableHead: [...document.querySelectorAll('table.csv th')].map((c) => c.textContent), tableRows: document.querySelectorAll('table.csv tbody tr').length, "
      + "code: document.querySelector('pre code')?.textContent ?? null })")) : null;
    const csvButton = JSON.parse(await chrome("JSON.stringify({ hidden: document.getElementById('csv-header').hidden, checked: document.getElementById('csv-header').getAttribute('aria-checked') })"));
    let saved = null;
    try { saved = JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8')); } catch { /* 保存されていない */ }
    return { state, page, csvButton, saved, ms: Date.now() - started };
  } finally {
    spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    await sleep(1500);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
}

async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-open-docs-'));
  const write = (name, data) => { const p = path.join(work, name); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, data); return p; };
  const guide = (state) => /Markdown（\.md）/.test(state.detail) && /テキスト（\.txt）/.test(state.detail);

  let r = await open(write('memo.txt', '# 見出しに見える行\n- リストに見える行\n    インデント\n'));
  check('.txtが、Markdownとして解釈されず、等幅の素のテキストで表示される',
    r.page?.text === '# 見出しに見える行\n- リストに見える行\n    インデント\n' && r.page.headings === 0 && r.state.banner === '', JSON.stringify(r.page));

  r = await open(write('日本語の フォルダ/一覧.csv', '名前,数,備考\nりんご,10,"甘い, 赤い"\nみかん,3,\n'));
  check('.csvが、1行目を見出しにした表で表示される（日本語のフォルダ名）',
    JSON.stringify(r.page?.tableHead) === JSON.stringify(['名前', '数', '備考']) && r.page.tableRows === 2 && r.state.banner === '', JSON.stringify(r.page));

  r = await open(write('pic.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect width="120" height="60" fill="#3f9be0"/></svg>'));
  check('.svgが、画像として表示される', r.page?.images.length === 1 && r.page.images[0] === true && r.state.banner === '', JSON.stringify(r.page?.images));

  for (const name of ['settings.yaml', 'data.json', 'README', 'app.log', 'page.html', 'image.png', 'doc.pdf']) {
    r = await open(write(name, name.endsWith('.png') || name.endsWith('.pdf') ? Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 1, 2]) : 'content\n'), 3500);
    check(`${name}: 対象外のファイルは、案内つきのエラーになる`, r.state.banner.includes('変換エラー') && guide(r.state), r.state.detail.slice(0, 80));
  }

  r = await open(write('sjis.txt', Buffer.from([0x93, 0xfa, 0x96, 0x7b, 0x8c, 0xea, 0x0a])), 3500);   // 「日本語」（Shift_JIS）
  check('Shift_JISのファイルは、UTF-8（BOMなし）だけに対応、と案内される', r.state.banner.includes('変換エラー') && /UTF-8（BOMなし）/.test(r.state.detail) && /Shift_JIS/.test(r.state.detail), r.state.detail.slice(0, 100));
  r = await open(write('bom.txt', Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('abc')])), 3500);
  check('BOMつきのUTF-8は、案内つきのエラーになる', r.state.banner.includes('変換エラー') && /BOM/.test(r.state.detail), r.state.detail.slice(0, 100));

  r = await open(path.join(work, '存在しない.txt'), 3000);
  check('存在しないファイルの指定は、黙って無視されず、案内が出る', r.state.banner.includes('変換エラー') && r.state.detail.includes('ファイルが見つかりません: 存在しない.txt'), r.state.detail);
  fs.mkdirSync(path.join(work, 'フォルダ'), { recursive: true });
  r = await open(path.join(work, 'フォルダ'), 3000);
  check('フォルダの指定は、案内が出る', r.state.detail.includes('フォルダは開けません'), r.state.detail);

  r = await open(write('big.txt', ('2026-09-20 12:34:56 INFO request handled path=/api/items id=42 ms=13 ok\n').repeat(30_000)), 7000);
  check('大きなファイル（約2 MB）は、先頭の約512 KBだけが、表示され、案内が出る（固まらない）',
    r.page?.notes.some((n) => n.includes('先頭の約512 KB')) && r.page.text.length <= 512 * 1024 && /更新/.test(r.state.status), `${r.state.status} / ${r.page?.notes}`);

  // CSVの、1行目を見出しにするかの切り替え（#220）。ボタンは、.csvのときだけ出て、切り替えは、設定として覚える。
  const csvText = 'りんご,10\nみかん,3\nぶどう,2\n';
  r = await open(write('noheader.csv', csvText));
  check('.csvでは、見出しの切り替えのボタンが出て、既定は、1行目が見出し', r.csvButton.hidden === false && r.csvButton.checked === 'true' && r.page?.tableHead.length === 2 && r.page.tableRows === 2, JSON.stringify(r.csvButton));
  r = await open(write('noheader2.csv', csvText), 4500, (chrome) => chrome("document.getElementById('csv-header').click()"));
  check('ボタンを押すと、すべての行がデータ行になり、設定として覚える',
    r.page?.tableHead.length === 0 && r.page.tableRows === 3 && r.csvButton.checked === 'false' && r.saved?.csvHeader === false, JSON.stringify({ head: r.page?.tableHead, rows: r.page?.tableRows, saved: r.saved?.csvHeader }));
  r = await open(write('other.txt', 'text\n'));
  check('.csv以外では、見出しの切り替えのボタンが出ない', r.csvButton.hidden === true);
  // 図の単体ファイル（Mermaid・PlantUML・D2・Graphviz）は、図として表示される。
  r = await open(write('flow.mmd', 'graph LR\n  A[開始] --> B[終了]\n'), 9000);
  check('.mmd（Mermaid）が、図として表示される', r.page?.images.length === 1 && r.page.images[0] === true && r.state.banner === '', `${r.state.status} ${JSON.stringify(r.page?.images)}`);
  r = await open(write('seq.puml', '@startuml\nAlice -> Bob: Hello\n@enduml\n'), 15000);
  check('.puml（PlantUML）が、図として表示される', r.page?.images.length === 1 && r.page.images[0] === true && r.state.banner === '', `${r.state.status} ${r.state.banner}`);
  r = await open(write('graph.d2', 'A -> B: hello\n'), 12000);
  check('.d2（D2）が、図として表示される', r.page?.images.length === 1 && r.page.images[0] === true && r.state.banner === '', `${r.state.status} ${r.state.banner}`);
  // Graphviz（#181）。Viz.jsは、初回に取得する（キャッシュがあれば、すぐ）。ElectronのChromium上で描画する。
  for (const name of ['g.dot', 'g.gv']) {
    r = await open(write(name, 'digraph { 開始 -> 処理 -> 終了 }\n'), 9000);
    check(`${name}（Graphviz）が、図として表示される`, r.page?.images.length === 1 && r.page.images[0] === true && r.state.banner === '', `${r.state.status} ${r.state.banner}`);
  }
  r = await open(write('with-dot.md', '# 図\n\n```dot\ndigraph { rankdir=LR; 長い日本語のラベルを持つノード -> b }\n```\n\n```graphviz\ngraph { a -- b }\n```\n'), 9000);
  check('Markdownの```dotと```graphvizが、図として表示される', r.page?.images.length === 2 && r.page.images.every(Boolean) && r.state.banner === '', `${r.state.status} ${JSON.stringify(r.page?.images)} ${r.state.banner}`);
  r = await open(write('bad.dot', 'graph { a -- b -- }\n'), 9000);
  check('Graphvizの構文エラーは、変換エラーとして、原因が示される', r.state.banner.includes('変換エラー') && /syntax error/.test(r.state.detail), `${r.state.banner} / ${r.state.detail.slice(0, 120)}`);

  fs.rmSync(work, { recursive: true, force: true });
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error) => { console.error(error); process.exit(1); });