'use strict';
// 自動再読み込み（#170）を、実際にViewerを起動して確認し、保存から表示の更新までの時間を測る。
// 開発者ツールのプロトコルで、内容のビューと、ツールバーを読む。Electronと、Pythonのワーカーが要る（CIでは動かさない）。
//
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-auto-reload.js [--runs 5]
//
// 確認すること:
//   1. 原稿の保存で、表示が自動で更新される（保存から更新まで。連続した保存を含む）
//   2. 更新で、スクロール位置が保たれる
//   3. エディタの原子的な保存（一時ファイルへ書いて、名前を付け替える）
//   4. 参照する画像の変更でも、表示が更新される
//   5. 変換に失敗しても、直前の表示が残り、直して保存すると、自動で回復する
//   6. 自動更新を切ると、更新されない

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const electron = require('electron');   // Electronの実行ファイルのパス
const viewerDir = path.resolve(__dirname, '..');
const port = 9600 + Math.floor(Math.random() * 300);
const runs = Number(process.argv[process.argv.indexOf('--runs') + 1]) || 5;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// -- 開発者ツールのプロトコル ---------------------------------------------------------

async function targets() {
  return (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json()).catch(() => []));
}

async function findTarget(pattern) {
  for (let i = 0; i < 80; i++) {
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
      const reply = await new Promise((resolve) => { waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, returnByValue: true } })); });
      return reply.result?.result?.value;
    },
    close: () => ws.close(),
  };
}

// -- 原稿 --------------------------------------------------------------------------------

function markdown(title, { image = true, extra = '' } = {}) {
  const paragraphs = Array.from({ length: 60 }, (_, i) => `段落${i + 1}。これは、スクロールできる長さにするための、本文です。`).join('\n\n');
  return `# ${title}\n\n${paragraphs}\n\n${image ? '![pic](pic.png)\n\n' : ''}${extra}\n`;
}

function png(color) {
  // 1色の、小さなPNG（標準ライブラリだけで作る）
  const zlib = require('node:zlib');
  const crc = (buf) => { let c, crcValue = 0xffffffff; for (let n = 0; n < buf.length; n++) { c = (crcValue ^ buf[n]) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; crcValue = (crcValue >>> 8) ^ c; } return (crcValue ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body)); return Buffer.concat([len, body, sum]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(8, 0); ihdr.writeUInt32BE(8, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.concat(Array.from({ length: 8 }, () => Buffer.concat([Buffer.from([0]), Buffer.from(color.flatMap((c) => Array(8).fill(c)))])));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

const stats = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return `平均 ${Math.round(values.reduce((a, b) => a + b, 0) / values.length)} ms（最小 ${Math.round(sorted[0])}、最大 ${Math.round(sorted.at(-1))}）`;
};

// -- 確認 --------------------------------------------------------------------------------

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-reload-'));
  const md = path.join(dir, 'doc.md');
  fs.writeFileSync(md, markdown('版0'));
  fs.writeFileSync(path.join(dir, 'pic.png'), png([200, 30, 30]));

  const env = { ...process.env };
  // 設定（自動更新のオン・オフ）は保存されるため、確認用のユーザーデータで動かし、使っている設定を変えない
  const userData = path.join(dir, 'user-data');
  const proc = spawn(electron, [`--remote-debugging-port=${port}`, `--user-data-dir=${userData}`, viewerDir, md], { env, stdio: 'ignore' });
  const results = [];
  const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`); };

  try {
    const content = await connect(await findTarget(/preview\.html/));
    const chrome = await connect(await findTarget(/chrome\.html/));
    const h1 = () => content.eval("document.querySelector('h1')?.textContent ?? ''");
    const waitH1 = async (expected, timeoutMs = 20000) => {
      const start = performance.now();
      while (performance.now() - start < timeoutMs) {
        if ((await h1()) === expected) return performance.now() - start;
        await sleep(4);
      }
      return null;
    };
    const waitForStatus = async (predicate, timeoutMs = 20000) => {
      const start = performance.now();
      while (performance.now() - start < timeoutMs) {
        if (predicate(await chrome.eval("document.getElementById('status').textContent"))) return true;
        await sleep(20);
      }
      return false;
    };

    check('起動して、最初の版が表示される', (await waitH1('版0')) !== null);
    await sleep(600);

    // 1. 保存 → 更新
    const times = [];
    for (let i = 1; i <= runs; i++) {
      const start = performance.now();
      fs.writeFileSync(md, markdown(`版${i}`));
      const t = await waitH1(`版${i}`);
      times.push(t === null ? NaN : performance.now() - start);
      await sleep(400);
    }
    check(`保存から表示の更新まで（本文の編集、${runs}回）`, times.every(Number.isFinite), stats(times));

    // 1b. 図（Mermaid）を変更した場合。1回目は、Mermaid用のブラウザの起動を含み、2回目以降は、ブラウザを使い回す。
    const diagram = (label) => `\`\`\`mermaid\ngraph LR\n  A[${label}] --> B[終了]\n\`\`\`\n`;
    const diagramTimes = [];
    for (let i = 1; i <= 4; i++) {
      const start = performance.now();
      fs.writeFileSync(md, markdown(`版図${i}`, { extra: diagram(`開始${i}`) }));
      const t = await waitH1(`版図${i}`, 60000);
      diagramTimes.push(t === null ? NaN : performance.now() - start);
      await sleep(400);
    }
    console.log(`     図の変更: 1回目（ブラウザの起動を含む） ${Math.round(diagramTimes[0])} ms、2回目以降 ${stats(diagramTimes.slice(1))}`);
    check('図（Mermaid）を変更しても、更新される', diagramTimes.every(Number.isFinite));

    // 2. スクロール位置の保持
    await content.eval('window.scrollTo(0, 1000); window.scrollY');
    fs.writeFileSync(md, markdown('版スクロール'));
    await waitH1('版スクロール');
    await sleep(300);
    const scrollY = await content.eval('window.scrollY');
    check('更新で、スクロール位置が保たれる', scrollY === 1000, `scrollY=${scrollY}`);

    // 3. 原子的な保存
    const tmp = `${md}.tmp`;
    fs.writeFileSync(tmp, markdown('版原子的'));
    fs.renameSync(tmp, md);
    check('エディタの原子的な保存（名前の付け替え）で更新される', (await waitH1('版原子的')) !== null);
    await sleep(400);

    // 4. 参照する画像の変更
    const before = await content.eval('performance.timeOrigin');
    fs.writeFileSync(path.join(dir, 'pic.png'), png([30, 30, 200]));
    let after = before;
    for (let i = 0; i < 300 && after === before; i++) { await sleep(20); after = await content.eval('performance.timeOrigin'); }
    check('参照する画像の変更でも更新される', after !== before);
    await sleep(400);

    // 連続した保存は、まとめられる（途中の状態を変換しない）
    const origins = new Set();
    for (let i = 1; i <= 5; i++) { fs.writeFileSync(md, markdown(`版連続${i}`)); await sleep(20); }
    const settled = await waitH1('版連続5');
    for (let i = 0; i < 30; i++) { origins.add(await content.eval('performance.timeOrigin')); await sleep(20); }
    check('連続した保存（5回、20 ms間隔）が、最後の内容で表示される', settled !== null);
    await sleep(500);

    // 5. 失敗と回復
    fs.writeFileSync(md, markdown('版壊れ', { image: false, extra: '::: layout-right\n図の無いブロックは、エラーです。\n:::\n' }));
    const errored = await waitForStatus((s) => s.includes('失敗'));
    const banner = await chrome.eval("document.getElementById('banner').hidden === false ? document.getElementById('banner-text').textContent : ''");
    check('変換に失敗しても、直前の表示が残り、エラーが出る', errored && (await h1()) === '版連続5' && banner.includes('変換エラー'));
    fs.writeFileSync(md, markdown('版回復'));
    const recovered = (await waitH1('版回復')) !== null;
    // 帯は、内容の更新のあとに、ツールバー側の状態として更新される。少し待つ
    let bannerHidden = false;
    for (let i = 0; i < 50 && !bannerHidden; i++) { bannerHidden = (await chrome.eval("document.getElementById('banner').hidden")) === true; if (!bannerHidden) await sleep(20); }
    check('直して保存すると、自動で回復する（内容の更新と、エラーの帯が消える）', recovered && bannerHidden);
    await sleep(400);

    // 6. 自動更新を切る
    await chrome.eval("document.getElementById('auto-reload').click()");
    await sleep(200);
    fs.writeFileSync(md, markdown('版切'));
    await sleep(1500);
    check('自動更新を切ると、保存しても更新されない', (await h1()) === '版回復');
    await chrome.eval("document.getElementById('auto-reload').click()");
    fs.writeFileSync(md, markdown('版再開'));
    check('自動更新を入れ直すと、次の保存から更新される', (await waitH1('版再開')) !== null);

    content.close();
    chrome.close();
  } catch (error) {
    console.error('FAILED', error);
    results.push(false);
  } finally {
    proc.kill();
    if (process.platform === 'win32') spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    // Electronの終了は非同期で、ユーザーデータのファイルが、しばらく使用中になる。後始末の失敗は、結果に影響させない
    try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(results.every(Boolean) ? '\nすべて成功' : '\n失敗あり');
  process.exit(results.every(Boolean) ? 0 : 1);
})();
