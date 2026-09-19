'use strict';
// Viewer（Electron）のメインプロセス（#190）。
//
// ウィンドウは、2つのビューでできている。
//   - ウィンドウ本体（chrome/）: ツールバー・エラーの帯・診断の一覧。
//   - 内容のビュー: ワーカーが作ったHTMLを表示する。Chromiumが、再読み込みで、スクロール位置を保つ。
// Markdownのファイルは、Pythonの常駐ワーカー（render_html）でHTMLにする。ワーカーが返した診断は、画面に出す。

const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow, Menu, WebContentsView, dialog, ipcMain, nativeTheme, shell } = require('electron');

const { summarize } = require('./diagnostics');
const { PythonNotFoundError, resolveWorkerLaunch } = require('./python');
const { DIAGRAM_EXTENSIONS, MARKDOWN_EXTENSIONS, classifyNavigation, fileFromArgv, isOpenable } = require('./targets');
const { FileWatcher } = require('./watcher');
const { WorkerClient } = require('./worker-client');

// アプリケーション名（#194）。Observe（観察する）+ 文図（文章と図）の造語。
// AppUserModelIdは、Windowsのタスクバーの固定・通知が、このアプリとして扱われるための識別子。
const APP_NAME = 'Obunzu';
// ウィンドウのタイトルに、バージョン（package.jsonのversion）を添える。
const APP_TITLE = `${APP_NAME} ${app.getVersion()}`;
app.setAppUserModelId('io.github.tokudiro.obunzu');

// #180で調整した起動引数。GPUを使わず、GPU処理をブラウザのプロセスに統合する（メモリが約35%減り、体感で最速だった）。
// 環境変数 VIEWER_GPU=1 で、標準の動作に戻せる。
if (process.env.VIEWER_GPU !== '1') {
  app.commandLine.appendSwitch('disable-gpu');
  app.commandLine.appendSwitch('in-process-gpu');
}

// 環境変数 VIEWER_THEME=light|dark で、OSの設定に関わらず、配色を固定する（画面の確認用。#192）。
if (process.env.VIEWER_THEME === 'light' || process.env.VIEWER_THEME === 'dark') {
  nativeTheme.themeSource = process.env.VIEWER_THEME;
}

// 環境変数 VIEWER_TRACE=1 で、起動の各段階の時刻（プロセスの開始から）を、標準エラーへ出す。
const trace = process.env.VIEWER_TRACE
  ? (label) => process.stderr.write(`[viewer] ${label} +${Math.round(process.uptime() * 1000)}ms\n`)
  : () => {};

const state = {
  file: null,            // 開いている（または、開こうとしている）ファイル
  busy: false,
  status: '',
  zoomPercent: 100,
  autoReload: true,      // 原稿・参照ファイルの保存を検知して、自動で更新する（#170）
  hasDocument: false,    // 内容を表示しているか
  diagnostics: summarize([]),
};

let win = null;
let contentView = null;
let chromeHeight = 40;
let zoomLevel = 0;
let worker = null;
let shown = null;        // 表示中の文書 {md, html}
let inFlight = false;
let queued = null;
let watcher = null;

// -- 起動 -----------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv, workingDirectory) => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
    const file = fileFromArgv(argv.slice(1), { cwd: workingDirectory });
    if (file) openFile(file);
  });

  app.whenReady().then(() => {
    trace('app-ready');
    createWindow();
    watcher = new FileWatcher({ onChange: onFilesChanged });
    Menu.setApplicationMenu(buildMenu());
    startWorker();
    const file = fileFromArgv(process.argv.slice(app.isPackaged ? 1 : 2));
    if (file) openFile(file);
  });
}

app.on('window-all-closed', () => app.quit());

let quitting = false;
app.on('before-quit', (event) => {
  watcher?.close();
  if (quitting || !worker) return;
  event.preventDefault();
  quitting = true;
  worker.dispose().finally(() => app.quit());
});

// -- ウィンドウ ---------------------------------------------------------------

function createWindow() {
  // 起動時に、白い画面を長く見せない。ウィンドウと内容のビューの背景を、ページの背景色に合わせる（#180）。
  const background = nativeTheme.shouldUseDarkColors ? '#0d1117' : '#ffffff';
  win = new BrowserWindow({
    width: 1000,
    height: 800,
    title: APP_TITLE,
    icon: path.join(__dirname, '..', 'assets', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    backgroundColor: background,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'chrome', 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.loadFile(path.join(__dirname, 'chrome', 'chrome.html'));

  // 内容のビュー。HTMLは、生成したもので、スクリプトを含まず、CSPでスクリプトを禁止している。
  // JavaScriptを有効にしているのは、ドロップの受け口（プリロード）を動かすため（無効だと、プリロードも動かない）。
  contentView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, 'chrome', 'content-preload.js'),   // ドロップの受け口だけ
      sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: true,
    },
  });
  contentView.setBackgroundColor(background);
  win.contentView.addChildView(contentView);

  const contents = contentView.webContents;
  contents.setWindowOpenHandler(({ url }) => { handleNavigation(url); return { action: 'deny' }; });
  // ドロップ・リンクで、アプリの表示が、他のページへ遷移してしまわないようにする
  contents.on('will-navigate', (event, url) => { event.preventDefault(); handleNavigation(url); });
  contents.on('zoom-changed', (_event, direction) => zoomBy(direction === 'in' ? 1 : -1));
  contents.on('did-finish-load', () => contents.setZoomLevel(zoomLevel));

  win.on('resize', layout);
  layout();
  trace('window-created');
}

/** 内容のビューを、ツールバーの下に置く。文書がまだ無いときは、大きさ0にして、案内の表示を隠さない。 */
function layout() {
  if (!win || !contentView) return;
  const [width, height] = win.getContentSize();
  contentView.setBounds(state.hasDocument
    ? { x: 0, y: chromeHeight, width, height: Math.max(0, height - chromeHeight) }
    : { x: 0, y: chromeHeight, width: 0, height: 0 });
}

function push() {
  if (win && !win.isDestroyed()) win.webContents.send('state', state);
}

// -- ワーカーと変換 -------------------------------------------------------------

function appDirectory() {
  return app.isPackaged ? path.dirname(process.execPath) : path.resolve(__dirname, '..');
}

/** ワーカーを、先に起動しておく。Pythonが見つからないときは、診断に出す（ウィンドウは、開いたままにする）。 */
function startWorker() {
  getWorker()
    .then((client) => client.warmUp())
    .then(() => trace('worker-ready'))
    .catch((error) => {
      state.diagnostics = summarize([{ severity: 'error', message: error.message }]);
      state.status = 'Pythonのワーカーを起動できません';
      push();
    });
}

async function getWorker() {
  if (!worker) {
    // 見つからない場合は、キャッシュせず、次の依頼でも、探し直す（環境変数を直した後に、再試行できるように）
    worker = new WorkerClient(resolveWorkerLaunch(appDirectory()));
  }
  return worker;
}

/** ファイルを開く。変換中に、次の依頼が来たときは、最後の依頼だけを残す。 */
function openFile(file) {
  const full = path.resolve(file);
  if (!isOpenable(full)) {
    state.diagnostics = summarize([{ severity: 'error', message: `開けないファイルです: ${path.basename(full)}` }]);
    push();
    return;
  }
  queued = full;
  if (!inFlight) void drain();
}

function reload() {
  if (state.file) openFile(state.file);
}

async function drain() {
  inFlight = true;
  try {
    while (queued) {
      const file = queued;
      queued = null;
      await renderOnce(file);
    }
  } finally {
    inFlight = false;
  }
}

async function renderOnce(file) {
  const sameDocument = shown?.md === file;
  state.file = file;
  state.busy = true;
  state.status = '';
  push();

  let result;
  try {
    const client = await getWorker();
    result = await client.renderHtml({ path: file });
  } catch (error) {
    if (error instanceof PythonNotFoundError) worker = null;
    // 想定外の例外でも、アプリを落とさず、原因を診断として見せる
    result = { ok: false, html: null, timings_ms: {}, diagnostics: [{ severity: 'error', message: error.message }] };
  }

  state.diagnostics = summarize(result.diagnostics);
  if (result.ok && result.html) {
    await showHtml(file, result.html, sameDocument, result.dependencies);
    const total = result.timings_ms.total;
    const warnings = state.diagnostics.warnings > 0 ? ` ／ 警告 ${state.diagnostics.warnings} 件` : '';
    state.status = `${clock()} ${total !== undefined ? `更新 ${Math.round(total)} ms` : '更新済み'}${warnings}`;
    win?.setTitle(`${path.basename(file)} - ${APP_TITLE}`);
    trace('content-shown');
  } else {
    // 失敗しても、直前に成功した表示を残す。ファイル名も、表示中の文書に戻す。
    state.file = shown ? shown.md : file;
    state.status = shown ? '変換に失敗しました。前回の成功した表示を残しています' : '変換に失敗しました';
  }
  state.busy = false;
  updateWatch();
  push();
}

/**
 * 監視するファイルを、表示中の原稿と、その参照ファイルにする。変換に失敗しても、原稿は監視し続ける
 * （直して保存したときに、自動で更新できるように）。
 */
function updateWatch() {
  if (!watcher || !state.file) return;
  const dependencies = shown && shown.md === state.file ? shown.deps : [];
  watcher.setFiles([state.file, ...dependencies]);
}

/** 監視しているファイルが、保存された。自動更新が有効なら、もう一度変換する。 */
async function onFilesChanged(paths) {
  trace(`changed ${paths.length}`);
  if (!state.autoReload || !state.file) return;
  const target = state.file;
  // エディタの原子的な保存の途中で、原稿が、一時的に無いことがある。短く待つ。
  for (let i = 0; i < 10 && !fs.existsSync(target); i++) await new Promise((resolve) => setTimeout(resolve, 100));
  if (state.file === target && fs.existsSync(target)) openFile(target);
}

function setAutoReload(value) {
  state.autoReload = Boolean(value);
  const item = Menu.getApplicationMenu()?.getMenuItemById('auto-reload');
  if (item) item.checked = state.autoReload;
  push();
}

function clock() {
  const now = new Date();
  return [now.getHours(), now.getMinutes(), now.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

/** HTMLを表示する。同じ文書の再読み込みは、`reload`で、スクロール位置を保つ。別の文書は、先頭から表示する。 */
async function showHtml(md, html, sameDocument, dependencies = []) {
  const contents = contentView.webContents;
  const loaded = new Promise((resolve) => {
    const done = () => { contents.removeListener('did-finish-load', done); contents.removeListener('did-fail-load', done); resolve(); };
    contents.once('did-finish-load', done);
    contents.once('did-fail-load', done);
  });
  if (sameDocument && shown?.html === html) contents.reloadIgnoringCache();
  else contents.loadFile(html).catch(() => {});
  await loaded;
  shown = { md, html, deps: dependencies };
  if (!state.hasDocument) { state.hasDocument = true; layout(); }
  contents.focus();
}

// -- ナビゲーション・ズーム -------------------------------------------------------

function handleNavigation(url) {
  const target = classifyNavigation(url);
  if (target.type === 'external') shell.openExternal(target.url);
  else if (target.type === 'open') openFile(target.path);
}

function zoomBy(delta) {
  zoomLevel = Math.min(5, Math.max(-3, zoomLevel + delta * 0.5));
  contentView?.webContents.setZoomLevel(zoomLevel);
  state.zoomPercent = Math.round(Math.pow(1.2, zoomLevel) * 100);
  push();
}

function zoomReset() {
  zoomLevel = 0;
  contentView?.webContents.setZoomLevel(0);
  state.zoomPercent = 100;
  push();
}

async function openWithDialog() {
  const result = await dialog.showOpenDialog(win, {
    title: 'Markdownファイルを開く',
    properties: ['openFile'],
    filters: [
      { name: 'Markdown・図', extensions: [...MARKDOWN_EXTENSIONS, ...DIAGRAM_EXTENSIONS].map((e) => e.slice(1)) },
      { name: 'すべてのファイル', extensions: ['*'] },
    ],
  });
  if (!result.canceled && result.filePaths[0]) openFile(result.filePaths[0]);
}

// -- メニュー・IPC --------------------------------------------------------------

function buildMenu() {
  return Menu.buildFromTemplate([
    {
      label: 'ファイル',
      submenu: [
        { label: '開く…', accelerator: 'CommandOrControl+O', click: () => openWithDialog() },
        { label: '再読み込み', accelerator: 'F5', click: reload },
        { label: '再読み込み', accelerator: 'CommandOrControl+R', click: reload, visible: false },
        { id: 'auto-reload', label: '保存したら自動で更新', type: 'checkbox', checked: true, click: (item) => setAutoReload(item.checked) },
        { type: 'separator' },
        { label: '終了', accelerator: 'CommandOrControl+Q', click: () => app.quit() },
      ],
    },
    {
      label: '表示',
      submenu: [
        { label: '拡大', accelerator: 'CommandOrControl+Plus', click: () => zoomBy(1) },
        { label: '拡大', accelerator: 'CommandOrControl+=', click: () => zoomBy(1), visible: false },
        { label: '縮小', accelerator: 'CommandOrControl+-', click: () => zoomBy(-1) },
        { label: '実寸', accelerator: 'CommandOrControl+0', click: zoomReset },
        ...(process.env.VIEWER_DEBUG ? [{ type: 'separator' }, { role: 'toggleDevTools' }] : []),
      ],
    },
  ]);
}

ipcMain.on('chrome-ready', push);
ipcMain.on('chrome-height', (_event, height) => { chromeHeight = Math.max(0, Math.round(height)); layout(); });
ipcMain.on('open-dialog', () => openWithDialog());
ipcMain.on('reload', reload);
ipcMain.on('auto-reload', (_event, value) => setAutoReload(value));
ipcMain.on('zoom', (_event, direction) => zoomBy(direction));
ipcMain.on('zoom-reset', zoomReset);
ipcMain.on('open-path', (_event, filePath) => { if (typeof filePath === 'string') openFile(filePath); });
