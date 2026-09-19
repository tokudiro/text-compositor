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
