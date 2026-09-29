'use strict';
// Viewer（Electron）のメインプロセス（#190）。
//
// ウィンドウは、2つのビューでできている。
//   - ウィンドウ本体（chrome/）: ツールバー・エラーの帯・診断の一覧。
//   - 内容のビュー: ワーカーが作ったHTMLを表示する。Chromiumが、再読み込みで、スクロール位置を保つ。
// Markdownのファイルは、Pythonの常駐ワーカー（render_html）でHTMLにする。ワーカーが返した診断は、画面に出す。

const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow, Menu, WebContentsView, clipboard, dialog, ipcMain, nativeTheme, net, screen, shell } = require('electron');

const { summarize } = require('./diagnostics');
const { NavigationHistory } = require('./history');
const { buildImageContextMenuTemplate, executeSaveImage } = require('./image-save');
const { PythonNotFoundError, resolveWorkerLaunch } = require('./python');
const { DEFAULTS, EDITABLE, loadSettings, normalizeSettings, saveSettings } = require('./settings');
const { checkOpenTarget, classifyNavigation, fileFromArgv, openDialogDirectory, openDialogFilters } = require('./targets');
const { FileWatcher } = require('./watcher');
const { MermaidHost } = require('./mermaid-host');
const { VegaHost } = require('./vega-host');
const { cacheRoot, cacheUsage, clearCache, workLocation } = require('./workdir');
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
  cache: { bytes: null, clearing: false },   // アプリの領域（変換したHTML・図のキャッシュ）の使用量。設定画面を開いたときに数える（#258）
  diagnostics: summarize([]),
  canGoBack: false,      // 戻るナビゲーションができるか（#330）
  canGoForward: false,   // 進むナビゲーションができるか（#330）
  // 文書内検索（#325）。ハイライトそのものは、内容のビューのプリロードが持つ（DOMを持っているのは、そちら）。
  // ここは、検索欄の入力と、その結果（件数・現在位置・正規表現エラー）だけを覚える。
  search: { open: false, query: '', regex: false, caseSensitive: false, count: 0, current: 0, error: null },
};

const history = new NavigationHistory();

let settingsFile = null;

let win = null;
let contentView = null;
let chromeHeight = 40;
let zoomLevel = 0;
let worker = null;
let shown = null;        // 表示中の文書 {md, html}
let inFlight = false;
let queued = null;
let idleWaiters = [];   // 変換が終わるのを待つ処理（キャッシュの削除）
let watcher = null;
const workRoot = cacheRoot();   // アプリの領域（#258）
// Mermaidの描画（非表示のウィンドウ。最初の図で作る。#207）および画像のラスタライズ（#327）。
const createHiddenWindow = (options = {}) => new BrowserWindow({
  show: false,
  width: 800,
  height: 600,
  webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false, ...options.webPreferences },
  ...options,
});
const mermaidHost = new MermaidHost({ createWindow: createHiddenWindow });
const vegaHost = new VegaHost({ createWindow: createHiddenWindow });   // Vega・Vega-Lite（#351）

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
  vegaHost.dispose();
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

  // 二重の防御（方針2章・#238）: 変換側（Python、既定で外部画像をプレースホルダに置き換える）に漏れがあっても、
  // http/httpsの通信そのものを、ここで止める。allowExternalImages（設定で許可）のときだけ、通す。
  contentView.webContents.session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] },
    (_details, callback) => callback({ cancel: !state.settings.allowExternalImages }));

  const contents = contentView.webContents;
  // content-preload.jsは、ドラッグ＆ドロップだけでなく、検索（#325）も持つようになった。失敗しても画面は白いままで
  // 気づけないため、標準エラーへ出す（サンドボックス化したプリロードは、electron以外のローカルファイルを
  // requireできない、という実測を、この行で見つけた）。
  contents.on('preload-error', (_e, path, error) => process.stderr.write(`[preload-error] ${path}: ${error.stack || error}\n`));
  contents.setWindowOpenHandler(({ url }) => { handleNavigation(url); return { action: 'deny' }; });
  // ドロップ・リンクで、アプリの表示が、他のページへ遷移してしまわないようにする
  contents.on('will-navigate', (event, url) => { event.preventDefault(); handleNavigation(url); });
  contents.on('zoom-changed', (_event, direction) => zoomBy(direction === 'in' ? 1 : -1));
  contents.on('did-finish-load', () => { contents.setZoomLevel(zoomLevel); sendLineBadge(); });
  contents.on('context-menu', (_event, params) => handleContextMenu(params));

  if (saved.maximized) win.maximize();
  win.on('resize', () => { layout(); scheduleWindowSave(); });
  win.on('move', scheduleWindowSave);
  win.on('maximize', scheduleWindowSave);
  win.on('unmaximize', scheduleWindowSave);
  win.on('close', saveWindowNow);
  // 非表示のMermaidのウィンドウが残ると、'window-all-closed'が発火せず、アプリが終了しない
  win.on('closed', () => { mermaidHost.dispose(); vegaHost.dispose(); });
  handleEscape(win.webContents);
  handleEscape(contents);
  handleNavigationShortcuts(win.webContents);
  handleNavigationShortcuts(contents);
  win.on('app-command', (_event, cmd) => {
    if (cmd === 'browser-backward') goBack();
    else if (cmd === 'browser-forward') goForward();
  });
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

/**
 * Escで、設定画面・検索欄を閉じる。設定画面のときは、文書の側は、隠れていてキーを受けないため、メインプロセスで受ける。
 * 検索欄は、文書の側（内容のビュー）にフォーカスがあるときも、閉じられるようにする（検索欄自身のEscは、chrome.js側で扱う）。
 */
function handleEscape(webContents) {
  webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || input.key !== 'Escape') return;
    if (state.settingsOpen) {
      event.preventDefault();
      setSettingsOpen(false);
    } else if (state.search.open) {
      event.preventDefault();
      setSearchOpen(false);
    }
  });
}

/** Alt+← / Alt+→ で、戻る・進むナビゲーションを行う（#330）。Chromiumの既定の動作を防ぎ、Viewerの履歴を動かす。 */
function handleNavigationShortcuts(webContents) {
  webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.alt && !input.control && !input.shift && !input.meta) {
      if (input.key === 'ArrowLeft') {
        event.preventDefault();
        goBack();
      } else if (input.key === 'ArrowRight') {
        event.preventDefault();
        goForward();
      }
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
  if (state.settingsOpen) { win.webContents.focus(); void refreshCacheUsage(); }
  else if (state.hasDocument) contentView.webContents.focus();
}

// -- 文書内検索（#325） ---------------------------------------------------------
// 検索欄（入力・トグル・件数）は、ツールバーの側（chrome.js）が持つ。ハイライトは、内容のビューのプリロードが、
// 表示中のDOMへ直接行う（生成したHTMLはscript-src 'none'で、ページ自身はスクリプトを持てないため）。
// ここ（メインプロセス）は、両者の間を、状態として仲立ちする。

/** 内容のビューへ送る、検索語一式。 */
function searchPayload() {
  return { query: state.search.query, regex: state.search.regex, caseSensitive: state.search.caseSensitive };
}

function setSearchOpen(open) {
  open = Boolean(open);
  if (open === state.search.open) return;   // Escが、複数の経路から二重に届いても、無害にする
  state.search = { ...state.search, open };
  if (open) {
    // 前回の検索語を覚えていれば、開いたときに、もう一度ハイライトする（ブラウザのCtrl+Fに合わせる）
    if (state.hasDocument && state.search.query) contentView.webContents.send('search-run', searchPayload());
  } else {
    state.search = { ...state.search, count: 0, current: 0, error: null };
    if (state.hasDocument) { contentView.webContents.send('search-clear'); contentView.webContents.focus(); }
  }
  push();
}

/** 検索語・正規表現/大文字小文字の切り替え。入力のたびに呼ばれる。 */
function setSearchQuery({ query, regex, caseSensitive }) {
  state.search = { ...state.search, query: String(query ?? ''), regex: Boolean(regex), caseSensitive: Boolean(caseSensitive) };
  if (state.hasDocument) contentView.webContents.send('search-run', searchPayload());
  else state.search = { ...state.search, count: 0, current: 0, error: null };
  push();
}

function moveSearch(delta) {
  if (state.hasDocument && state.search.count > 0) contentView.webContents.send('search-move', delta);
}

/** 内容のビューから届いた、検索結果（件数・現在位置・正規表現エラー）。 */
function onSearchResult({ count, current, error }) {
  state.search = { ...state.search, count, current, error: error ?? null };
  push();
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

/** 行番号バッジ（#328）の、オン・オフを、内容のビューへ伝える。文書は、スクリプトを持てないため、プリロードが、html要素の属性にする。 */
function sendLineBadge() {
  if (contentView && !contentView.webContents.isDestroyed()) contentView.webContents.send('line-badge', state.settings.lineBadge);
}

/** 設定を1つ変えて、すぐに反映し、保存する。想定外のキー・値は、無視する。 */
function changeSetting(key, value) {
  if (!EDITABLE.includes(key)) return;   // ウィンドウの状態などは、画面から変えさせない
  const next = normalizeSettings({ ...state.settings, [key]: value });
  if (next[key] !== value) return;
  state.settings = next;
  if (key === 'theme') applyTheme();
  if (key === 'autoReload') state.autoReload = next.autoReload;
  if (key === 'lineBadge') sendLineBadge();
  saveSettings(settingsFile, state.settings);
  layout();
  push();
}

function push() {
  state.isCsv = /\.csv$/i.test(state.file ?? '');
  state.canGoBack = history.canGoBack;
  state.canGoForward = history.canGoForward;
  const menu = Menu.getApplicationMenu();
  const backItem = menu?.getMenuItemById('go-back');
  if (backItem) backItem.enabled = state.canGoBack;
  const forwardItem = menu?.getMenuItemById('go-forward');
  if (forwardItem) forwardItem.enabled = state.canGoForward;
  // 「表示」メニューの、CSVの見出し行の項目は、.csvを開いているときだけ、有効にする
  const csvItem = menu?.getMenuItemById('csv-header');
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
    // Mermaid・Vega・Vega-Liteは、Pythonのplaywrightではなく、こちら（ElectronのChromium）で描画する（#207）
    launch.env = { ...launch.env, TEXT_COMPOSITOR_MERMAID_HOST: '1' };
    worker = new WorkerClient(launch, {
      services: {
        render_mermaid: (payload) => mermaidHost.render(payload),
        render_vega: (payload) => vegaHost.render(payload),
      },
    });
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
function openFile(file, { targetScrollY = null, historyNav = null } = {}) {
  const full = path.resolve(file);
  const target = checkOpenTarget(full);
  if (!target.ok) {
    state.diagnostics = summarize([{ severity: 'error', message: target.message }]);
    push();
    return;
  }
  // 履歴の戻る・進む移動では、ファイルを開くダイアログの初期フォルダ（lastDirectory）を書き換えない（#342レビュー指摘）
  if (!historyNav) rememberDirectory(path.dirname(full));
  queued = { file: full, targetScrollY, historyNav };
  if (!inFlight) void drain();
}

/** 開いたファイルのフォルダを覚える（ファイルを開くダイアログの、最初の場所）。変わったときだけ保存する。 */
function rememberDirectory(directory) {
  if (state.settings.lastDirectory === directory) return;
  state.settings = normalizeSettings({ ...state.settings, lastDirectory: directory });
  saveSettings(settingsFile, state.settings);
}

function reload() {
  leaveSettings();
  if (state.file) openFile(state.file);
}

async function drain() {
  inFlight = true;
  try {
    while (queued) {
      const task = queued;
      queued = null;
      await renderOnce(task.file, task.targetScrollY, task.historyNav);
    }
  } finally {
    inFlight = false;
    for (const resolve of idleWaiters.splice(0)) resolve();
  }
}

/** 変換が終わるまで待つ（変換中に、変換の材料を消さないため）。 */
function whenIdle() {
  return inFlight ? new Promise((resolve) => idleWaiters.push(resolve)) : Promise.resolve();
}

async function renderOnce(file, targetScrollY = null, historyNav = null) {
  const sameDocument = shown?.md === file;
  state.file = file;
  state.busy = true;
  state.status = '';
  push();

  let result;
  let fellBack = false;
  try {
    const client = await getWorker();
    // 既定では、HTMLと図のキャッシュを、アプリの領域に置く（原稿のフォルダには、何も書かない。#258）
    const location = workLocation(state.settings.workLocation, file, { root: workRoot });
    fellBack = location.fellBack;
    // plugins.structurizrは、text-compositor本体では既定false（内部で使うstructurizr-cliが重いため、#212）。
    // Obunzuは、Mermaid/PlantUML/D2と同じく常に有効にする（#290。同梱すれば追加取得なし、無くてもPlantUML/D2と同じ
    // ライブ取得にフォールバックするだけで、CLIのconfig.yamlのような「意図しない重い取得」への配慮は要らない）。
    result = await client.renderHtml({
      path: file, csv_header: state.settings.csvHeader, allow_external_images: state.settings.allowExternalImages,
      plugins: { structurizr: true }, ...location.params,
    });
  } catch (error) {
    if (error instanceof PythonNotFoundError) worker = null;
    // 想定外の例外でも、アプリを落とさず、原因を診断として見せる
    result = { ok: false, html: null, timings_ms: {}, diagnostics: [{ severity: 'error', message: error.message }] };
  }

  if (fellBack) {
    // 設定は「原稿の隣」でも、書き込めない場所の原稿は、開けないより、開けるほうがよい。切り替えたことを知らせる
    result.diagnostics = [...(result.diagnostics ?? []), { severity: 'warning', message: '原稿のフォルダに書き込めないため、変換したファイルを、アプリの領域に保存しました（設定は「原稿の隣」）', file }];
  }
  state.diagnostics = summarize(result.diagnostics);
  if (result.ok && result.html) {
    await showHtml(file, result.html, sameDocument, result.dependencies, targetScrollY);
    // 変換に成功して表示できた段階で、履歴の位置を更新する（#342レビュー指摘）。
    // 失敗したときはインデックスを動かさないため、ロールバックや永続的な食い違いが起きない。
    if (historyNav === 'back') {
      history.back();
    } else if (historyNav === 'forward') {
      history.forward();
    } else {
      history.push(file);
    }
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
async function showHtml(md, html, sameDocument, dependencies = [], targetScrollY = null) {
  const contents = contentView.webContents;
  const loaded = new Promise((resolve) => {
    const done = () => { contents.removeListener('did-finish-load', done); contents.removeListener('did-fail-load', done); resolve(); };
    contents.once('did-finish-load', done);
    contents.once('did-fail-load', done);
  });
  if (sameDocument && shown?.html === html) contents.reloadIgnoringCache();
  else contents.loadFile(html).catch(() => {});
  await loaded;
  if (targetScrollY !== null && targetScrollY > 0) {
    contents.executeJavaScript(`window.scrollTo(0, ${targetScrollY}); requestAnimationFrame(() => window.scrollTo(0, ${targetScrollY}));`).catch(() => {});
  }
  shown = { md, html, deps: dependencies };
  if (!state.hasDocument) { state.hasDocument = true; layout(); }
  // 表示し直すたび（自動更新を含む）、内容のビューは、プリロードから作り直される。検索語が残っていれば、
  // 新しいDOMへ、もう一度ハイライトを掛け直す（ハイライトは、内容のビュー側の状態のため、こちらでは持ち越せない）。
  if (state.search.open && state.search.query) contents.send('search-run', searchPayload());
  // 検索欄に入力中は、フォーカスを奪わない（自動更新中でも、続けて打てるように）
  if (!state.settingsOpen && !state.search.open) contents.focus();
}

// -- ナビゲーション・ズーム -------------------------------------------------------

/**
 * 戻る・進むナビゲーションを行う（#330）。
 * 到達可能性チェックはopenFileに任せ、ここではガードとキューイングのみを同期的に行う（#342レビュー指摘）。
 */
function navigateHistory(direction) {
  leaveSettings();
  if (inFlight || state.busy) return;
  const target = direction === 'back' ? history.peekBack() : history.peekForward();
  if (!target) return;
  openFile(target.file, { targetScrollY: target.scrollY, historyNav: direction });
}

function goBack() {
  navigateHistory('back');
}

function goForward() {
  navigateHistory('forward');
}

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
    defaultPath: openDialogDirectory(state.settings, app.getPath('documents')),   // 'os'のときは、undefined（OSにゆだねる）
    properties: ['openFile'],
    filters: openDialogFilters(),
  });
  if (!result.canceled && result.filePaths[0]) openFile(result.filePaths[0]);
}

/** 設定画面の「フォルダを選ぶ」。選んだフォルダを、「特定のフォルダ」として保存する。キャンセルしたときは、変えない。 */
async function chooseOpenDirectory() {
  const result = await dialog.showOpenDialog(win, {
    title: 'ファイルを開く場所',
    defaultPath: state.settings.fixedDirectory ?? app.getPath('documents'),
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return;
  state.settings = normalizeSettings({ ...state.settings, fixedDirectory: result.filePaths[0] });
  saveSettings(settingsFile, state.settings);
  push();
}

// -- 画像の保存（#327） ---------------------------------------------------------

function handleContextMenu(params) {
  if (params.mediaType !== 'image' || !params.srcURL) return;

  const template = buildImageContextMenuTemplate(params, {
    onSave: (p, format) => void saveImageFromContextMenu(p, format),
  });

  const menu = Menu.buildFromTemplate(template);
  menu.popup({ window: win });
}

async function saveImageFromContextMenu(params, requestedFormat) {
  try {
    const result = await executeSaveImage(params, requestedFormat, {
      win,
      documentFile: state.file,
      lastDirectory: state.settings.lastDirectory,
      downloadsDirectory: app.getPath('downloads'),
      showSaveDialog: (w, opts) => dialog.showSaveDialog(w, opts),
      createWindow: createHiddenWindow,
      netFetch: net.fetch,
    });
    if (result.saved && result.directory) {
      rememberDirectory(result.directory);
    }
  } catch (error) {
    state.diagnostics = summarize([{
      severity: 'error',
      message: `画像の保存に失敗しました: ${error.message}`,
    }]);
    push();
  }
}

// -- アプリの領域（変換したHTML・図のキャッシュ）の管理（#258） ----------------------------

/** 使用量を数えて、設定画面に出す。 */
async function refreshCacheUsage() {
  const usage = await cacheUsage(workRoot);
  state.cache = { ...state.cache, bytes: usage.bytes };
  push();
}

/**
 * 設定画面の「キャッシュを削除」。消すのは、アプリの領域の、HTMLと図のSVGだけ（原稿の隣の`.text-compositor/`は、
 * 利用者のフォルダのため、消さない）。表示中の文書は、HTMLと図のファイルを消したため、変換し直して、表示し直す。
 */
async function clearWorkCache() {
  if (state.cache.clearing) return;
  state.cache = { ...state.cache, clearing: true };
  push();
  try {
    await whenIdle();   // 変換中は、変換の材料を消さない
    await clearCache(workRoot);
  } catch (error) {
    state.diagnostics = summarize([{ severity: 'error', message: `キャッシュを削除できません: ${error.message}` }]);
  } finally {
    state.cache = { ...state.cache, clearing: false };
  }
  await refreshCacheUsage();
  if (state.file) openFile(state.file);   // 設定画面は、開いたままにする（reloadと違い、leaveSettingsは呼ばない）
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
        { id: 'go-back', label: '戻る', accelerator: 'Alt+Left', enabled: state.canGoBack, click: goBack },
        { label: '戻る', accelerator: 'CommandOrControl+[', enabled: state.canGoBack, click: goBack, visible: false },
        { id: 'go-forward', label: '進む', accelerator: 'Alt+Right', enabled: state.canGoForward, click: goForward },
        { label: '進む', accelerator: 'CommandOrControl+]', enabled: state.canGoForward, click: goForward, visible: false },
        { type: 'separator' },
        { label: '拡大', accelerator: 'CommandOrControl+Plus', click: () => zoomBy(1) },
        { label: '拡大', accelerator: 'CommandOrControl+=', click: () => zoomBy(1), visible: false },
        { label: '縮小', accelerator: 'CommandOrControl+-', click: () => zoomBy(-1) },
        { label: '実寸', accelerator: 'CommandOrControl+0', click: zoomReset },
        { type: 'separator' },
        { label: '検索…', accelerator: 'CommandOrControl+F', click: () => setSearchOpen(!state.search.open) },
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
ipcMain.on('content-scroll', (_event, scrollY) => {
  if (typeof scrollY === 'number' && Number.isFinite(scrollY)) {
    history.updateCurrentScroll(Math.max(0, Math.round(scrollY)));
  }
});
ipcMain.on('go-back', () => goBack());
ipcMain.on('go-forward', () => goForward());
ipcMain.on('reload', reload);
ipcMain.on('auto-reload', (_event, value) => setAutoReload(value));
ipcMain.on('csv-header', (_event, value) => setCsvHeader(value));
ipcMain.on('zoom', (_event, direction) => zoomBy(direction));
ipcMain.on('zoom-reset', zoomReset);
ipcMain.on('settings-toggle', () => setSettingsOpen(!state.settingsOpen));
ipcMain.on('settings-set', (_event, key, value) => changeSetting(key, value));
ipcMain.on('choose-open-directory', () => chooseOpenDirectory());
ipcMain.on('clear-cache', () => clearWorkCache());
// 行番号バッジのクリック（#328）。内容のビューからだけ、数字だけを、クリップボードへ入れる
ipcMain.on('copy-line-number', (event, text) => {
  if (event.sender === contentView?.webContents && /^\d{1,9}$/.test(String(text))) clipboard.writeText(String(text));
});
ipcMain.on('open-path', (_event, filePath) => { if (typeof filePath === 'string') { leaveSettings(); openFile(filePath); } });
ipcMain.on('search-toggle', () => setSearchOpen(!state.search.open));
ipcMain.on('search-close', () => setSearchOpen(false));
ipcMain.on('search-set', (_event, payload) => setSearchQuery(payload ?? {}));
ipcMain.on('search-move', (_event, delta) => moveSearch(delta));
ipcMain.on('search-result', (_event, result) => onSearchResult(result ?? {}));
