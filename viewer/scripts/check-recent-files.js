'use strict';
// 「最近開いたファイル」（#331）が、実際のアプリで、設定（settings.json）の`recentFiles`に、新しい順・重複なしで、
// 保存され、再起動しても残ることを確認する（手動）。メニューの見た目と、項目を押した動作は、人の目で確かめる。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-recent-files.js
// 2つ目以降のファイルは、同じ設定の置き場所で、もう1度起動して渡す（アプリの2重起動は、既存のウィンドウが受け取る）。

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const viewerDir = path.resolve(__dirname, '..');
const electron = require('electron');
const { sleep, waitExit } = require('./wait-for');
let failures = 0;
function check(name, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
}

const work = fs.mkdtempSync(path.join(viewerDir, '..', 'temp', 'obunzu-recent-'));
const userData = path.join(work, 'user-data');
const doc = (name) => { const file = path.join(work, name); fs.writeFileSync(file, `# ${name}\n`); return file; };
const [a, b, c] = ['a.md', 'b.md', 'c.md'].map(doc);

const readRecent = () => {
  try { return JSON.parse(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8')).recentFiles; } catch { return null; }
};

/** 一覧が、期待どおりになるまで待つ（上限つき）。 */
async function waitRecent(expected, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (JSON.stringify(readRecent()) === JSON.stringify(expected)) return true;
    await sleep(200);
  }
  return false;
}

const launch = (file) => spawn(electron, [`--user-data-dir=${userData}`, viewerDir, file], { env: { ...process.env }, stdio: 'ignore' });
const kill = (proc) => spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });

async function main() {
  const first = launch(a);
  check('1つ目のファイルが、一覧に入る', await waitRecent([a]));
  launch(b);
  check('2つ目のファイルが、先頭に入る', await waitRecent([b, a]));
  launch(c);
  check('3つ目のファイルが、先頭に入る', await waitRecent([c, b, a]));
  launch(a);
  check('開き直したファイルは、重複せず、先頭に移る', await waitRecent([a, c, b]));
  kill(first);
  await waitExit(first);   // 2重起動の判定に、前のプロセスを残さない
  const second = launch(b);
  check('アプリを終了して、起動し直しても、一覧が残る（開いたファイルは、先頭へ）', await waitRecent([b, a, c]));
  kill(second);
  await waitExit(second);
}

main().finally(() => {
  try { fs.rmSync(work, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  console.log(failures === 0 ? '\nすべて OK' : `\n${failures}件 NG`);
  process.exit(failures === 0 ? 0 : 1);
});
