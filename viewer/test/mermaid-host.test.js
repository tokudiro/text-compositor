'use strict';
// Electronを使わず、偽のウィンドウで、MermaidHostの動作（遅延・1回だけの準備・直列・エラーの整形・片付け）を確認する（#207）。

const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { MermaidHost, cleanMessage } = require('../src/mermaid-host');

/** 偽のウィンドウ。executeJavaScriptに渡されたコードを記録し、`respond`が結果（または例外）を決める。 */
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
          if (!code.startsWith('mermaid.render(')) return undefined;
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

const request = (code = 'graph TD\n  A --> B', js = '/cache/mermaid.min.js', id = 'mermaid-abc') => ({ diagram_id: id, code, js });

describe('MermaidHost', () => {
  test('no window is created until the first diagram, and it is prepared once', async () => {
    const env = fakeEnvironment();
    const host = new MermaidHost(env);
    assert.equal(env.windows.length, 0);

    await host.render(request());
    await host.render(request('graph LR\n  X --> Y', '/cache/mermaid.min.js', 'mermaid-def'));
    assert.equal(env.windows.length, 1);
    assert.deepEqual(env.reads, ['/cache/mermaid.min.js']);
    assert.match(env.windows[0].loaded, /^data:text\/html/);
    // mermaid.min.jsの読み込み → 初期化 → 描画2回
    assert.equal(env.scripts.filter((s) => s.includes('mermaid.initialize')).length, 1);
    assert.match(env.scripts.find((s) => s.includes('mermaid.initialize')), /htmlLabels: false, flowchart: \{ htmlLabels: false \}/);
    assert.equal(env.scripts.filter((s) => s.startsWith('mermaid.render(')).length, 2);
  });

  test('the diagram id and code are passed as JSON strings, so they cannot break out of the script', async () => {
    const env = fakeEnvironment();
    const host = new MermaidHost(env);
    const code = 'graph TD\n  A["quote \\" and `tick` and ${x}"] --> B\n</script>';
    await host.render(request(code, '/cache/mermaid.min.js', 'id"with\'quotes'));
    const call = env.scripts.find((s) => s.startsWith('mermaid.render('));
    assert.equal(call, `mermaid.render(${JSON.stringify('id"with\'quotes')}, ${JSON.stringify(code)}).then((result) => result.svg)`);
  });

  test('diagrams are rendered one at a time', async () => {
    const env = fakeEnvironment();
    const host = new MermaidHost(env);
    await Promise.all([1, 2, 3, 4].map((n) => host.render(request(`graph TD\n  A${n} --> B`, '/cache/mermaid.min.js', `mermaid-${n}`))));
    assert.equal(env.maxInFlight, 1);
  });

  test('a render error becomes a plain message without the internal stack', async () => {
    const env = fakeEnvironment(() => {
      throw new Error("Error invoking remote method 'ELECTRON_BROWSER_EXECUTE_JAVASCRIPT': Error: Parse error on line 3:\n  A --> \n----^\n    at Parser.parse (<anonymous>:1:1)");
    });
    const host = new MermaidHost(env);
    await assert.rejects(host.render(request()), (error) => {
      assert.equal(error.message, 'Parse error on line 3:\n  A --> \n----^');
      return true;
    });
    // 図のエラーでは、ウィンドウを作り直さない（次の図も、同じウィンドウで描画する）
    assert.equal(env.windows.length, 1);
  });

  test('something that is not an SVG is an error', async () => {
    const host = new MermaidHost(fakeEnvironment(() => 'not an svg'));
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
    const host = new MermaidHost(env);
    await assert.rejects(host.render(request()), /load failed/);
    assert.equal(env.windows[0].destroyed, true);
    assert.match(await host.render(request()), /<svg/);
    assert.equal(env.windows.length, 2);
  });

  test('a different mermaid.min.js path reloads the page; dispose destroys the window', async () => {
    const env = fakeEnvironment();
    const host = new MermaidHost(env);
    await host.render(request());
    await host.render(request('graph TD\n  A --> B', '/other/mermaid.min.js'));
    assert.equal(env.windows.length, 2);
    assert.equal(env.windows[0].destroyed, true);
    host.dispose();
    assert.equal(env.windows[1].destroyed, true);
    host.dispose();   // 2回呼んでも、安全
    assert.equal(env.destroyed, 2);
    // 片付けた後も、次の依頼で、作り直せる
    await host.render(request());
    assert.equal(env.windows.length, 3);
  });

  test('a window destroyed from outside is recreated', async () => {
    const env = fakeEnvironment();
    const host = new MermaidHost(env);
    await host.render(request());
    env.windows[0].destroyed = true;
    await host.render(request());
    assert.equal(env.windows.length, 2);
  });
});

describe('cleanMessage', () => {
  test('removes the remote-call wrapper, the error class and the stack lines', () => {
    assert.equal(cleanMessage(new Error("Error invoking remote method 'x': Error: boom\n    at a (b)")), 'boom');
    assert.equal(cleanMessage('plain'), 'plain');
    assert.equal(cleanMessage(undefined), 'undefined');
  });
});
