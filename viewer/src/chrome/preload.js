'use strict';
// 画面（ツールバー・エラーの帯）から、メインプロセスを呼ぶための、最小のAPI（#190）。
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('viewer', {
  onState: (callback) => ipcRenderer.on('state', (_event, state) => callback(state)),
  ready: () => ipcRenderer.send('chrome-ready'),
  openDialog: () => ipcRenderer.send('open-dialog'),
  reload: () => ipcRenderer.send('reload'),
  setAutoReload: (value) => ipcRenderer.send('auto-reload', value),
  zoomIn: () => ipcRenderer.send('zoom', 1),
  zoomOut: () => ipcRenderer.send('zoom', -1),
  zoomReset: () => ipcRenderer.send('zoom-reset'),
  openPath: (filePath) => ipcRenderer.send('open-path', filePath),
  pathForFile: (file) => webUtils.getPathForFile(file),
  setChromeHeight: (height) => ipcRenderer.send('chrome-height', height),
});
