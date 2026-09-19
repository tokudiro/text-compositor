'use strict';
// Electronを使わず、偽のウィンドウで、GraphvizHostの動作（遅延・1回だけの準備・直列・エラーの整形・片付け）を確認する（#181）。
// ページの中で動く、文字幅の補正は、実際のChromiumが要るため、`scripts/check-open-files.js`（実機）で確かめる。

const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { GraphvizHost, BLANK_PAGE, INSTALL_SCRIPT } = require('../src/graphviz-host');

/** 偽のウィンドウ。executeJavaScriptに渡されたコードを記録し、`respond`が結果（または例外）を決める。 */
function fakeEnvironment(respond = () => ({ svg: '<svg id="x"></svg>' })) {
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
          if (!code.startsWith('window.__renderDot(')) return undefined;
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

const request = (code = 'digraph { a -> b }', js = '/cache/viz-global.js', id = 'graphviz-abc') => ({ diagram_id: id, code, js });

describe('GraphvizHost', () => {
  test('no window is created until the first diagram, and it is prepared once', async () => {
    const env = fakeEnvironment();
    const host = new GraphvizHost(env);
    assert.equal(env.windows.length, 0);

    await host.render(request());
    await host.render(request('digraph { x -> y }'));
    assert.equal(env.windows.length, 1);
    assert.deepEqual(env.reads, ['/cache/viz-global.js']);
    assert.match(env.windows[0].loaded, /^data:text\/html/);
    // viz-global.jsの読み込み → 描画関数の登録 → 描画2回
    assert.equal(env.scripts.filter((s) => s === INSTALL_SCRIPT).length, 1);
    assert.equal(env.scripts.filter((s) => s.startsWith('window.__renderDot(')).length, 2);
  });

  test('the blank page has a base URL, because viz-global.js builds URLs from document.baseURI', () => {
    // `data:`のページのままだと、`new URL(..., document.baseURI)`が失敗して、Viz.instance()が拒否される
    assert.match(decodeURIComponent(BLANK_PAGE), /<base href="file:\/\/\/[^"]*">/);
  });

  test('the installed script defines the renderer for the page (it must not use anything from this module)', () => {
    assert.match(INSTALL_SCRIPT, /^\(function installRenderer\(\)/);
    assert.match(INSTALL_SCRIPT, /window\.__renderDot = async/);
    // 別のスコープで組み立てて、構文として成り立つこと（ページに渡す文字列）
    assert.doesNotThrow(() => new Function(INSTALL_SCRIPT));
  });

  test('the code is passed as a JSON string, so it cannot break out of the script', async () => {
    const env = fakeEnvironment();
    const host = new GraphvizHost(env);
    const code = 'digraph { a [label="quote \\" and `tick` and ${x}"] }\n</script>';
    await host.render(request(code));
    const call = env.scripts.find((s) => s.startsWith('window.__renderDot('));
    assert.ok(call.startsWith(`window.__renderDot(${JSON.stringify(code)}, `));
  });

  test('diagrams are rendered one at a time', async () => {
    const env = fakeEnvironment();
    const host = new GraphvizHost(env);
    await Promise.all([1, 2, 3, 4].map((n) => host.render(request(`digraph { a${n} -> b }`, '/cache/viz-global.js', `graphviz-${n}`))));
    assert.equal(env.maxInFlight, 1);
  });

  test('a syntax error reported by the page is thrown with its own message', async () => {
    const env = fakeEnvironment(() => ({ error: "syntax error in line 1 near '}'" }));
    const host = new GraphvizHost(env);
    await assert.rejects(host.render(request()), (error) => {
      assert.equal(error.message, "syntax error in line 1 near '}'");
      return true;
    });
    // 図のエラーでは、ウィンドウを作り直さない（次の図も、同じウィンドウで描画する）
    assert.equal(env.windows.length, 1);
  });

  test('an exception from the window is cleaned of the internal wrapper and stack', async () => {
    const env = fakeEnvironment(() => {
      throw new Error("Error invoking remote method 'ELECTRON_BROWSER_EXECUTE_JAVASCRIPT': Error: boom\n    at x (<anonymous>:1:1)");
    });
    const host = new GraphvizHost(env);
    await assert.rejects(host.render(request()), (error) => {
      assert.equal(error.message, 'boom');
      return true;
    });
  });

  test('something that is not an SVG is an error', async () => {
    const host = new GraphvizHost(fakeEnvironment(() => ({ svg: 'not an svg' })));
    await assert.rejects(host.render(request()), /SVG/);
    const empty = new GraphvizHost(fakeEnvironment(() => undefined));
    await assert.rejects(empty.render(request()), /SVG/);
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
    const host = new GraphvizHost(env);
    await assert.rejects(host.render(request()), /load failed/);
    assert.equal(env.windows[0].destroyed, true);
    assert.match(await host.render(request()), /<svg/);
    assert.equal(env.windows.length, 2);
  });

  test('a different viz-global.js path reloads the page; dispose destroys the window', async () => {
    const env = fakeEnvironment();
    const host = new GraphvizHost(env);
    await host.render(request());
    await host.render(request('digraph { a -> b }', '/other/viz-global.js'));
    assert.equal(env.windows.length, 2);
    assert.equal(env.windows[0].destroyed, true);
    host.dispose();
    assert.equal(env.windows[1].destroyed, true);
    host.dispose();   // 2回呼んでも、安全
    assert.equal(env.destroyed, 2);
    await host.render(request());   // 片付けた後も、次の依頼で、作り直せる
    assert.equal(env.windows.length, 3);
  });

  test('a window destroyed from outside is recreated', async () => {
    const env = fakeEnvironment();
    const host = new GraphvizHost(env);
    await host.render(request());
    env.windows[0].destroyed = true;
    await host.render(request());
    assert.equal(env.windows.length, 2);
  });
});
