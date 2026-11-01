'use strict';
// プロトコル1だけを話す、偽のワーカー（テスト用。#190）。
//   node fake-worker.js <mode> <marker>
// mode: ok | garbage | crash-once | hang-once | protocol-error | no-ready | slow | mermaid
// mermaid: render_htmlの処理中に、呼び出し元へ描画を依頼し（render_mermaid）、その応答を、診断のメッセージにして返す（#207）。
// crash-once・hang-onceは、マーカーファイルが無いときだけ発動し、発動したらマーカーを作る（起動し直した後は、正常に動く）。
const fs = require('node:fs');
const readline = require('node:readline');

const [mode, marker] = process.argv.slice(2);
const say = (object) => process.stdout.write(`${JSON.stringify(object)}\n`);

if (mode === 'no-ready') {
  setInterval(() => {}, 1000);
} else {
  say({ event: 'ready', protocol: 1, version: 'fake' });
  let waiting = null;
  const held = [];
  readline.createInterface({ input: process.stdin }).on('line', (line) => {
    const request = JSON.parse(line);
    if (request.callback !== undefined) {   // 呼び出し元からの、描画の応答
      if (waiting && request.callback === waiting.callback) { const done = waiting; waiting = null; done.finish(request); }
      return;
    }
    if (request.method === 'shutdown') process.exit(0);
    if (mode === 'mermaid' && request.method === 'render_html') {
      const callback = 41;
      const event = request.params.event ?? 'render_mermaid';
      say({ event, callback, diagram_id: 'mermaid-x', code: 'graph TD\n  A --> B', js: '/cache/mermaid.min.js' });
      waiting = {
        callback,
        finish: (reply) => say({
          id: request.id, ok: true, html: `${request.params.path}.html`,
          diagnostics: [{ severity: 'info', message: JSON.stringify(reply), file: null, line: null, detail: null }],
          timings_ms: {}, dependencies: [],
        }),
      };
      return;
    }

    // #284: 2つ目の`open`が届くまで、1つ目に答えない。届いたら、1つ目は`superseded`、2つ目は成功で答える
    // （クライアントが、前の応答を待たずに、`open`を送ることの確認用）。
    if (mode === 'open-pair' && request.method === 'open') {
      held.push(request);
      if (held.length === 2) {
        const [older, newer] = held.splice(0);
        say({ id: older.id, ok: false, error: { code: 'superseded', message: 'newer open' } });
        say({ id: newer.id, ok: true, html: `${newer.params.path}.html`, diagnostics: [], timings_ms: {}, dependencies: [] });
      }
      return;
    }
    // #284: open・close_doc・watch・set_auto_reloadと、変更の通知（rendered・changed）。
    // `open`は、応答のあとに`rendered`を1つ出す（params.notifyが真のとき）。`watch`は、`changed`を1つ出す。
    if (mode === 'watch') {
      if (request.method === 'open') {
        const p = request.params.path;
        say({ id: request.id, ok: true, html: `${p}.html`, diagnostics: [], timings_ms: {}, dependencies: [] });
        if (request.params.notify) say({ event: 'rendered', doc: request.params.doc, path: p, ok: true, html: `${p}.again.html`, diagnostics: [], timings_ms: {}, dependencies: [] });
      } else if (request.method === 'watch') {
        say({ id: request.id, ok: true, result: {} });
        if (request.params.files.length > 0) say({ event: 'changed', name: request.params.name, paths: request.params.files });
      } else if (request.method === 'set_auto_reload' && typeof request.params.value !== 'boolean') {
        say({ id: request.id, ok: false, error: { code: 'bad_request', message: 'value' } });
      } else {
        say({ id: request.id, ok: true, result: { method: request.method, params: request.params } });
      }
      return;
    }

    const first = !fs.existsSync(marker);
    if (request.method === 'render_html' && mode === 'crash-once' && first) {
      fs.writeFileSync(marker, '');
      process.stderr.write('boom: fake crash\n');
      process.exit(3);
    }
    if (request.method === 'render_html' && mode === 'hang-once' && first) {
      fs.writeFileSync(marker, '');
      return; // 応答しない
    }
    if (mode === 'protocol-error') {
      say({ id: request.id, ok: false, error: { code: 'bad_request', message: 'nope' } });
      return;
    }
    if (mode === 'garbage') {
      process.stdout.write('this is not json\n');
      process.stdout.write('[1, 2, 3]\n');
    }
    const respond = () => {
      if (request.method === 'ping') {
        say({ id: request.id, ok: true, result: { pong: true } });
      } else {
        const p = request.params.path;
        say({
          id: request.id, ok: true, html: `${p}.html`,
          diagnostics: [{ severity: 'warning', message: 'w', file: p, line: 7, detail: null }],
          timings_ms: { total: 1.5 },
          dependencies: [`${p}.png`],
        });
      }
    };
    if (mode === 'slow') setTimeout(respond, 50); else respond();
  });
}
