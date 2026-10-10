'use strict';
// 開発中のObunzuを、このリポジトリのPythonコード（text_compositor）で起動する。
//   npm run dev -- [--theme light|dark] [ファイルまたはフォルダ ...]
//
// TEXT_COMPOSITOR_PYTHONPATHを指定しないと、PATH上のPythonのsite-packagesにある古いtext_compositorが使われ、
// 「No module named text_compositor.worker」のワーカーエラーになる。それを避けるため、リポジトリのルートを自動で渡す。
// 環境変数が、すでに指定されているときは、それを尊重する。

const { spawn } = require('node:child_process');
const path = require('node:path');

const viewerDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(viewerDir, '..');
// `npm run`は、cwdをviewerにする。相対パスは、npmを実行した場所を基準に解釈する
const baseDir = process.env.INIT_CWD || process.cwd();

const env = { ...process.env };
env.TEXT_COMPOSITOR_PYTHONPATH ||= repoRoot;

const files = [];
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--theme') {
    const value = args[++i];
    if (value !== 'light' && value !== 'dark') {
      process.stderr.write('--theme には light か dark を指定してください\n');
      process.exit(2);
    }
    env.VIEWER_THEME = value;
  } else {
    files.push(path.resolve(baseDir, args[i]));
  }
}

// 起動が、すぐ終了（コード0）するときは、前回のElectronが残っている（二重起動の防止）。そのとき、一言添える
const started = Date.now();
const child = spawn(require('electron'), ['.', ...files], { cwd: viewerDir, env, stdio: 'inherit' });
child.on('exit', (code) => {
  if (code === 0 && Date.now() - started < 3000) {
    process.stderr.write('すぐに終了しました。前回のObunzu（electron.exe）が残っていると、二重起動の防止で、すぐ終了します。\n');
  }
  process.exit(code ?? 1);
});
