'use strict';
// 内容のビュー（生成したHTMLを表示する）の、ドラッグ＆ドロップの受け口（#190）。
// ドロップされたファイルのパスを、メインプロセスへ渡すだけで、文書には何も公開しない。
// 何もしないと、ファイルへ、ページが遷移してしまい、（JavaScriptを無効にしているため）ドロップを受け取れない。
const { ipcRenderer, webUtils } = require('electron');

window.addEventListener('dragover', (event) => event.preventDefault(), true);
window.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) ipcRenderer.send('open-path', webUtils.getPathForFile(file));
}, true);

// スクロール位置をメインプロセスへ伝える（#330）。
// 画面遷移時に非同期IPCで問い合わせると、openFileのキュー順序が崩れる（#342レビュー指摘）。
// スクロール時に最新の位置をメインプロセスへ送っておき、キュー処理は同期のまま保つ。
let scrollRaf = null;
window.addEventListener('scroll', () => {
  if (scrollRaf) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null;
    ipcRenderer.send('content-scroll', window.scrollY);
  });
}, { passive: true });

window.addEventListener('pagehide', () => {
  if (scrollRaf) {
    cancelAnimationFrame(scrollRaf);
    scrollRaf = null;
  }
  ipcRenderer.send('content-scroll', window.scrollY);
});
