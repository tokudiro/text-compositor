// ElectronでHTMLを表示するだけの、計測用の最小アプリ（#180）。
//   electron <このフォルダ> <html> [--user-data <dir>]
// 標準出力へ、"loaded"・"reloaded"を出す（他の候補と同じ）。
// 再読み込みは、ファイルの変更を検知して行う（実際のViewerと同じ流れ。標準入力の合図は使わない）。
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const userDataIndex = process.argv.indexOf('--user-data');
if (userDataIndex >= 0) app.setPath('userData', process.argv[userDataIndex + 1]);
const deferShow = process.argv.includes('--defer-show');   // 内容が描かれるまで、ウィンドウを表示しない
const html = path.resolve(process.argv.slice(2).find((a) => /\.html?$/i.test(a)));

function say(line) { process.stdout.write(line + '\n'); }

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1000, height: 800, x: 40, y: 40, show: !deferShow, backgroundColor: '#ffffff',
    webPreferences: { javascript: false, sandbox: true },   // 静的なHTMLだけなので、JavaScriptは要らない
  });
  let loadedOnce = false;
  win.webContents.on('did-finish-load', () => { say(loadedOnce ? 'reloaded' : 'loaded'); loadedOnce = true; });
  if (deferShow) win.once('ready-to-show', () => win.show());
  win.loadFile(html);

  let timer = null;
  fs.watch(html, () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (!win.isDestroyed()) win.webContents.reload(); }, 10);   // 連続した変更をまとめる
  });
});

app.on('window-all-closed', () => app.quit());
