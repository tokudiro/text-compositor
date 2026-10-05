'use strict';
// 画面（ツールバー・エラーの帯）から、メインプロセスを呼ぶための、最小のAPI（#190）。
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('viewer', {
  onState: (callback) => ipcRenderer.on('state', (_event, state) => callback(state)),
  ready: () => ipcRenderer.send('chrome-ready'),
  openDialog: () => ipcRenderer.send('open-dialog'),
  goBack: () => ipcRenderer.send('go-back'),
  goForward: () => ipcRenderer.send('go-forward'),
  reload: () => ipcRenderer.send('reload'),
  setAutoReload: (value) => ipcRenderer.send('auto-reload', value),
  setCsvHeader: (value) => ipcRenderer.send('csv-header', value),
  zoomIn: () => ipcRenderer.send('zoom', 1),
  zoomOut: () => ipcRenderer.send('zoom', -1),
  zoomReset: () => ipcRenderer.send('zoom-reset'),
  toggleSettings: () => ipcRenderer.send('settings-toggle'),
  toggleSidebar: () => ipcRenderer.send('sidebar-toggle'),
  openFolder: () => ipcRenderer.send('open-folder'),
  listDirectory: (directory) => ipcRenderer.invoke('list-directory', directory),
  setSetting: (key, value) => ipcRenderer.send('settings-set', key, value),
  chooseOpenDirectory: () => ipcRenderer.send('choose-open-directory'),
  clearCache: () => ipcRenderer.send('clear-cache'),
  openPath: (filePath, inNewTab = false) => ipcRenderer.send('open-path', filePath, inNewTab),
  pathForFile: (file) => webUtils.getPathForFile(file),
  setChromeHeight: (height) => ipcRenderer.send('chrome-height', height),
  toggleSearch: () => ipcRenderer.send('search-toggle'),
  closeSearch: () => ipcRenderer.send('search-close'),
  setSearch: (payload) => ipcRenderer.send('search-set', payload),
  moveSearch: (delta) => ipcRenderer.send('search-move', delta),
  activateTab: (id) => ipcRenderer.send('tab-activate', id),
  closeTab: (id) => ipcRenderer.send('tab-close', id),
  newTab: () => ipcRenderer.send('tab-new'),
});
