'use strict';
// Viewer（Electron）のメインプロセス（#190）。
//
// ウィンドウは、2つのビューでできている。
//   - ウィンドウ本体（chrome/）: ツールバー・エラーの帯・診断の一覧。
//   - 内容のビュー: ワーカーが作ったHTMLを表示する。Chromiumが、再読み込みで、スクロール位置を保つ。
// Markdownのファイルは、Pythonの常駐ワーカー（render_html）でHTMLにする。ワーカーが返した診断は、画面に出す。

const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow, Menu, WebContentsView, dialog, ipcMain, nativeTheme, screen, shell } = require('electron');

const { summarize } = require('./diagnostics');
const { PythonNotFoundError, resolveWorkerLaunch } = require('./python');
const { DEFAULTS, EDITABLE, loadSettings, normalizeSettings, saveSettings } = require('./settings');
const { DIAGRAM_EXTENSIONS, MARKDOWN_EXTENSIONS, OTHER_EXTENSIONS, checkOpenTarget, classifyNavigation, fileFromArgv } = require('./targets');
const { FileWatcher } = require('./watcher');
const { MermaidHost } = require('./mermaid-host');
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

// 環境変数 VIEWER_THEME=light|dark は、設定より優先して、配色を固定する（画面の確認用。#192）。
const THEME_FROM_ENV = process.env.VIEWER_THEME === 'light' || process.env.VIEWER_THEME === 'dark'
  ? process.env.VIEWER_THEME
  : null;

// 環境変数 VIEWER_TRACE=1 で、起動の各段階の時刻（プロセスの開始から）を、標準エラーへ出す。
const trace = process.env.VIEWER_TRACE
  ? (label) => process.stderr.write(`[viewer] ${label} +${Math.round(process.uptime() * 1000)}ms\n`)
  : () => {};

const state = {
  file: null,            // 開いている（または、開こうとしている）ファイル
  busy: false,
  status: '',
  zoomPercent: 100,
  autoReload: DEFAULTS.autoReload,   // 原稿・参照ファイルの保存を検知して、自動で更新する（#170）。設定として保存する
  hasDocument: false,    // 内容を表示しているか
  settingsOpen: false,   // 設定画面を開いているとき、内容のビューを隠して、設定を表示する（#200）
  isCsv: false,          // 開いているのが、.csvか（ツールバーの、見出し行の切り替えを出す。#220）
  settings: { ...DEFAULTS },
  diagnostics: summarize([]),
};

let settingsFile = null;

let win = null;
let contentView = null;
let chromeHeight = 40;
let zoomLevel = 0;
let worker = null;
let shown = null;        // 表示中の文書 {md, html}
let inFlight = false;
let queued = null;
let watcher = null;
// Mermaidの描画（非表示のウィンドウ。最初の図で作る。#207）。ワーカーが、標準入出力で、依頼してくる。
const mermaidHost = new MermaidHost({
  createWindow: () => new BrowserWindow({
    show: false,
    width: 800,
    height: 600,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
  }),
});

// -- 起動 -----------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv, workingDirectory) => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
    const file = targetFromArgv(argv, workingDirectory);
    if (file) openFile(file);
  });

  app.whenReady().then(() => {
    trace('app-ready');
    settingsFile = path.join(app.getPath('userData'), 'settings.json');
    state.settings = loadSettings(settingsFile);
    state.autoReload = state.settings.autoReload;
    applyTheme();
    createWindow();
    watcher = new FileWatcher({ onChange: onFilesChanged });
    Menu.setApplicationMenu(buildMenu());
    startWorker();
    const file = targetFromArgv(process.argv, process.cwd());
    if (file) openFile(file);
  });
}

app.on('window-all-closed', () => app.quit());

let quitting = false;
app.on('before-quit', (event) => {
  watcher?.close();
  mermaidHost.dispose();
  if (quitting || !worker) return;
  event.preventDefault();
  quitting = true;
  worker.dispose().finally(() => app.quit());
});

// -- ウィンドウ ---------------------------------------------------------------

function createWindow() {
  // 起動時に、白い画面を長く見せない。ウィンドウと内容のビューの背景を、ページの背景色に合わせる（#180）。
  const background = nativeTheme.shouldUseDarkColors ? '#0d1117' : '#ffffff';
  const saved = restoredWindow();
  win = new BrowserWindow({
    ...saved.bounds,
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

  if (saved.maximized) win.maximize();
  win.on('resize', () => { layout(); scheduleWindowSave(); });
  win.on('move', scheduleWindowSave);
  win.on('maximize', scheduleWindowSave);
  win.on('unmaximize', scheduleWindowSave);
  win.on('close', saveWindowNow);
  // 非表示のMermaidのウィンドウが残ると、'window-all-closed'が発火せず、アプリが終了しない
  win.on('closed', () => mermaidHost.dispose());
  handleEscape(win.webContents);
  handleEscape(contents);
  nativeTheme.on('updated', applyBackground);
  layout();
  trace('window-created');
}

/** 内容のビューを、ツールバーの下に置く。文書がまだ無いときは、大きさ0にして、案内の表示を隠さない。 */
function layout() {
  if (!win || !contentView) return;
  const [width, height] = win.getContentSize();
  // ツールバーが下のときは、内容が、画面の上端から始まる（帯・一覧も、ツールバーの側に、まとまる）
  const y = state.settings.toolbarPosition === 'bottom' ? 0 : chromeHeight;
  // 設定画面を開いている間も、内容のビューを隠す（設定は、ウィンドウ本体の側に表示するため）
  contentView.setBounds(state.hasDocument && !state.settingsOpen
    ? { x: 0, y, width, height: Math.max(0, height - chromeHeight) }
    : { x: 0, y, width: 0, height: 0 });
}

/** Escで、設定画面を閉じる（設定画面のときは、文書の側は、隠れていてキーを受けないため、メインプロセスで受ける）。 */
function handleEscape(webContents) {
  webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.key === 'Escape' && state.settingsOpen) {
      event.preventDefault();
      setSettingsOpen(false);
    }
  });
}
// -- 設定（#200） -------------------------------------------------------------

function applyTheme() {
  nativeTheme.themeSource = THEME_FROM_ENV ?? state.settings.theme;
}

/** 配色が変わったとき（設定・OSの切り替え）、起動時に合わせた背景色も、合わせ直す。 */
function applyBackground() {
  const background = nativeTheme.shouldUseDarkColors ? '#0d1117' : '#ffffff';
  win?.setBackgroundColor(background);
  contentView?.setBackgroundColor(background);
}

function setSettingsOpen(open) {
  state.settingsOpen = Boolean(open);
  layout();
  push();
  // 開いたら、フォーカスを設定画面（ウィンドウ本体）へ移す。文書に残ったままだと、隠れた文書がキーを受けて、
  // Escで閉じられない（実測）。閉じたら、文書へ戻す（スクロール・キー操作が、そのまま使える）。
  if (state.settingsOpen) win.webContents.focus();
  else if (state.hasDocument) contentView.webContents.focus();
}

// -- ウィンドウの大きさ・位置の記憶（#192） ------------------------------------------

const DEFAULT_BOUNDS = { width: 1000, height: 800 };

/** 位置が、どれかの画面に、十分に見える（タイトルバーをつかめる）か。外付けの画面を外したあとの、画面外への復元を防ぐ。 */
function isVisibleOnScreen(bounds) {
  return screen.getAllDisplays().some(({ workArea }) => {
    const overlapX = Math.min(bounds.x + bounds.width, workArea.x + workArea.width) - Math.max(bounds.x, workArea.x);
    const overlapY = Math.min(bounds.y + bounds.height, workArea.y + workArea.height) - Math.max(bounds.y, workArea.y);
    return overlapX >= 100 && overlapY >= 50;
  });
}

/** 前回の大きさ・位置。位置が、今の画面に収まらないときは、大きさだけを使う（位置は、OSに任せる）。 */
function restoredWindow() {
  const saved = state.settings.window;
  if (!saved) return { bounds: { ...DEFAULT_BOUNDS }, maximized: false };
  const bounds = { width: saved.width, height: saved.height };
  if (saved.x !== undefined && isVisibleOnScreen({ x: saved.x, y: saved.y, width: saved.width, height: saved.height })) {
    bounds.x = saved.x;
    bounds.y = saved.y;
  }
  return { bounds, maximized: saved.maximized };
}

let windowSaveTimer = null;

/** 移動・サイズ変更は、続けて何度も届くため、落ち着いてから、1回だけ保存する。 */
function scheduleWindowSave() {
  clearTimeout(windowSaveTimer);
  windowSaveTimer = setTimeout(saveWindowNow, 400);
}

function saveWindowNow() {
  clearTimeout(windowSaveTimer);
  if (!win || win.isDestroyed() || win.isMinimized()) return;
  // 最大化中でも、元の大きさ・位置を保存する（戻したときに、その大きさになる）
  const { x, y, width, height } = win.getNormalBounds();
  const next = { x, y, width, height, maximized: win.isMaximized() };
  const current = state.settings.window;
  if (current && Object.keys(next).every((key) => current[key] === next[key])) return;
  state.settings = normalizeSettings({ ...state.settings, window: next });
  saveSettings(settingsFile, state.settings);
}
/** 利用者が、ファイルを開く・再読み込みをしたときは、設定画面を閉じて、文書を見せる（自動更新では、閉じない）。 */
function leaveSettings() {
  if (state.settingsOpen) setSettingsOpen(false);
}

/** 設定を1つ変えて、すぐに反映し、保存する。想定外のキー・値は、無視する。 */
function changeSetting(key, value) {
  if (!EDITABLE.includes(key)) return;   // ウィンドウの状態などは、画面から変えさせない
  const next = normalizeSettings({ ...state.settings, [key]: value });
  if (next[key] !== value) return;
  state.settings = next;
  if (key === 'theme') applyTheme();
  if (key === 'autoReload') state.autoReload = next.autoReload;
  saveSettings(settingsFile, state.settings);
  layout();
  push();
}

function push() {
  state.isCsv = /\.csv$/i.test(state.file ?? '');
  // 「表示」メニューの、CSVの見出し行の項目は、.csvを開いているときだけ、有効にする
  const csvItem = Menu.getApplicationMenu()?.getMenuItemById('csv-header');
  if (csvItem) { csvItem.enabled = state.isCsv; csvItem.checked = state.settings.csvHeader; }
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
    const launch = resolveWorkerLaunch(appDirectory());
    // Mermaidは、Pythonのplaywrightではなく、こちら（ElectronのChromium）で描画する（#207）
    launch.env = { ...launch.env, TEXT_COMPOSITOR_MERMAID_HOST: '1' };
    worker = new WorkerClient(launch, { services: { render_mermaid: (payload) => mermaidHost.render(payload) } });
  }
  return worker;
}

/**
 * 起動引数から、開くファイルを探す。開発時（`electron <アプリのフォルダ> <ファイル>`）は、引数に、アプリのフォルダも
 * 入るため、外す。拡張子では絞らない（#196）ため、外さないと、アプリのフォルダを、ファイルとして開こうとしてしまう。
 */
function targetFromArgv(argv, cwd) {
  const appPath = path.resolve(app.getAppPath());
  const args = argv.slice(1).filter((arg) => !arg || arg.startsWith('-') || path.resolve(cwd, arg) !== appPath);
  return fileFromArgv(args, { cwd });
}
/** ファイルを開く。変換中に、次の依頼が来たときは、最後の依頼だけを残す。 */
function openFile(file) {
  const full = path.resolve(file);
  const target = checkOpenTarget(full);
  if (!target.ok) {
    state.diagnostics = summarize([{ severity: 'error', message: target.message }]);
    push();
    return;
  }
  queued = full;
  if (!inFlight) void drain();
}

function reload() {
  leaveSettings();
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
    result = await client.renderHtml({ path: file, csv_header: state.settings.csvHeader });
  } catch (error) {
    if (error instanceof PythonNotFoundError) worker = null;
    // 想定外の例外でも、アプリを落とさず、原因を診断として見せる
    result = { ok: false, html: null, timings_ms: {}, diagnostics: [{ severity: 'error', message: error.message }] };
  }

  state.diagnostics = summarize(result.diagnostics);
  if (result.ok && result.html) {
    await showHtml(file, result.html, sameDocument, result.dependencies);
    const total = result.timings_ms.total;
    // 警告の件数は、帯に出るため、状態の表示には、入れない（同じ内容を2か所に出さない）
    state.status = `${clock()} ${total !== undefined ? `更新 ${Math.round(total)} ms` : '更新済み'}`;
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

/** .csvの1行目を、見出し行にするか（#220）。設定として覚え、開いているCSVを、表示し直す（スクロール位置は、保たれる）。 */
function setCsvHeader(value) {
  changeSetting('csvHeader', Boolean(value));
  if (state.isCsv && state.file) openFile(state.file);
}

function setAutoReload(value) {
  changeSetting('autoReload', Boolean(value));   // 設定として保存し、次の起動でも保つ
  const item = Menu.getApplicationMenu()?.getMenuItemById('auto-reload');
  if (item) item.checked = state.autoReload;
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
  if (!state.settingsOpen) contents.focus();
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
  leaveSettings();
  const result = await dialog.showOpenDialog(win, {
    title: 'ファイルを開く',
    properties: ['openFile'],
    filters: [
      { name: 'Markdown・図・テキスト・CSV・SVG', extensions: [...MARKDOWN_EXTENSIONS, ...DIAGRAM_EXTENSIONS, ...OTHER_EXTENSIONS].map((e) => e.slice(1)) },
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
        { id: 'auto-reload', label: '保存したら自動で更新', type: 'checkbox', checked: state.autoReload, click: (item) => setAutoReload(item.checked) },
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
        { type: 'separator' },
        { id: 'csv-header', label: 'CSV: 1行目を見出しにする', type: 'checkbox', checked: state.settings.csvHeader, enabled: false, click: (item) => setCsvHeader(item.checked) },
        { type: 'separator' },
        { label: '設定…', accelerator: 'CommandOrControl+,', click: () => setSettingsOpen(!state.settingsOpen) },
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
ipcMain.on('csv-header', (_event, value) => setCsvHeader(value));
ipcMain.on('zoom', (_event, direction) => zoomBy(direction));
ipcMain.on('zoom-reset', zoomReset);
ipcMain.on('settings-toggle', () => setSettingsOpen(!state.settingsOpen));
ipcMain.on('settings-set', (_event, key, value) => changeSetting(key, value));
ipcMain.on('open-path', (_event, filePath) => { if (typeof filePath === 'string') { leaveSettings(); openFile(filePath); } });
