'use strict';
// Viewer（Electron）のメインプロセス（#190）。
//
// ウィンドウは、2つのビューでできている。
//   - ウィンドウ本体（chrome/）: ツールバー・エラーの帯・診断の一覧。
//   - 内容のビュー: ワーカーが作ったHTMLを表示する。Chromiumが、再読み込みで、スクロール位置を保つ。
// Markdownのファイルは、Pythonの常駐ワーカー（render_html）でHTMLにする。ワーカーが返した診断は、画面に出す。

const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow, Menu, WebContentsView, clipboard, dialog, ipcMain, nativeTheme, net, screen, session, shell } = require('electron');

const { summarize } = require('./diagnostics');
const { DocumentTab, tabsAffectedBy } = require('./document-tab');
const { buildImageContextMenuTemplate, executeSaveImage } = require('./image-save');
const { PythonNotFoundError, resolveWorkerLaunch } = require('./python');
const { DEFAULTS, EDITABLE, FEATURES, loadSettings, normalizeSettings, saveSettings } = require('./settings');
const { isInsideDirectory, listDirectory } = require('./directory-list');
const { buildProject, isInsideProject, isProjectConfigFile, projectEntries } = require('./project');
const { checkOpenTarget, classifyNavigation, fileFromArgv, resolveRelativeLink, openDialogDirectory, openDialogFilters } = require('./targets');
const { FileWatcher } = require('./watcher');
const { buildSelectionContextMenuTemplate } = require('./selection-menu');
const { chooseVoice, createSpeaker, rateOf } = require('./speech');
const { buildLineContextMenuTemplate, lineAtPointScript } = require('./line-ref');
const { buildLinkContextMenuTemplate, describeLink, headingLinkRef, linkAtPointScript } = require('./link-info');
const { MermaidHost } = require('./mermaid-host');
const { migrateLegacySettings } = require('./legacy-settings');
const { VegaHost } = require('./vega-host');
const { WaveDromHost } = require('./wavedrom-host');
const { BytefieldHost } = require('./bytefield-host');
const { cacheRoot, cacheUsage, clearCache, workLocation } = require('./workdir');
const { WorkerClient } = require('./worker-client');

// アプリケーション名（#194）。Observe（観察する）+ 文図（文章と図）の造語。
// AppUserModelIdは、Windowsのタスクバーの固定・通知が、このアプリとして扱われるための識別子。
const APP_NAME = 'Obunzu Markdown Viewer';
// ウィンドウのタイトルに、バージョン（package.jsonのversion）を添える。
const APP_TITLE = `${APP_NAME} ${app.getVersion()}`;
app.setAppUserModelId('io.github.tokudiro.obunzu-markdown-viewer');

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

// 環境変数 VIEWER_TREE_ROOT=<絶対パスのフォルダ> は、起動時に、ファイルツリー（#339）のルートを決める（確認用。
// 「フォルダを開く」のダイアログは、自動では操作できないため）。
const TREE_ROOT_FROM_ENV = process.env.VIEWER_TREE_ROOT && path.isAbsolute(process.env.VIEWER_TREE_ROOT)
  ? process.env.VIEWER_TREE_ROOT
  : null;

// 環境変数 VIEWER_TRACE=1 で、起動の各段階の時刻（プロセスの開始から）を、標準エラーへ出す。
const trace = process.env.VIEWER_TRACE
  ? (label) => process.stderr.write(`[viewer] ${label} +${Math.round(process.uptime() * 1000)}ms\n`)
  : () => {};

const SIDEBAR_WIDTH = 240;   // サイドバー（ファイルツリー。#339）の幅。いまは固定（幅の変更は、必要になってから）

// アプリ全体（ウィンドウ全体）の状態。文書ごとの状態（ファイル・履歴・診断・検索・内容のビューなど）は、
// `DocumentTab`が持つ（#332）。ウィンドウ本体（chrome/）へは、この2つを合わせて、1つの`state`として送る（`push`）。
// プロジェクトモード（#373）の、章の一覧（project.jsのbuildProjectの結果）。stateには入れない（章が多くても、毎回の画面への通知を重くしない。
// 画面は、`list-directory`の依頼で、必要な見出しだけを読む）。
let project = null;

const state = {
  zoomPercent: 100,
  autoReload: DEFAULTS.autoReload,   // 原稿・参照ファイルの保存を検知して、自動で更新する（#170）。設定として保存する
  settingsOpen: false,   // 設定画面を開いているとき、内容のビューを隠して、設定を表示する（#200）
  settings: { ...DEFAULTS },
  sidebarWidth: SIDEBAR_WIDTH,   // 画面（chrome/）が、サイドバーの幅を、CSSに使う。
  // サイドバーを開いているか。覚えない（#373）。ルートを決めたら、開く。手動で閉じたら、そのルートの間は、閉じたまま。
  // 起動直後は、ルートが無い（単一ファイルモード）ため、閉じている。
  sidebarOpen: TREE_ROOT_FROM_ENV !== null,
  // サイドバーのモード（#373）。root: ルートのフォルダ。kind: null（単一ファイル。ルートなし）| 'folder'（フォルダ。
  // 「フォルダを開く」）。モードは、「いま開いているファイル」ではなく、ルートの開き方で決める。覚えない（起動のたびに、単一ファイルから）。
  // kind: 'project'（設定ファイルの章。「ファイルを開く」で設定ファイルを選ぶ。#373）のとき、root は設定ファイルのパス。
  tree: { root: TREE_ROOT_FROM_ENV, kind: TREE_ROOT_FROM_ENV ? 'folder' : null },
  features: FEATURES.map(({ key, label, description, on, off }) => ({ key, label, description, on, off })),   // 設定画面の「表示する機能」の行を作る材料（#326）
  speech: { supported: process.platform === 'win32', voices: [] },   // 読み上げ（#430）。設定画面の、声の選択肢の材料
  cache: { bytes: null, clearing: false },   // アプリの領域（変換したHTML・図のキャッシュ）の使用量。設定画面を開いたときに数える（#258）
};

// タブ（#332）。`tab`は、いま見ているタブ。設定「複数のタブ」がオフの間は、タブは常に1つ。
// 変換のような、await をまたぐ処理は、途中でタブが切り替わっても、始めたタブに書き込めるよう、タブを引数で受ける。
const tabs = [];
let tab = null;
let nextTabId = 1;

let settingsFile = null;

let win = null;
let chromeHeight = 40;
let zoomLevel = 0;
let worker = null;
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
const wavedromHost = new WaveDromHost({ createWindow: createHiddenWindow });   // WaveDrom（#392）
const bytefieldHost = new BytefieldHost({ createWindow: createHiddenWindow });   // Bytefield-svg（#300）

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
    if (file) openTarget(file);
  });

  app.whenReady().then(() => {
    trace('app-ready');
    // 改名（#394）の前の設定を、新しい置き場所へ、1回だけ引き継ぐ。
    // --user-data-dir を渡された起動は、確認スクリプト用の隔離環境とみなして引き継がない（#423）。
    // 旧名の置き場所は実環境のappDataのため、引き継ぐと確認の結果が実行する人の設定に左右される。
    if (!app.commandLine.hasSwitch('user-data-dir')) {
      migrateLegacySettings({ userData: app.getPath('userData'), appData: app.getPath('appData') });
    }
    settingsFile = path.join(app.getPath('userData'), 'settings.json');
    state.settings = loadSettings(settingsFile);
    state.autoReload = state.settings.autoReload;
    applyTheme();
    createWindow();
    watcher = new FileWatcher({ onChange: onFilesChanged });
    Menu.setApplicationMenu(buildMenu());
    startWorker();
    const file = targetFromArgv(process.argv, process.cwd());
    if (file) openTarget(file);
  });
}

app.on('window-all-closed', () => app.quit());

// 選択範囲の読み上げ（#430）。読み上げているのは、同時に1つだけ。始めたタブを覚え、そのタブの文書が替わる・タブを閉じる・終了するときに止める。
const speaker = createSpeaker();
let speechTab = null;

// 設定画面に出す、OSの日本語の声の一覧。起動時に1回、裏で取得する（PowerShellの起動に、少し時間がかかるため）。
// 声の名前は、環境で違うため、コードに固定しない。
speaker.listVoices().then((voices) => {
  state.speech.voices = voices;
  if (win && tab) push();
});

function stopSpeech({ wait = false } = {}) {
  speaker.stop({ wait });
  speechTab = null;
}

async function speakSelection(origin, text) {
  // 声は、設定の声（OSに無ければ、日本語の声の先頭）。速さは、設定の3段階。一覧は、起動時に取得済み。
  const voices = state.speech.voices.length > 0 ? state.speech.voices : await speaker.listVoices();
  const voice = chooseVoice(state.settings.speechVoice, voices);
  if (speaker.speak(text, { voice, rate: rateOf(state.settings.speechRate) })) speechTab = origin;
}

let quitting = false;
app.on('before-quit', (event) => {
  stopSpeech({ wait: true });
  watcher?.close();
  mermaidHost.dispose();
  vegaHost.dispose();
  wavedromHost.dispose();
  bytefieldHost.dispose();
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

  // 二重の防御（方針2章・#238）: 変換側（Python、既定で外部画像をプレースホルダに置き換える）に漏れがあっても、
  // http/httpsの通信そのものを、ここで止める。allowExternalImages（設定で許可）のときだけ、通す。
  // 内容のビューは、すべて、同じ既定のセッションを使うため、1回だけ設定する。
  session.defaultSession.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] },
    (_details, callback) => callback({ cancel: !state.settings.allowExternalImages }));

  tab = createTab();

  if (saved.maximized) win.maximize();
  win.on('resize', () => { layout(); scheduleWindowSave(); });
  win.on('move', scheduleWindowSave);
  win.on('maximize', scheduleWindowSave);
  win.on('unmaximize', scheduleWindowSave);
  win.on('close', saveWindowNow);
  // 非表示のMermaidのウィンドウが残ると、'window-all-closed'が発火せず、アプリが終了しない
  win.on('closed', () => { stopSpeech({ wait: true }); mermaidHost.dispose(); vegaHost.dispose(); wavedromHost.dispose(); bytefieldHost.dispose(); });
  handleEscape(win.webContents);
  // フォーカスが、どちらのビューにあるかを覚える（F6の切り替えに使う。`isFocused()`は、子のビューとの関係で、当てにならないため。#340）
  win.webContents.on('focus', () => { focusedArea = 'toolbar'; });
  handleNavigationShortcuts(win.webContents);
  win.on('app-command', (_event, cmd) => {
    if (cmd === 'browser-backward') goBack();
    else if (cmd === 'browser-forward') goForward();
  });
  nativeTheme.on('updated', applyBackground);
  layout();
  trace('window-created');
}

/**
 * タブを1つ作る（#332）。内容のビューは、タブごとに持つ（スクロール位置・検索のハイライトが、切り替えても保たれる）。
 * HTMLは、生成したもので、スクリプトを含まず、CSPでスクリプトを禁止している。
 * JavaScriptを有効にしているのは、ドロップの受け口（プリロード）を動かすため（無効だと、プリロードも動かない）。
 */
function createTab() {
  const created = new DocumentTab(nextTabId++);
  const background = nativeTheme.shouldUseDarkColors ? '#0d1117' : '#ffffff';
  created.contentView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, 'chrome', 'content-preload.js'),   // ドロップの受け口・検索・コピーなど
      sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: true,
    },
  });
  created.contentView.setBackgroundColor(background);
  win.contentView.addChildView(created.contentView);
  tabs.push(created);

  const contents = created.contentView.webContents;
  // content-preload.jsは、ドラッグ＆ドロップだけでなく、検索（#325）も持つようになった。失敗しても画面は白いままで
  // 気づけないため、標準エラーへ出す（サンドボックス化したプリロードは、electron以外のローカルファイルを
  // requireできない、という実測を、この行で見つけた）。
  contents.on('preload-error', (_e, path, error) => process.stderr.write(`[preload-error] ${path}: ${error.stack || error}\n`));
  contents.setWindowOpenHandler(({ url }) => { handleNavigation(url, created); return { action: 'deny' }; });
  // ドロップ・リンクで、アプリの表示が、他のページへ遷移してしまわないようにする
  contents.on('will-navigate', (event, url) => { event.preventDefault(); handleNavigation(url, created); });
  contents.on('zoom-changed', (_event, direction) => zoomBy(direction === 'in' ? 1 : -1));
  contents.on('did-finish-load', () => {
    contents.setZoomLevel(zoomLevel);
    resetLine(created);
    sendLineIndicator(created);
    sendContentFeatures(created);
  });
  contents.on('context-menu', (_event, params) => { void handleContextMenu(created, params); });
  handleEscape(contents);
  contents.on('focus', () => { if (created === tab) focusedArea = 'content'; });
  handleNavigationShortcuts(contents);
  return created;
}

/** 内容のビューを、ツールバーの下（サイドバーを開いているときは、その右）に置く。文書がまだ無いときは、大きさ0にして、案内の表示を隠さない。見ていないタブは、隠す。 */
function layout() {
  if (!win || !tab?.contentView) return;
  const [windowWidth, height] = win.getContentSize();
  const x = sidebarShown() ? Math.min(SIDEBAR_WIDTH, windowWidth) : 0;
  const width = windowWidth - x;
  // ツールバーが下のときは、内容が、画面の上端から始まる（帯・一覧も、ツールバーの側に、まとまる）
  const y = state.settings.toolbarPosition === 'bottom' ? 0 : chromeHeight;
  for (const other of tabs) {
    // 設定画面を開いている間も、内容のビューを隠す（設定は、ウィンドウ本体の側に表示するため）
    const visible = other === tab && other.hasDocument && !state.settingsOpen;
    other.contentView.setBounds(visible
      ? { x, y, width, height: Math.max(0, height - chromeHeight) }
      : { x: 0, y, width: 0, height: 0 });
    other.contentView.setVisible(visible);
  }
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
    } else if (tab.search.open) {
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
  for (const each of tabs) each.contentView?.setBackgroundColor(background);
}

/** サイドバーが、いま画面に出ているか。設定「ファイルツリー」がオンで、開いているとき。 */
function sidebarShown() {
  return state.settings.showFileTree && state.sidebarOpen;
}

/** サイドバーを開閉する（#339）。開閉は、覚えない（#373）。設定画面を開いている間は、サイドバーも隠れるが、開閉の状態は変えない。 */
function setSidebarOpen(open) {
  if (!state.settings.showFileTree) return;   // 設定「ファイルツリー」が「出さない」のとき、サイドバーは使えない
  if (state.sidebarOpen === Boolean(open)) return;
  state.sidebarOpen = Boolean(open);
  layout();
  push();
}

/** ルート（サイドバーのモード）を決める。決めたら、サイドバーを開く（#373）。 */
function enterRoot(root, kind) {
  // version: 同じ設定ファイルを開き直したとき、画面が、一覧を読み直すための印（章を書き換えた後でも、古い一覧が残らない）
  state.tree = { root, kind, version: (state.tree.version ?? 0) + 1 };
  state.sidebarOpen = true;
  layout();
  push();
}

/** `file`が、いまのルートの中か。フォルダモードは、フォルダの中。プロジェクトモードは、章か設定ファイル自身。 */
function isInsideRoot(file) {
  if (state.tree.kind === 'project') return isInsideProject(project, file);
  return isInsideDirectory(state.tree.root, path.dirname(file));
}

/** ルートを手放し、単一ファイルモードへ戻る。サイドバーは閉じる（`Ctrl+B`で、案内つきの空のサイドバーを開ける）。 */
function leaveRoot() {
  if (state.tree.root === null) return;
  project = null;
  state.tree = { root: null, kind: null };
  state.sidebarOpen = false;
  updateWatch();   // プロジェクトの設定ファイルの監視を、やめる
  layout();
  push();
}

function setSettingsOpen(open) {
  state.settingsOpen = Boolean(open);
  layout();
  push();
  // 開いたら、フォーカスを設定画面（ウィンドウ本体）へ移す。文書に残ったままだと、隠れた文書がキーを受けて、
  // Escで閉じられない（実測）。閉じたら、文書へ戻す（スクロール・キー操作が、そのまま使える）。
  if (state.settingsOpen) { win.webContents.focus(); void refreshCacheUsage(); }
  else if (tab.hasDocument) tab.contentView.webContents.focus();
}

// -- 文書内検索（#325） ---------------------------------------------------------
// 検索欄（入力・トグル・件数）は、ツールバーの側（chrome.js）が持つ。ハイライトは、内容のビューのプリロードが、
// 表示中のDOMへ直接行う（生成したHTMLはscript-src 'none'で、ページ自身はスクリプトを持てないため）。
// ここ（メインプロセス）は、両者の間を、状態として仲立ちする。

/** 内容のビューへ送る、検索語一式。 */
function searchPayload(target = tab) {
  return { query: target.search.query, regex: target.search.regex, caseSensitive: target.search.caseSensitive };
}

/**
 * F6で、フォーカスを、ツールバー（ウィンドウ本体のビュー）と、文書（内容のビュー）の間で、行き来させる（#340）。
 * 2つは、別のビューで、Tabでは、行き来できない。キーボードだけで、ツールバーのボタンに届くようにするため。
 * 設定画面・検索欄を開いているときは、ウィンドウ本体のビューの中だけで操作するため、何もしない。
 */
let focusedArea = 'content';

function toggleFocusArea() {
  if (!win || state.settingsOpen) return;
  // 文書にフォーカスがあるときは、ツールバーへ。それ以外（ツールバーなど）は、文書へ
  if (!tab.hasDocument || focusedArea === 'content') {
    focusedArea = 'toolbar';   // プログラムからのfocus()では、'focus'のイベントが来ないことがあるため、ここでも、覚える
    win.webContents.focus();
    // 最初の操作できるボタンへ。文書が無いときは、「開く」
    void win.webContents.executeJavaScript(
      "(document.querySelector('#toolbar button:not(:disabled):not([hidden])') ?? document.getElementById('empty-open'))?.focus()").catch(() => {});
  } else {
    focusedArea = 'content';
    tab.contentView.webContents.focus();
  }
}

function setSearchOpen(open) {
  open = Boolean(open);
  if (open === tab.search.open) return;   // Escが、複数の経路から二重に届いても、無害にする
  tab.search = { ...tab.search, open };
  if (open) {
    // 前回の検索語を覚えていれば、開いたときに、もう一度ハイライトする（ブラウザのCtrl+Fに合わせる）
    if (tab.hasDocument && tab.search.query) tab.contentView.webContents.send('search-run', searchPayload());
  } else {
    tab.search = { ...tab.search, count: 0, current: 0, error: null };
    if (tab.hasDocument) { tab.contentView.webContents.send('search-clear'); tab.contentView.webContents.focus(); }
  }
  push();
}

/**
 * 右クリックの「選択範囲で検索」（#429）。検索欄を開き、選んだ文字を検索語にして、検索する。
 * 選んだ文字は、そのまま探したいため、正規表現はオフにする。`queryRevision`を進めて、すでに開いている検索欄の入力も、そろえさせる。
 */
function searchForSelection(origin, term) {
  if (origin !== tab || !origin.hasDocument) return;
  setSearchOpen(true);
  tab.search = { ...tab.search, queryRevision: (tab.search.queryRevision ?? 0) + 1 };
  setSearchQuery({ query: term, regex: false, caseSensitive: tab.search.caseSensitive });
}

/** 検索語・正規表現/大文字小文字の切り替え。入力のたびに呼ばれる。 */
function setSearchQuery({ query, regex, caseSensitive }) {
  tab.search = { ...tab.search, query: String(query ?? ''), regex: Boolean(regex), caseSensitive: Boolean(caseSensitive) };
  if (tab.hasDocument) tab.contentView.webContents.send('search-run', searchPayload());
  else tab.search = { ...tab.search, count: 0, current: 0, error: null };
  push();
}

function moveSearch(delta) {
  if (tab.hasDocument && tab.search.count > 0) tab.contentView.webContents.send('search-move', delta);
}

/** 内容のビューから届いた、検索結果（件数・現在位置・正規表現エラー）。 */
function onSearchResult(origin, { count, current, error }) {
  if (!origin) return;
  origin.search = { ...origin.search, count, current, error: error ?? null };
  if (origin === tab) push();
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

/** 行番号の表示（#328）の、オン・オフを、内容のビューへ伝える。オンのときだけ、プリロードが、乗せたブロックの行を送ってくる。 */
/** 見出しのリンク（#337）・コードのコピーボタン（#336）の、オン・オフを、内容のビューへ伝える。表示・操作は、プリロードが行う。 */
function sendContentFeatures(target) {
  if (!target.contentView || target.contentView.webContents.isDestroyed()) return;
  target.contentView.webContents.send('content-features', {
    headingAnchor: state.settings.showHeadingAnchor,
    codeCopy: state.settings.showCodeCopy,
  });
}

function sendLineIndicator(target) {
  if (target.contentView && !target.contentView.webContents.isDestroyed()) target.contentView.webContents.send('line-indicator', state.settings.showLineNumber);
}

/** 行番号を消す。文書を表示し直したとき（自動更新を含む）と、表示をオフにしたとき。行が、ずれているかもしれないため。 */
function resetLine(target) {
  if (target.line === null) return;
  target.line = null;
  if (target === tab) push();
}

/** 設定を1つ変えて、すぐに反映し、保存する。想定外のキー・値は、無視する。 */
function changeSetting(key, value) {
  if (!EDITABLE.includes(key)) return;   // ウィンドウの状態などは、画面から変えさせない
  const next = normalizeSettings({ ...state.settings, [key]: value });
  if (next[key] !== value) return;
  state.settings = next;
  if (key === 'theme') applyTheme();
  if (key === 'autoReload') state.autoReload = next.autoReload;
  if (key === 'showLineNumber') for (const each of tabs) { resetLine(each); sendLineIndicator(each); }
  if (key === 'showHeadingAnchor' || key === 'showCodeCopy') for (const each of tabs) sendContentFeatures(each);
  if (key === 'showFileTree' && !next.showFileTree) { project = null; state.tree = { root: null, kind: null }; state.sidebarOpen = false; updateWatch(); }   // 「出さない」にしたら、開いていたフォルダも、手放す
  if (key === 'enableTabs' && !next.enableTabs) closeOtherTabs();   // 「使わない」にしたら、いま見ているタブだけを残す
  saveSettings(settingsFile, state.settings);
  layout();
  push();
}

function push() {
  const menu = Menu.getApplicationMenu();
  const backItem = menu?.getMenuItemById('go-back');
  if (backItem) backItem.enabled = tab.canGoBack;
  const forwardItem = menu?.getMenuItemById('go-forward');
  if (forwardItem) forwardItem.enabled = tab.canGoForward;
  // 「表示」メニューの、CSVの見出し行の項目は、.csvを開いているときだけ、有効にする
  const csvItem = menu?.getMenuItemById('csv-header');
  if (csvItem) { csvItem.enabled = tab.isCsv; csvItem.checked = state.settings.csvHeader; }
  // ファイルツリーの入口は、設定「ファイルツリー」がオンのときだけ出す（#339）
  for (const id of ['open-folder', 'toggle-sidebar']) {
    const item = menu?.getMenuItemById(id);
    if (item) item.visible = state.settings.showFileTree;
  }
  // タブの操作は、設定「複数のタブ」がオンのときだけ使える（#332）
  for (const [id, enabled] of [['new-tab', true], ['close-tab', tabs.length > 1], ['next-tab', tabs.length > 1], ['previous-tab', tabs.length > 1]]) {
    const item = menu?.getMenuItemById(id);
    if (item) item.enabled = state.settings.enableTabs && enabled;
  }
  if (win && !win.isDestroyed()) {
    const tabList = tabs.map((each) => ({ ...each.summary(), active: each === tab }));
    win.webContents.send('state', { ...state, ...tab.snapshot(), tabs: tabList });
  }
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
      tab.diagnostics = summarize([{ severity: 'error', message: error.message }]);
      tab.status = 'Pythonのワーカーを起動できません';
      push();
    });
}

async function getWorker() {
  if (!worker) {
    // 見つからない場合は、キャッシュせず、次の依頼でも、探し直す（環境変数を直した後に、再試行できるように）
    const launch = resolveWorkerLaunch(appDirectory());
    // Mermaid・Vega・Vega-Lite・WaveDrom・Bytefieldは、Pythonのplaywrightではなく、こちら（ElectronのChromium）で描画する（#207）
    launch.env = { ...launch.env, TEXT_COMPOSITOR_MERMAID_HOST: '1' };
    worker = new WorkerClient(launch, {
      services: {
        render_mermaid: (payload) => mermaidHost.render(payload),
        render_vega: (payload) => vegaHost.render(payload),
        render_wavedrom: (payload) => wavedromHost.render(payload),
        render_bytefield: (payload) => bytefieldHost.render(payload),
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
/** ファイルを開く。変換中に、次の依頼が来たときは、最後の依頼だけを残す。開く先は、指定がなければ、いま見ているタブ。 */
function openFile(file, { targetScrollY = null, historyNav = null, fragment = null, notices = [] } = {}, target = tab) {
  const full = path.resolve(file);
  const check = checkOpenTarget(full);
  if (!check.ok) {
    target.diagnostics = summarize([{ severity: 'error', message: check.message }]);
    push();
    return;
  }
  // ルートの外のファイルを開いたら、単一ファイルモードへ戻る（#373）。ルートの中なら、モードを保つ（サイドバーの
  // クリック・相対リンク）。開けない対象（上のcheck）では、モードを変えない。
  if (state.tree.root !== null && !isInsideRoot(full)) leaveRoot();
  // 履歴の戻る・進む移動では、ファイルを開くダイアログの初期フォルダ（lastDirectory）を書き換えない（#342レビュー指摘）
  if (!historyNav) rememberDirectory(path.dirname(full));
  target.queued = { file: full, targetScrollY, historyNav, fragment, notices };
  if (!target.inFlight) void drain(target);
}

/** 開いたファイルのフォルダを覚える（ファイルを開くダイアログの、最初の場所）。変わったときだけ保存する。 */
function rememberDirectory(directory) {
  if (state.settings.lastDirectory === directory) return;
  state.settings = normalizeSettings({ ...state.settings, lastDirectory: directory });
  saveSettings(settingsFile, state.settings);
}

function reload() {
  leaveSettings();
  if (tab.file) openFile(tab.file);
}

async function drain(target) {
  target.inFlight = true;
  try {
    while (target.queued) {
      const task = target.queued;
      target.queued = null;
      await renderOnce(target, task.file, task.targetScrollY, task.historyNav, task.fragment, task.notices);
    }
  } finally {
    target.inFlight = false;
    target.releaseIdleWaiters();
  }
}

/** どのタブも、変換が終わるまで待つ（変換中に、変換の材料を消さないため）。 */
function whenIdle() {
  return Promise.all(tabs.map((each) => each.whenIdle()));
}

async function renderOnce(target, file, targetScrollY = null, historyNav = null, fragment = null, notices = []) {
  const sameDocument = target.shown?.md === file;
  target.file = file;
  target.busy = true;
  target.status = '';
  // 変換の前から原稿を監視する。末尾でしか登録しないと、最初の変換中に保存されたとき、通知を取りこぼし、
  // 古い表示のまま止まる（見ていないタブでは、特に起きやすい。#424）。保存を検知すると、キューで再変換される。
  updateWatch();
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
    // ワーカーは、全タブで1つ。変換は、1件ずつ順に処理される（#332）。
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
  // 開く前に分かった注意（章の一覧の誤りなど。#373）は、変換の診断の前に並べる
  target.diagnostics = summarize([...notices, ...result.diagnostics]);
  if (target.closed) return;   // 変換の途中で、タブが閉じられた
  if (result.ok && result.html) {
    await showHtml(target, file, result.html, sameDocument, result.dependencies, targetScrollY, fragment);
    // 変換に成功して表示できた段階で、履歴の位置を更新する（#342レビュー指摘）。
    // 失敗したときはインデックスを動かさないため、ロールバックや永続的な食い違いが起きない。
    if (historyNav === 'back') {
      target.history.back();
    } else if (historyNav === 'forward') {
      target.history.forward();
    } else {
      target.history.push(file);
    }
    const total = result.timings_ms.total;
    // 警告の件数は、帯に出るため、状態の表示には、入れない（同じ内容を2か所に出さない）
    target.status = `${clock()} ${total !== undefined ? `更新 ${Math.round(total)} ms` : '更新済み'}`;
    if (target === tab) win?.setTitle(`${path.basename(file)} - ${APP_TITLE}`);
    trace('content-shown');
  } else {
    // 失敗しても、直前に成功した表示を残す。ファイル名も、表示中の文書に戻す。
    target.file = target.shown ? target.shown.md : file;
    target.status = target.shown ? '変換に失敗しました。前回の成功した表示を残しています' : '変換に失敗しました';
  }
  target.busy = false;
  updateWatch();
  push();
}

/**
 * 監視するファイルを、全タブの原稿と、その参照ファイルにする。変換に失敗しても、原稿は監視し続ける
 * （直して保存したときに、自動で更新できるように）。
 */
function updateWatch() {
  if (!watcher) return;
  // プロジェクトモード（#373）では、設定ファイルも監視する（章の並びの変更を、一覧へ反映するため）
  watcher.setFiles([...tabs.flatMap((each) => each.watchedFiles), ...(state.tree.kind === 'project' ? [state.tree.root] : [])]);
}

/** 監視しているファイルが、保存された。自動更新が有効なら、そのファイルを開いているタブを、もう一度変換する。 */
async function onFilesChanged(paths) {
  trace(`changed ${paths.length}`);
  if (!state.autoReload) return;
  if (state.tree.kind === 'project' && paths.includes(state.tree.root)) void refreshProject();   // 監視は、解決済みの絶対パスで登録するため、そのまま比べられる
  for (const each of tabsAffectedBy(tabs, paths)) {
    const target = each.file;
    // エディタの原子的な保存の途中で、原稿が、一時的に無いことがある。短く待つ。
    for (let i = 0; i < 10 && !fs.existsSync(target); i++) await new Promise((resolve) => setTimeout(resolve, 100));
    if (!each.closed && each.file === target && fs.existsSync(target)) openFile(target, {}, each);
  }
}

/** .csvの1行目を、見出し行にするか（#220）。設定として覚え、開いているCSVを、表示し直す（スクロール位置は、保たれる）。 */
function setCsvHeader(value) {
  changeSetting('csvHeader', Boolean(value));
  for (const each of tabs) if (each.isCsv && each.file) openFile(each.file, {}, each);
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
async function showHtml(target, md, html, sameDocument, dependencies = [], targetScrollY = null, fragment = null) {
  const contents = target.contentView.webContents;
  if (!sameDocument && speechTab === target) stopSpeech();
  const loaded = new Promise((resolve) => {
    const done = () => { contents.removeListener('did-finish-load', done); contents.removeListener('did-fail-load', done); resolve(); };
    contents.once('did-finish-load', done);
    contents.once('did-fail-load', done);
  });
  if (sameDocument && target.shown?.html === html) contents.reloadIgnoringCache();
  else contents.loadFile(html).catch(() => {});
  await loaded;
  if (targetScrollY !== null && targetScrollY > 0) {
    contents.executeJavaScript(`window.scrollTo(0, ${targetScrollY}); requestAnimationFrame(() => window.scrollTo(0, ${targetScrollY}));`).catch(() => {});
  }
  // `other.md#見出し`のリンクで開いたときは、その見出しへ（#361）
  if (fragment) {
    contents.executeJavaScript(`document.getElementById(${JSON.stringify(fragment)})?.scrollIntoView()`).catch(() => {});
  }
  target.shown = { md, html, deps: dependencies };
  if (!target.hasDocument) { target.hasDocument = true; layout(); }
  // 表示し直すたび（自動更新を含む）、内容のビューは、プリロードから作り直される。検索語が残っていれば、
  // 新しいDOMへ、もう一度ハイライトを掛け直す（ハイライトは、内容のビュー側の状態のため、こちらでは持ち越せない）。
  if (target.search.open && target.search.query) contents.send('search-run', searchPayload(target));
  // 検索欄に入力中は、フォーカスを奪わない（自動更新中でも、続けて打てるように）。見ていないタブも、奪わない
  if (target === tab && !state.settingsOpen && !target.search.open) contents.focus();
}

// -- ナビゲーション・ズーム -------------------------------------------------------

/**
 * 戻る・進むナビゲーションを行う（#330）。
 * 到達可能性チェックはopenFileに任せ、ここではガードとキューイングのみを同期的に行う（#342レビュー指摘）。
 */
function navigateHistory(direction) {
  leaveSettings();
  if (tab.inFlight || tab.busy) return;
  const target = direction === 'back' ? tab.history.peekBack() : tab.history.peekForward();
  if (!target) return;
  openFile(target.file, { targetScrollY: target.scrollY, historyNav: direction });
}

function goBack() {
  navigateHistory('back');
}

function goForward() {
  navigateHistory('forward');
}

/** リンク・ドロップ（`origin`のタブの内容のビューから）。Markdownなどは、そのタブで開く。 */
function handleNavigation(url, origin = tab) {
  const target = classifyNavigation(url);
  if (target.type === 'external') shell.openExternal(target.url);
  else if (target.type === 'open') openFile(target.path, {}, origin);
}

/** 文書内の相対リンクを、原稿のフォルダを基準に開く（#361）。 */
function handleRelativeLink(href, origin = tab) {
  const target = origin.file ? resolveRelativeLink(href, origin.file) : null;
  if (target) openFile(target.path, { fragment: target.fragment }, origin);
}

function zoomBy(delta) {
  zoomLevel = Math.min(5, Math.max(-3, zoomLevel + delta * 0.5));
  for (const each of tabs) each.contentView?.webContents.setZoomLevel(zoomLevel);
  state.zoomPercent = Math.round(Math.pow(1.2, zoomLevel) * 100);
  push();
}

function zoomReset() {
  zoomLevel = 0;
  for (const each of tabs) each.contentView?.webContents.setZoomLevel(0);
  state.zoomPercent = 100;
  push();
}

/** ファイルを開くダイアログ。選んだファイルを返す（キャンセルは、null）。 */
async function chooseFileToOpen() {
  leaveSettings();
  const result = await dialog.showOpenDialog(win, {
    title: 'ファイルを開く',
    defaultPath: openDialogDirectory(state.settings, app.getPath('documents')),   // 'os'のときは、undefined（OSにゆだねる）
    properties: ['openFile'],
    filters: openDialogFilters(),
  });
  return !result.canceled && result.filePaths[0] ? result.filePaths[0] : null;
}

async function openWithDialog() {
  const file = await chooseFileToOpen();
  if (file) openTarget(file);
}

/** 「フォルダを開く」（#339）。選んだフォルダを、サイドバーのファイルツリーのルートにして、サイドバーを開く。キャンセルしたときは、変えない。 */
async function openFolder() {
  if (!state.settings.showFileTree) return;
  leaveSettings();
  const result = await dialog.showOpenDialog(win, {
    title: 'フォルダを開く',
    defaultPath: state.tree.root ?? openDialogDirectory(state.settings, app.getPath('documents')),
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return;
  enterRoot(result.filePaths[0], 'folder');
}

/** ファイルツリーが読んでよいフォルダか。ルートの中（ルート自身を含む）だけ。画面からの依頼で、無関係な場所を、一覧させない。 */
function isInsideTreeRoot(directory) {
  return state.settings.showFileTree && state.tree.kind === 'folder' && isInsideDirectory(state.tree.root, directory);
}

/**
 * ファイルを開く入口（ダイアログ・ドロップ・コマンドライン引数）。設定ファイルの名前なら、プロジェクトモードで開く（#373）。
 * サイドバーの項目のクリック・相対リンクは、ここを通さない（クリックで、モードを変えないため）。
 */
function openTarget(file) {
  if (state.settings.showFileTree && isProjectConfigFile(file)) void openProject(path.resolve(file));
  else openFile(file);
}

/**
 * 設定ファイルを、プロジェクトとして開く（#373）。章の一覧を、ワーカーに1回だけ問い合わせ、サイドバーに出す。
 * 本文には、設定ファイルのソースを出す。一覧を作れなかった（設定の誤り）ときは、サイドバーは出さず、本文に、案内を添える。
 */
async function openProject(configPath) {
  leaveSettings();
  const { built, notices } = await loadProject(configPath);
  if (built) {
    project = built;
    enterRoot(configPath, 'project');
    updateWatch();   // 設定ファイルの変更を検知して、一覧を更新する
  } else {
    leaveRoot();
  }
  openFile(configPath, { notices });
}

/** 設定ファイルから、章の一覧を作る。作れなかったとき（設定の誤り）は、`built`が`null`で、理由が、`notices`に入る。 */
async function loadProject(configPath) {
  const notices = [];
  try {
    const client = await getWorker();
    const { items, warnings } = await client.listChapters(configPath);
    for (const message of warnings) notices.push({ severity: 'warning', message: `章の一覧: ${message}`, file: configPath });
    return { built: buildProject(configPath, items), notices };
  } catch (error) {
    const reason = error.code === 'bad_config' ? error.message.replace(/^bad_config: /, '') : error.message;
    notices.push({ severity: 'warning', message: `章の一覧を作れません: ${reason}`, file: configPath });
    return { built: null, notices };
  }
}

/**
 * 設定ファイルが保存されたとき、章の一覧を作り直す（#373）。読めなかった（編集の途中で、構文が壊れている）ときは、
 * 前の一覧を残す（直して保存すれば、また更新される）。待っている間に、プロジェクトを離れていたら、何もしない。
 */
async function refreshProject() {
  const configPath = state.tree.kind === 'project' ? state.tree.root : null;
  if (!configPath) return;
  const { built } = await loadProject(configPath);
  if (!built || state.tree.kind !== 'project' || state.tree.root !== configPath) return;
  project = built;
  state.tree = { ...state.tree, version: (state.tree.version ?? 0) + 1 };
  updateWatch();
  push();
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

// -- タブ（#332） -----------------------------------------------------------------

/** 見ているタブを切り替える。見ていたタブの内容のビューは、隠す（スクロール位置・検索のハイライトは、そのまま残る）。 */
function activateTab(target) {
  if (!target || target === tab || target.closed) return;
  tab = target;
  focusedArea = 'content';
  layout();
  win?.setTitle(tab.file ? `${path.basename(tab.file)} - ${APP_TITLE}` : APP_TITLE);
  push();
  if (!state.settingsOpen && tab.hasDocument) tab.contentView.webContents.focus();
}

/** 「新しいタブで開く」。ファイルを選んでから、タブを作る（キャンセルしたときは、タブを増やさない）。 */
async function openInNewTab(file = null) {
  if (!state.settings.enableTabs) return;
  const chosen = file ?? await chooseFileToOpen();
  if (!chosen) return;
  const created = createTab();
  activateTab(created);
  openFile(chosen, {}, created);
}

/** タブを閉じる。最後の1つは、閉じない。見ていたタブを閉じたときは、隣のタブを見る。 */
function closeTab(target = tab) {
  if (tabs.length <= 1 || target.closed) return;
  const index = tabs.indexOf(target);
  if (speechTab === target) stopSpeech();
  target.closed = true;
  target.queued = null;
  tabs.splice(index, 1);
  win.contentView.removeChildView(target.contentView);
  if (!target.contentView.webContents.isDestroyed()) target.contentView.webContents.close();
  if (target === tab) {
    tab = tabs[Math.min(index, tabs.length - 1)];
    layout();
    win?.setTitle(tab.file ? `${path.basename(tab.file)} - ${APP_TITLE}` : APP_TITLE);
    if (!state.settingsOpen && tab.hasDocument) tab.contentView.webContents.focus();
  }
  updateWatch();
  push();
}

/** いま見ているタブ以外を、すべて閉じる（設定「複数のタブ」を「使わない」にしたとき）。 */
function closeOtherTabs() {
  for (const each of [...tabs]) if (each !== tab) closeTab(each);
}

/** 次・前のタブへ（端では、反対側へ回る）。 */
function cycleTab(delta) {
  if (tabs.length < 2) return;
  const index = tabs.indexOf(tab);
  activateTab(tabs[(index + delta + tabs.length) % tabs.length]);
}

/** 内容のビューを送り元とするメッセージの、持ち主のタブ。 */
function tabFromSender(sender) {
  return tabs.find((each) => each.contentView?.webContents === sender) ?? null;
}

// -- 画像の保存（#327） ---------------------------------------------------------

/** 右クリックの位置の、いちばん内側のブロックの行（原稿での行）。ブロックの外・失敗は、null。 */
async function lineAtPoint(origin, params) {
  try {
    const line = await origin.contentView.webContents.executeJavaScript(
      lineAtPointScript(params.x, params.y, origin.contentView.webContents.getZoomFactor()));
    return Number.isInteger(line) ? line : null;
  } catch {
    return null;
  }
}

/** 右クリックした位置のリンクの、href属性の値（#362）。リンクの外では、null。 */
async function linkAtPoint(origin, params) {
  try {
    const href = await origin.contentView.webContents.executeJavaScript(
      linkAtPointScript(params.x, params.y, origin.contentView.webContents.getZoomFactor()));
    return typeof href === 'string' && href ? href : null;
  } catch {
    return null;
  }
}

/** 「リンクを開く」。文書内のアンカーは、その見出しへスクロールし、相対リンク・外部リンクは、クリックと同じ扱いにする。 */
function openLink(origin, href) {
  if (href.startsWith('#')) {
    let id = href.slice(1);
    try { id = decodeURIComponent(id); } catch { /* そのまま使う */ }
    origin.contentView.webContents.executeJavaScript(`document.getElementById(${JSON.stringify(id)})?.scrollIntoView()`).catch(() => {});
  } else if (resolveRelativeLink(href, origin.file ?? '')) {
    handleRelativeLink(href, origin);
  } else {
    handleNavigation(href, origin);
  }
}

/**
 * 内容のビューの右クリックのメニュー。項目は、次の4種類で、あるものを、区切り線で分けて並べる。
 *   - コピー（選択があるとき）・すべて選択（常に。#409）
 *   - 画像の保存（#327）
 *   - リンクを開く・リンクのアドレスをコピー（#362）
 *   - 行番号のコピー（#328・#357）: `ファイル名:行`を、クリップボードへ入れる。行は、右クリックの位置から、その場で求める
 *     （ホバーで保持している最後の行ではなく、今の位置のブロック。余白では、項目を出さない）。設定「行番号の表示」がオフなら、出さない。
 */
async function handleContextMenu(origin, params) {
  // 先頭は、コピー（選択があるとき）・すべて選択（#409）。文書の上では、メニューが、常に出る
  const contents = origin.contentView.webContents;
  const template = buildSelectionContextMenuTemplate(params, {
    onCopy: () => { contents.focus(); contents.copy(); },
    onSearch: (term) => searchForSelection(origin, term),
    onSelectAll: () => { contents.focus(); contents.selectAll(); },
    onSpeak: (text) => void speakSelection(origin, text),
    onStopSpeaking: () => stopSpeech(),
    onPause: () => speaker.pause(),
    onResume: () => speaker.resume(),
    speaking: speaker.isSpeaking(),
    paused: speaker.isPaused(),
  });
  if (params.mediaType === 'image' && params.srcURL) {
    template.push({ type: 'separator' });
    template.push(...buildImageContextMenuTemplate(params, {
      onSave: (p, format) => void saveImageFromContextMenu(origin, p, format),
    }));
  }
  const href = await linkAtPoint(origin, params);
  if (href !== null) {
    template.push({ type: 'separator' });
    template.push(...buildLinkContextMenuTemplate({
      href, markdownFile: origin.file, onCopy: (text) => clipboard.writeText(text), onOpen: (link) => openLink(origin, link),
    }));
  }
  if (state.settings.showLineNumber && origin.file) {
    const line = await lineAtPoint(origin, params);
    if (line !== null) {
      template.push({ type: 'separator' });
      template.push(...buildLineContextMenuTemplate({ file: origin.file, line, onCopy: (text) => clipboard.writeText(text) }));
    }
  }
  const menu = Menu.buildFromTemplate(template);
  menu.popup({ window: win });
}

async function saveImageFromContextMenu(origin, params, requestedFormat) {
  try {
    const result = await executeSaveImage(params, requestedFormat, {
      win,
      documentFile: origin.file,
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
    origin.diagnostics = summarize([{
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
    tab.diagnostics = summarize([{ severity: 'error', message: `キャッシュを削除できません: ${error.message}` }]);
  } finally {
    state.cache = { ...state.cache, clearing: false };
  }
  await refreshCacheUsage();
  // 設定画面は、開いたままにする（reloadと違い、leaveSettingsは呼ばない）。どのタブの文書も、HTMLを消したため、変換し直す
  for (const each of tabs) if (each.file) openFile(each.file, {}, each);
}
// -- メニュー・IPC --------------------------------------------------------------

function buildMenu() {
  return Menu.buildFromTemplate([
    {
      label: 'ファイル',
      submenu: [
        { label: '開く…', accelerator: 'CommandOrControl+O', click: () => openWithDialog() },
        { id: 'open-folder', label: 'フォルダを開く…', click: () => void openFolder() },
        // タブの操作は、設定「複数のタブ」がオンのときだけ使える（#332。pushが、有効・無効を切り替える）
        { id: 'new-tab', label: '新しいタブで開く…', accelerator: 'CommandOrControl+Shift+O', enabled: false, click: () => void openInNewTab() },
        { id: 'close-tab', label: 'タブを閉じる', accelerator: 'CommandOrControl+W', enabled: false, click: () => closeTab() },
        { id: 'next-tab', label: '次のタブ', accelerator: 'Ctrl+Tab', enabled: false, click: () => cycleTab(1) },
        { id: 'previous-tab', label: '前のタブ', accelerator: 'Ctrl+Shift+Tab', enabled: false, click: () => cycleTab(-1) },
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
        { id: 'go-back', label: '戻る', accelerator: 'Alt+Left', enabled: tab.canGoBack, click: goBack },
        { label: '戻る', accelerator: 'CommandOrControl+[', enabled: tab.canGoBack, click: goBack, visible: false },
        { id: 'go-forward', label: '進む', accelerator: 'Alt+Right', enabled: tab.canGoForward, click: goForward },
        { label: '進む', accelerator: 'CommandOrControl+]', enabled: tab.canGoForward, click: goForward, visible: false },
        { type: 'separator' },
        { label: '拡大', accelerator: 'CommandOrControl+Plus', click: () => zoomBy(1) },
        { label: '拡大', accelerator: 'CommandOrControl+=', click: () => zoomBy(1), visible: false },
        { label: '縮小', accelerator: 'CommandOrControl+-', click: () => zoomBy(-1) },
        { label: '実寸', accelerator: 'CommandOrControl+0', click: zoomReset },
        { type: 'separator' },
        { id: 'toggle-sidebar', label: 'サイドバー', accelerator: 'CommandOrControl+B', click: () => setSidebarOpen(!state.sidebarOpen) },
        { label: '検索…', accelerator: 'CommandOrControl+F', click: () => setSearchOpen(!tab.search.open) },
        { label: 'ツールバーと文書を行き来', accelerator: 'F6', click: toggleFocusArea },
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
ipcMain.on('open-link', (event, href) => handleRelativeLink(href, tabFromSender(event.sender) ?? tab));
// 内容のビューの、見出しの「#」・コードの「コピー」（#337・#336）。クリップボードへの書き込みは、こちらで行う
ipcMain.on('copy-heading-link', (event, id) => {
  const origin = tabFromSender(event.sender);
  if (!origin || !state.settings.showHeadingAnchor || !origin.file) return;
  const text = headingLinkRef(origin.file, id);
  if (text) clipboard.writeText(text);
});
const COPY_CODE_MAX = 5 * 1024 * 1024;   // 巨大なコードでも、メモリを使い切らないための上限（超えたら、コピーしない）
ipcMain.on('copy-code', (event, text) => {
  if (!tabFromSender(event.sender) || !state.settings.showCodeCopy) return;
  if (typeof text === 'string' && text.length <= COPY_CODE_MAX) clipboard.writeText(text);
});
// ホバー中のリンクの飛び先を、内容のビューの下方に出す（#362）。表示する文字列は、こちらで作り、送り返す
ipcMain.on('link-hover', (event, href) => {
  event.sender.send('link-hover-text', describeLink(href, tabFromSender(event.sender)?.file ?? null));
});
ipcMain.on('content-scroll', (event, scrollY) => {
  const origin = tabFromSender(event.sender);
  if (origin && typeof scrollY === 'number' && Number.isFinite(scrollY)) {
    origin.history.updateCurrentScroll(Math.max(0, Math.round(scrollY)));
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
ipcMain.on('sidebar-toggle', () => setSidebarOpen(!state.sidebarOpen));
ipcMain.on('open-folder', () => void openFolder());
// ファイルツリーの一覧。ワーカー（変換の直列キュー）を通さず、ここで直接読む（変換中でも、展開が待たされない）
ipcMain.handle('list-directory', (event, directory) => {
  if (event.sender === win?.webContents && state.settings.showFileTree && state.tree.kind === 'project') return projectEntries(project, directory);   // 章の一覧（#373）
  if (event.sender !== win?.webContents || !isInsideTreeRoot(directory)) return { ok: false, message: 'このフォルダは、読めません' };
  return listDirectory(directory);
});
// サイドバーの項目のクリック。設定ファイルでも、モードを変えず、ただのファイルとして開く（#373）
ipcMain.on('open-from-sidebar', (event, filePath) => {
  if (event.sender !== win?.webContents || typeof filePath !== 'string') return;
  leaveSettings();
  openFile(filePath);
});
ipcMain.on('settings-set', (_event, key, value) => changeSetting(key, value));
ipcMain.on('choose-open-directory', () => chooseOpenDirectory());
ipcMain.on('clear-cache', () => clearWorkCache());
// 設定画面の「試し聞き」（#430）。いまの設定の声と速さで、短い文を読む。文書のタブとは無関係のため、文書の切り替えでは止めない
ipcMain.on('speech-test', (event) => {
  if (event.sender !== win?.webContents) return;
  void speakSelection(null, 'これは、読み上げの試し聞きです。声と速さを、確かめてください。');
});
// 行番号の表示（#328）。内容のビューが、マウスを乗せたブロックの行を、変わったときだけ送ってくる。値は、正の整数だけ受け付ける
ipcMain.on('content-line', (event, line) => {
  const origin = tabFromSender(event.sender);
  if (!origin || !state.settings.showLineNumber) return;
  if (!Number.isInteger(line) || line < 1 || line > 999999999 || line === origin.line) return;
  origin.line = line;
  if (origin === tab) push();
});
// 画面へのドロップ。Ctrlを押しながらのドロップは、設定「複数のタブ」がオンのとき、新しいタブで開く（#332）
ipcMain.on('open-path', (_event, filePath, inNewTab) => {
  if (typeof filePath !== 'string') return;
  leaveSettings();
  if (inNewTab === true && state.settings.enableTabs) void openInNewTab(filePath);
  else openTarget(filePath);
});
ipcMain.on('search-toggle', () => setSearchOpen(!tab.search.open));
ipcMain.on('search-close', () => setSearchOpen(false));
ipcMain.on('search-set', (_event, payload) => setSearchQuery(payload ?? {}));
ipcMain.on('search-move', (_event, delta) => moveSearch(delta));
ipcMain.on('search-result', (event, result) => onSearchResult(tabFromSender(event.sender), result ?? {}));
// タブ列（#332）。設定がオフのときは、タブ列そのものが出ないが、念のため、ここでも、はじく
ipcMain.on('tab-activate', (_event, id) => { if (state.settings.enableTabs) activateTab(tabs.find((each) => each.id === id)); });
ipcMain.on('tab-close', (_event, id) => { if (state.settings.enableTabs) closeTab(tabs.find((each) => each.id === id)); });
ipcMain.on('tab-new', () => void openInNewTab());
