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
