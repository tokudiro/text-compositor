'use strict';
// 実際のPythonワーカー（`python -m text_compositor.worker`）と、Node側のクライアント（WorkerClient）の結合の確認（#172）。
//
// worker-client.test.jsは、偽のワーカーで、クライアントの動き（異常終了・時間切れ・再起動）を確認する。Python側は、
// tests/test_worker.pyが、プロトコルを確認する。どちらも、相手を偽物にしているため、両方が本物のときに、つながることは、
// ここで確認する。図表の描画（Mermaid・PlantUML・D2）は、外部のツールや、ダウンロードが要るため、対象にしない。
//
// 実行には、markdown-it-pyなどが入ったPythonと、text_compositorが要る。無い環境（開発中の、Pythonの準備がない状態）では、
// 飛ばす。CIでは、環境変数 REQUIRE_WORKER_INTEGRATION=1 を付けて、飛ばさず、失敗にする（準備の不備を見逃さないため）。

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { after, before, describe, test } = require('node:test');

const { PYTHONPATH_ENV, PythonNotFoundError, resolveWorkerLaunch } = require('../src/python');
const { WorkerClient } = require('../src/worker-client');

const repoDir = path.resolve(__dirname, '..', '..');
const required = process.env.REQUIRE_WORKER_INTEGRATION === '1';

// 1x1の透明なPNG（画像の参照を、依存ファイルとして返すことの確認用）
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');

/** 実際のワーカーを起動できるか。できないときは、その理由を返す。 */
function prepare() {
  let launch;
  try {
    const env = { ...process.env, [PYTHONPATH_ENV]: process.env[PYTHONPATH_ENV] || repoDir };
    launch = resolveWorkerLaunch(path.join(repoDir, 'viewer'), { env });
  } catch (error) {
    if (error instanceof PythonNotFoundError) return { reason: error.message };
    throw error;
  }
  const probe = spawnSync(launch.file, ['-c', 'import markdown_it, mdit_py_plugins, yaml, platformdirs, text_compositor.worker'], {
    env: { ...process.env, ...launch.env },
    encoding: 'utf8',
    timeout: 60_000,
  });
  if (probe.status !== 0) {
    return { reason: `Pythonで、text_compositorと依存パッケージを読み込めません: ${(probe.stderr || probe.error?.message || '').trim().split('\n').pop()}` };
  }
  return { launch };
}

const prepared = prepare();
if (prepared.reason && required) {
  // 飛ばさず、失敗にする（CIで、準備の不備を見逃さない）
  test('the real worker can be started (REQUIRE_WORKER_INTEGRATION=1)', () => assert.fail(prepared.reason));
}

describe('real worker + WorkerClient (#172)', { skip: prepared.reason ? `${prepared.reason}（飛ばします）` : false }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-integration-'));
  let client;

  // 外部の描画ツール（ブラウザ・Java・D2）は、使わない
  const PLAIN = { mermaid: false, plantuml: false, d2: false };

  /** `html`は、HTMLの文字列ではなく、書き出したHTMLファイルのパス（Viewerは、これを読み込んで表示する）。 */
  const htmlOf = (result) => {
    assert.equal(typeof result.html, 'string');
    assert.ok(path.isAbsolute(result.html) && fs.existsSync(result.html), `html file: ${result.html}`);
    return fs.readFileSync(result.html, 'utf8');
  };

  before(async () => {
    client = new WorkerClient(prepared.launch, { startTimeoutMs: 60_000, requestTimeoutMs: 120_000 });
    await client.warmUp();
  });

  after(async () => {
    await client?.dispose();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test('a Markdown file becomes HTML, and its local image is reported as a dependency', async () => {
    fs.writeFileSync(path.join(dir, 'pic.png'), PNG);
    const file = path.join(dir, 'doc.md');
    fs.writeFileSync(file, '# 結合テスト\n\n本文です。\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n![pic](pic.png)\n', 'utf8');

    const result = await client.renderHtml({ path: file, plugins: PLAIN });

    assert.equal(result.ok, true, JSON.stringify(result.diagnostics));
    const html = htmlOf(result);
    assert.match(html, /<h1[^>]*>結合テスト<\/h1>/);
    assert.match(html, /<table/);
    assert.match(html, /<img[^>]+pic\.png/);
    assert.deepEqual(result.diagnostics.filter((d) => d.severity === 'error'), []);
    assert.ok(result.dependencies.some((d) => path.basename(d) === 'pic.png'), `dependencies: ${JSON.stringify(result.dependencies)}`);
    assert.equal(typeof result.timings_ms.total, 'number');
  });

  test('csv_header decides whether the first row of a CSV is a header (the option the viewer sends, #220)', async () => {
    const file = path.join(dir, 'data.csv');
    fs.writeFileSync(file, 'name,qty\nAlice,3\n', 'utf8');

    // 同じフォルダの同じファイル名（preview.html）に書くため、変換のたびに、すぐ読む（次の変換が、上書きする）
    const withHeader = await client.renderHtml({ path: file, plugins: PLAIN, csv_header: true });
    assert.equal(withHeader.ok, true);
    assert.match(htmlOf(withHeader), /<th/);

    const withoutHeader = await client.renderHtml({ path: file, plugins: PLAIN, csv_header: false });
    assert.equal(withoutHeader.ok, true);
    const html = htmlOf(withoutHeader);
    assert.doesNotMatch(html, /<th/);
    assert.match(html, /Alice/);
  });

  test('a file that does not exist fails as a result, not as a crash, and the worker keeps working', async () => {
    const result = await client.renderHtml({ path: path.join(dir, 'missing.md'), plugins: PLAIN });

    assert.equal(result.ok, false);
    assert.equal(result.html, null);
    assert.ok(result.diagnostics.some((d) => d.severity === 'error'), JSON.stringify(result.diagnostics));
    assert.equal(await client.ping(), true);
    assert.equal(client.startCount, 1);   // 再起動していない
  });

  test('the same worker keeps serving after several requests (it is resident)', async () => {
    const file = path.join(dir, 'again.md');
    fs.writeFileSync(file, '# もう一度\n', 'utf8');
    for (let i = 0; i < 3; i += 1) {
      const result = await client.renderHtml({ path: file, plugins: PLAIN });
      assert.equal(result.ok, true);
    }
    assert.equal(client.startCount, 1);
  });
});
