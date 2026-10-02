'use strict';
// Electronを使わず、偽のウィンドウで、WaveDromHostの動作（遅延・1回だけの準備・読み込み順・直列・エラーの整形・片付け）を確認する（#392）。

const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { WaveDromHost } = require('../src/wavedrom-host');

const SCRIPT = '([spec]) => "<svg></svg>"';

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
          if (!code.startsWith('(([spec])')) return undefined;
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

const JS = { skin: '/cache/default.js', wavedrom: '/cache/wavedrom.min.js' };
const request = (spec = { signal: [{ name: 'a', wave: '01' }] }, js = JS) => ({ diagram_id: 'x', spec, script: SCRIPT, js });

describe('WaveDromHost', () => {
  test('no window is created until the first diagram, and the skin is loaded before wavedrom, once', async () => {
    const env = fakeEnvironment();
    const host = new WaveDromHost(env);
    assert.equal(env.windows.length, 0);

    await host.render(request());
    await host.render(request({ signal: [{ name: 'b', wave: '10' }] }));
    assert.equal(env.windows.length, 1);
    assert.deepEqual(env.reads, ['/cache/default.js', '/cache/wavedrom.min.js']);
    assert.match(env.windows[0].loaded, /^data:text\/html/);
    assert.equal(env.scripts.filter((s) => s.startsWith('(() =>')).length, 2);   // 読み込み2回（スキン → wavedrom）
    assert.equal(env.scripts.filter((s) => s.startsWith('(([spec])')).length, 2);   // 描画2回
  });

  test('the script from the worker is called with [spec] as JSON, so the spec cannot break out of it', async () => {
    const env = fakeEnvironment();
    const host = new WaveDromHost(env);
    const spec = { head: { text: 'quote " and `tick` and ${x} </script>' } };
    await host.render(request(spec));
    const call = env.scripts.find((s) => s.startsWith('(([spec])'));
    assert.equal(call, `(${SCRIPT})(${JSON.stringify([spec])})`);
  });

  test('diagrams are rendered one at a time', async () => {
    const env = fakeEnvironment();
    const host = new WaveDromHost(env);
    await Promise.all([1, 2, 3, 4].map((n) => host.render(request({ signal: [{ name: 'a', wave: '01' }], n }))));
    assert.equal(env.maxInFlight, 1);
  });

  test('a render error becomes a plain message without the internal stack, and keeps the window', async () => {
    const env = fakeEnvironment(() => {
      throw new Error("Error invoking remote method 'ELECTRON_BROWSER_EXECUTE_JAVASCRIPT': Error: WaveDrom could not draw this spec.\n    at blocked (<anonymous>:1:1)");
    });
    const host = new WaveDromHost(env);
    await assert.rejects(host.render(request()), (error) => {
      assert.equal(error.message, 'WaveDrom could not draw this spec.');
      return true;
    });
    assert.equal(env.windows.length, 1);
  });

  test('something that is not an SVG is an error', async () => {
    const host = new WaveDromHost(fakeEnvironment(() => 'not an svg'));
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
    const host = new WaveDromHost(env);
    await assert.rejects(host.render(request()), /load failed/);
    assert.equal(env.windows[0].destroyed, true);
    assert.match(await host.render(request()), /<svg/);
    assert.equal(env.windows.length, 2);
  });

  test('different js paths reload the page; dispose destroys the window and is safe to repeat', async () => {
    const env = fakeEnvironment();
    const host = new WaveDromHost(env);
    await host.render(request());
    await host.render(request({ signal: [{ name: 'a', wave: '01' }] }, { skin: '/other/default.js', wavedrom: '/other/wavedrom.min.js' }));
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
    const host = new WaveDromHost(env);
    await host.render(request());
    env.windows[0].destroyed = true;
    await host.render(request());
    assert.equal(env.windows.length, 2);
  });
});
