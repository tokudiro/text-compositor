'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { after, describe, test } = require('node:test');

const { WorkerClient, WorkerError, WorkerProtocolError } = require('../src/worker-client');

const FAKE = path.join(__dirname, 'fixtures', 'fake-worker.js');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-test-'));
const clients = [];

after(async () => {
  await Promise.all(clients.map((c) => c.dispose()));
  fs.rmSync(dir, { recursive: true, force: true });
});

/** 偽のワーカーを起動するクライアント。modeごとに、別のマーカーファイルを使う。 */
function create(mode, options = {}) {
  const marker = path.join(dir, `marker-${mode}-${clients.length}`);
  const client = new WorkerClient({ file: process.execPath, args: [FAKE, mode, marker] },
    { startTimeoutMs: 20_000, requestTimeoutMs: 20_000, ...options });
  clients.push(client);
  return client;
}

describe('WorkerClient', () => {
  test('render_html round trip returns html, diagnostics and timings', async () => {
    const client = create('ok');
    const result = await client.renderHtml({ path: 'a.md' });
    assert.equal(result.ok, true);
    assert.equal(result.html, 'a.md.html');
    assert.deepEqual(result.diagnostics.map((d) => [d.severity, d.line]), [['warning', 7]]);
    assert.equal(result.timings_ms.total, 1.5);
    assert.deepEqual(result.dependencies, ['a.md.png']);
    assert.equal(await client.ping(), true);
  });

  test('warmUp starts the worker once and later requests reuse it', async () => {
    const client = create('ok');
    await client.warmUp();
    await client.renderHtml({ path: 'x.md' });
    await client.renderHtml({ path: 'y.md' });
    assert.equal(client.startCount, 1);
    assert.equal(client.isRunning, true);
  });

  test('lines that are not protocol messages are ignored', async () => {
    const client = create('garbage');
    const result = await client.renderHtml({ path: 'x.md' });
    assert.equal(result.ok, true);
  });

  test('concurrent requests are serialized and answered in order', async () => {
    const client = create('slow');
    const results = await Promise.all([0, 1, 2, 3, 4].map((i) => client.renderHtml({ path: `doc${i}.md` })));
    assert.deepEqual(results.map((r) => r.html), [0, 1, 2, 3, 4].map((i) => `doc${i}.md.html`));
  });

  test('a crash fails the request with the stderr tail, and the next request restarts the worker', async () => {
    const client = create('crash-once');
    await assert.rejects(client.renderHtml({ path: 'x.md' }), (error) => {
      assert.ok(error instanceof WorkerError);
      assert.match(error.message, /boom: fake crash/);
      assert.match(error.message, /終了コード 3/);
      return true;
    });
    const result = await client.renderHtml({ path: 'x.md' });
    assert.equal(result.ok, true);
    assert.equal(client.startCount, 2);
  });

  test('a timeout kills the worker and the next request restarts it', async () => {
    const client = create('hang-once', { requestTimeoutMs: 1500 });
    await assert.rejects(client.renderHtml({ path: 'x.md' }), /応答しませんでした/);
    const result = await client.renderHtml({ path: 'x.md' });
    assert.equal(result.ok, true);
    assert.equal(client.startCount, 2);
  });

  test('a protocol error is reported with its code', async () => {
    const client = create('protocol-error');
    await assert.rejects(client.renderHtml({ path: 'x.md' }), (error) => {
      assert.ok(error instanceof WorkerProtocolError);
      assert.equal(error.code, 'bad_request');
      assert.match(error.message, /nope/);
      return true;
    });
  });

  test('a worker that never becomes ready times out', async () => {
    const client = create('no-ready', { startTimeoutMs: 800 });
    await assert.rejects(client.warmUp(), /準備できませんでした/);
  });

  test('a missing executable is a worker error, not a crash of the app', async () => {
    const client = new WorkerClient({ file: path.join(dir, 'no-such-python'), args: [] });
    clients.push(client);
    await assert.rejects(client.warmUp(), /起動できませんでした/);
  });

  test('dispose asks the worker to shut down and later requests fail', async () => {
    const client = create('ok');
    await client.warmUp();
    await client.dispose();
    assert.equal(client.isRunning, false);
    await assert.rejects(client.renderHtml({ path: 'x.md' }), WorkerError);
  });
});

describe('WorkerClient documents and events (#284)', () => {
  test('open returns the same shape as renderHtml', async () => {
    const client = create('watch');
    const result = await client.open({ doc: '1', path: 'a.md' });
    assert.deepEqual(result, { ok: true, html: 'a.md.html', diagnostics: [], timings_ms: {}, dependencies: [] });
  });

  test('rendered events after an open are handed to onEvent, not dropped', async () => {
    const events = [];
    const client = create('watch', { onEvent: (event) => events.push(event) });
    await client.open({ doc: '7', path: 'a.md', notify: true });
    await client.ping().catch(() => {});   // 応答の後に届いた通知を、取りこぼしていないことを確かめるための往復
    assert.deepEqual(events.map((e) => [e.event, e.doc, e.path, e.html]), [['rendered', '7', 'a.md', 'a.md.again.html']]);
  });

  test('watch sends the name and files, and a changed event comes back', async () => {
    const events = [];
    const client = create('watch', { onEvent: (event) => events.push(event) });
    await client.watch('project', ['C:/docs/config.yaml']);
    await client.ping().catch(() => {});
    assert.deepEqual(events, [{ event: 'changed', name: 'project', paths: ['C:/docs/config.yaml'] }]);
  });

  test('closeDoc and setAutoReload resolve when the worker accepts them', async () => {
    const client = create('watch');
    await client.closeDoc('1');
    await client.setAutoReload(true);
  });

  test('a protocol error from setAutoReload and a throwing onEvent do not break the connection', async () => {
    const client = create('watch', { onEvent: () => { throw new Error('handler bug'); } });
    await client.watch('p', ['x']);   // changedが届き、onEventが例外を投げる
    await client.open({ doc: '1', path: 'a.md' });   // 通信は、続いている
    await assert.rejects(client._expectOk('set_auto_reload', { value: 'yes' }), (error) => error instanceof WorkerProtocolError && error.code === 'bad_request');
  });

  test('onExit is called when a ready worker dies on its own, but not after dispose or when it never became ready', async () => {
    const exits = [];
    const crashing = create('crash-once', { onExit: (info) => exits.push(info.code) });
    await assert.rejects(crashing.renderHtml({ path: 'x.md' }));
    await new Promise((resolve) => setTimeout(resolve, 100));
    assert.deepEqual(exits, [3]);

    const never = create('no-ready', { startTimeoutMs: 500, onExit: (info) => exits.push(info.code) });
    await assert.rejects(never.warmUp());
    await new Promise((resolve) => setTimeout(resolve, 200));
    assert.deepEqual(exits, [3]);

    const disposed = create('watch', { onExit: (info) => exits.push(info.code) });
    await disposed.warmUp();
    await disposed.dispose();
    assert.deepEqual(exits, [3]);
  });

  test('onReady is called for every start, with restarted true after the first', async () => {
    const calls = [];
    const client = create('crash-once', { onReady: (info) => calls.push(info) });
    await assert.rejects(client.renderHtml({ path: 'x.md' }));   // 1回目: 起動して、クラッシュ
    await client.renderHtml({ path: 'x.md' });   // 起動し直す
    assert.deepEqual(calls, [{ restarted: false }, { restarted: true }]);
  });
});

describe('WorkerClient services (render_mermaid, #207)', () => {
  const reply = (result) => JSON.parse(result.diagnostics[0].message);

  test('a callback from the worker is served and the svg goes back', async () => {
    const calls = [];
    const client = create('mermaid', {
      services: { render_mermaid: async (payload) => { calls.push(payload); return '<svg>ok</svg>'; } },
    });
    const result = await client.renderHtml({ path: 'a.md' });
    assert.deepEqual(calls, [{ diagram_id: 'mermaid-x', code: 'graph TD\n  A --> B', js: '/cache/mermaid.min.js' }]);
    assert.deepEqual(reply(result), { callback: 41, ok: true, svg: '<svg>ok</svg>' });
    assert.equal(result.ok, true);
  });

  test('a failing service is reported to the worker as ok: false with its message', async () => {
    const client = create('mermaid', { services: { render_mermaid: async () => { throw new Error('Parse error on line 3'); } } });
    const result = await client.renderHtml({ path: 'a.md' });
    assert.deepEqual(reply(result), { callback: 41, ok: false, error: 'Parse error on line 3' });
  });

  test('an event without a service is answered with an error, so the worker does not wait forever', async () => {
    const client = create('mermaid');
    const result = await client.renderHtml({ path: 'a.md' });
    assert.equal(reply(result).ok, false);
    assert.match(reply(result).error, /未対応の依頼です: render_mermaid/);
    const other = await create('mermaid', { services: { render_mermaid: async () => 'x' } }).renderHtml({ path: 'b.md', event: 'unknown_event' });
    assert.match(reply(other).error, /未対応の依頼です: unknown_event/);
  });

  test('the worker keeps working after a callback (the queue is not blocked)', async () => {
    const client = create('mermaid', { services: { render_mermaid: async () => '<svg/>' } });
    await client.renderHtml({ path: 'a.md' });
    const second = await client.renderHtml({ path: 'b.md' });
    assert.equal(second.html, 'b.md.html');
  });
});