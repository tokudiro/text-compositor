'use strict';
// Electronを使わず、偽のウィンドウで、BytefieldHostの動作（遅延・1回だけの準備・読み込み順・直列・エラーの整形・片付け）を確認する（#300）。

const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { BytefieldHost } = require('../src/bytefield-host');

const SCRIPT = '([source]) => "<svg></svg>"';

/** 偽のウィンドウ。executeJavaScriptに渡されたコードを記録し、`respond`が、描画の結果（または例外）を決める。 */
function fakeEnvironment(respond = () => '<svg id="x"></svg>') {
  const env = { windows: [], scripts: [], destroyed: 0, reads: [], inFlight: 0, maxInFlight: 0 };
  env.createWindow = () => {
    const window = {
      loaded: null,
      destroyed: false,
      async loadURL(url) { window.loaded = url; },
      isDestroyed: () => window.destroyed,
      destroy() { window.destroyed = true; env.destroyed += 1; },
      webContents: {
        async executeJavaScript(code) {
          env.scripts.push(code);
          if (!code.startsWith('(([source])')) return undefined;
          env.inFlight += 1;
          env.maxInFlight = Math.max(env.maxInFlight, env.inFlight);
          await new Promise((resolve) => setTimeout(resolve, 5));
          env.inFlight -= 1;
          return respond(code);
        },
      },
    };
    env.windows.push(window);
    return window;
  };
  env.readFile = (p) => { env.reads.push(p); return `/* ${p} */`; };
  return env;
}

const JS = { bytefield: '/cache/lib.js' };
const request = (source = '(draw-box "A" {:span 8})', js = JS) => ({ diagram_id: 'x', source, script: SCRIPT, js });

describe('BytefieldHost', () => {
  test('no window is created until the first diagram, and lib.js is loaded once', async () => {
    const env = fakeEnvironment();
    const host = new BytefieldHost(env);
    assert.equal(env.windows.length, 0);

    await host.render(request());
    await host.render(request('(draw-box "B" {:span 8})'));
    assert.equal(env.windows.length, 1);
    assert.deepEqual(env.reads, ['/cache/lib.js']);
    assert.match(env.windows[0].loaded, /^data:text\/html/);
    assert.equal(env.scripts.filter((s) => s.startsWith('(() =>')).length, 1);   // 読み込み1回（lib.js）
    assert.equal(env.scripts.filter((s) => s.startsWith('(([source])')).length, 2);   // 描画2回
  });

  test('the script from the worker is called with [source] as JSON, so the source cannot break out of it', async () => {
    const env = fakeEnvironment();
    const host = new BytefieldHost(env);
    const spec = '(draw-box "quote \\" and `tick` and ${x} </script>" {:span 8})';
    await host.render(request(spec));
    const call = env.scripts.find((s) => s.startsWith('(([source])'));
    assert.equal(call, `(${SCRIPT})(${JSON.stringify([spec])})`);
  });

  test('diagrams are rendered one at a time', async () => {
    const env = fakeEnvironment();
    const host = new BytefieldHost(env);
    await Promise.all([1, 2, 3, 4].map((n) => host.render(request(`(draw-box "A${n}" {:span 8})`))));
    assert.equal(env.maxInFlight, 1);
  });

  test('a render error becomes a plain message without the internal stack, and keeps the window', async () => {
    const env = fakeEnvironment(() => {
      throw new Error("Error invoking remote method 'ELECTRON_BROWSER_EXECUTE_JAVASCRIPT': Error: draw-box called with span larger than remaining columns in row [at line 1, column 1].\n    at blocked (<anonymous>:1:1)");
    });
    const host = new BytefieldHost(env);
    await assert.rejects(host.render(request()), (error) => {
      assert.equal(error.message, 'draw-box called with span larger than remaining columns in row [at line 1, column 1].');
      return true;
    });
    assert.equal(env.windows.length, 1);
  });

  test('something that is not an SVG is an error', async () => {
    const host = new BytefieldHost(fakeEnvironment(() => 'not an svg'));
    await assert.rejects(host.render(request()), /SVG/);
  });

  test('a failure while preparing is retried on the next request with a new window', async () => {
    const env = fakeEnvironment();
    let failures = 1;
    const createWindow = env.createWindow;
    env.createWindow = () => {
      const window = createWindow();
      if (failures > 0) { failures -= 1; window.loadURL = async () => { throw new Error('load failed'); }; }
      return window;
    };
    const host = new BytefieldHost(env);
    await assert.rejects(host.render(request()), /load failed/);
    assert.equal(env.windows[0].destroyed, true);
    assert.match(await host.render(request()), /<svg/);
    assert.equal(env.windows.length, 2);
  });

  test('different js paths reload the page; dispose destroys the window and is safe to repeat', async () => {
    const env = fakeEnvironment();
    const host = new BytefieldHost(env);
    await host.render(request());
    await host.render(request('(draw-box "A" {:span 8})', { bytefield: '/other/lib.js' }));
    assert.equal(env.windows.length, 2);
    assert.equal(env.windows[0].destroyed, true);
    host.dispose();
    host.dispose();
    assert.equal(env.destroyed, 2);
    await host.render(request());
    assert.equal(env.windows.length, 3);
  });

  test('a window destroyed from outside is recreated', async () => {
    const env = fakeEnvironment();
    const host = new BytefieldHost(env);
    await host.render(request());
    env.windows[0].destroyed = true;
    await host.render(request());
    assert.equal(env.windows.length, 2);
  });
});
