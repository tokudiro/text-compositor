'use strict';
// check-a11y.jsから呼ばれる（Electronの本体として実行する）。変換済みのHTMLを、非表示のウィンドウで開き、axe-coreで調べて、
// 違反をJSONで、標準出力へ出す（#340）。内容のビューは、DevTools Protocolから直接は調べられないため、同じHTMLを、別のウィンドウで調べる。
//   electron scripts/a11y-content.js <HTMLの絶対パス> [dark]    （darkで、ダークの配色を調べる）
const { app, BrowserWindow, nativeTheme } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

app.whenReady().then(async () => {
  if (process.argv[3] === 'dark') nativeTheme.themeSource = 'dark';
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } });
  // 変換済みのHTMLは、CSPで、スクリプトを禁じている。調べるための複製だけ、CSPを外す（同じフォルダに置き、相対パスの画像を保つ）
  const original = path.resolve(process.argv[2]);
  const copy = path.join(path.dirname(original), 'a11y-audit.html');
  fs.writeFileSync(copy, fs.readFileSync(original, 'utf8').replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, ''));
  await win.loadFile(copy);
  // axeは、scriptの要素として、読み込む（ホストの描画ウィンドウと同じ方法）。executeJavaScriptの同期の例外は、メッセージが捨てられるため、使わない
  await win.webContents.executeJavaScript(
    `(() => { const s = document.createElement('script'); s.textContent = ${JSON.stringify(axeSource)}; document.head.appendChild(s); })()`);
  const violations = await win.webContents.executeJavaScript(`axe.run(document, { resultTypes: ['violations'] }).then((r) => r.violations.map((v) => ({
    id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split(String.fromCharCode(10)).slice(0, 2).join(' / ')) })))`);
  process.stdout.write('A11Y_RESULT' + JSON.stringify(violations));
  fs.rmSync(copy, { force: true });
  app.quit();
}).catch((error) => { console.error(error); app.exit(1); });
