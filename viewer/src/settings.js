'use strict';
// 設定の読み書き（#200）。ユーザーのデータの場所に、JSONで保存する。
// 壊れている・存在しない・値が想定外のときは、既定値にして、起動を止めない。

const fs = require('node:fs');
const path = require('node:path');

/**
 * 「表示する機能」の一覧（#326）。画面に、常時、要素を足す機能（行番号・目次パネルなど）は、ここに1行足すだけで、
 * 設定（既定値・正規化・保存）と、設定画面の行が、そろう。方針（何を、ここに入れるか。既定値の基準）は、
 * `doc/viewer-visual-design.md`の「機能を足すときの基準」。
 *   key: 設定のキー（`state.settings[key]`で、機能を使う側が読む）。 default: 既定値（真偽値）。
 *   label・description: 設定画面の名前と説明（文字列。HTMLは使えない）。 on・off: 選択肢の文字。
 */
const FEATURES = Object.freeze([
  Object.freeze({
    key: 'showLineNumber',
    default: true,   // ツールバーの、既存の行の中で完結する、小さな表示のため、既定は「出す」（#328・#357）
    label: '行番号の表示',
    description: '段落・見出し・リスト・表・図などにマウスを乗せると、ツールバーのファイル名の右横に、元のMarkdownの行番号'
      + '（check.md:14の:14）を出します。右クリックのメニューの「行番号をコピー」で、ファイル名:行をコピーできます。'
      + '長い原稿を、直しに戻るときの目印です。',
    on: '出す',
    off: '出さない',
  }),
  Object.freeze({
    key: 'showHeadingAnchor',
    default: true,   // ホバーしたときだけ出す、小さな表示のため、既定は「出す」（#337）
    label: '見出しのリンク',
    description: '見出しにマウスを乗せると、右に「#」が出ます。クリックすると、その見出しへのリンク（check.md#見出し）をコピーします。'
      + '別の文書から[…](check.md#見出し)と書くと、Obunzuで、その見出しへ飛べます。',
    on: '出す',
    off: '出さない',
  }),
  Object.freeze({
    key: 'showCodeCopy',
    default: true,   // ホバーしたときだけ出す、小さな表示のため、既定は「出す」（#336）
    label: 'コードのコピーボタン',
    description: 'コードブロックにマウスを乗せると、右上に「コピー」が出ます。クリックすると、コードの内容（フェンスの中身）をコピーします。',
    on: '出す',
    off: '出さない',
  }),
  Object.freeze({
    key: 'showFileTree',
    default: true,   // フォルダを開くまで、画面は何も変わらない（サイドバーは閉じている）ため、既定は「出す」（#339。#326のDの例外）
    label: 'ファイルツリー',
    description: '「フォルダを開く」で選んだフォルダを、サイドバー（Ctrl+B）に、ファイルのツリーで出します。クリックで、ファイルを開けます。'
      + '「出さない」にすると、サイドバーのボタンと、メニューの「フォルダを開く」も出ません。',
    on: '出す',
    off: '出さない',
  }),
  Object.freeze({
    key: 'enableTabs',
    default: false,   // 画面の構造を変える（タブ列が増える）ため、既定は「使わない」（#326のD。#332）
    label: '複数のタブ',
    description: '複数の文書を、タブで切り替えて開きます。「新しいタブで開く」（Ctrl+Shift+O）で、いまの文書を残したまま、別の文書を開けます。'
      + 'タブを閉じるのは、Ctrl+W、切り替えは、Ctrl+Tab・Ctrl+Shift+Tabです。「使わない」にすると、いま見ているタブだけを残して、ほかは閉じます。',
    on: '使う',
    off: '使わない',
  }),
]);

const DEFAULTS = Object.freeze({
  ...Object.fromEntries(FEATURES.map((feature) => [feature.key, feature.default])),
  toolbarPosition: 'top',   // 'top' | 'bottom'
  theme: 'system',          // 'system' | 'light' | 'dark'
  autoReload: true,         // 保存したら、自動で更新する（#170）
  csvHeader: true,          // .csvの1行目を、見出し行にする（#220）。ツールバーで切り替え、覚える
  allowExternalImages: false, // 外部の画像（https://...等）を読み込むか（既定false。方針2章「ローカルに閉じる」。#238）
  window: null,             // 前回のウィンドウの大きさ・位置（#192）。設定画面では変えない
  openDirectoryMode: 'last', // ファイルを開くダイアログの、最初の場所（#226）。'os'（OSにゆだねる） | 'last'（前回開いたフォルダ） | 'fixed'（特定のフォルダ）
  fixedDirectory: null,     // 'fixed'のときのフォルダ。設定画面の、フォルダを選ぶボタンで決める
  workLocation: 'app',      // 変換したHTML・図のキャッシュの置き場所（#258）。'app'（アプリの領域。原稿のフォルダには書かない） | 'beside'（原稿の隣の.text-compositor/）
  lastDirectory: null,      // 前回開いたファイルのフォルダ。アプリが自動で保存する。設定画面では変えない
  sidebarOpen: false,       // サイドバー（ファイルツリー。#339）を開いているか。ボタン・Ctrl+Bで切り替え、開閉を覚える。設定画面では変えない
});

/** 設定画面から変えられる項目（ウィンドウの状態などは、アプリが自動で保存する） */
const EDITABLE = Object.freeze(['toolbarPosition', 'theme', 'autoReload', 'csvHeader', 'allowExternalImages', ...FEATURES.map((feature) => feature.key), 'openDirectoryMode', 'workLocation']);

const WINDOW_MIN = Object.freeze({ width: 400, height: 300 });
const WINDOW_MAX = 20000;

const CHOICES = Object.freeze({
  toolbarPosition: ['top', 'bottom'],
  theme: ['system', 'light', 'dark'],
  openDirectoryMode: ['os', 'last', 'fixed'],
  workLocation: ['app', 'beside'],   // 「ファイルを作らない」（カスタムプロトコル）は、実装できてから加える（#258）
});

function integer(value, min, max) {
  return Number.isFinite(value) && Math.round(value) >= min && Math.round(value) <= max ? Math.round(value) : null;
}

/**
 * 保存されたウィンドウの状態を、使える値にする。大きさが不正なら、まるごと捨てる（既定の大きさで開く）。
 * 位置は、xとyの両方が正しいときだけ使う（片方だけでは、画面の外に出るおそれがある）。
 */
function normalizeWindow(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const width = integer(value.width, WINDOW_MIN.width, WINDOW_MAX);
  const height = integer(value.height, WINDOW_MIN.height, WINDOW_MAX);
  if (width === null || height === null) return null;
  const x = integer(value.x, -WINDOW_MAX, WINDOW_MAX);
  const y = integer(value.y, -WINDOW_MAX, WINDOW_MAX);
  const result = { width, height, maximized: value.maximized === true };
  if (x !== null && y !== null) { result.x = x; result.y = y; }
  return result;
}

/** 任意の値から、正しい設定を作る。項目ごとに、想定外の値だけを既定値に戻し、知らない項目は捨てる。 */
function normalizeSettings(value) {
  const source = value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const result = { ...DEFAULTS };
  for (const [key, choices] of Object.entries(CHOICES)) {
    if (choices.includes(source[key])) result[key] = source[key];
  }
  if (typeof source.autoReload === 'boolean') result.autoReload = source.autoReload;
  if (typeof source.csvHeader === 'boolean') result.csvHeader = source.csvHeader;
  if (typeof source.allowExternalImages === 'boolean') result.allowExternalImages = source.allowExternalImages;
  if (typeof source.sidebarOpen === 'boolean') result.sidebarOpen = source.sidebarOpen;
  for (const feature of FEATURES) {
    if (typeof source[feature.key] === 'boolean') result[feature.key] = source[feature.key];
  }
  result.window = normalizeWindow(source.window);
  for (const key of ['lastDirectory', 'fixedDirectory']) {
    if (typeof source[key] === 'string' && path.isAbsolute(source[key])) result[key] = source[key];
  }
  return result;
}

function loadSettings(file) {
  try {
    return normalizeSettings(JSON.parse(fs.readFileSync(file, 'utf8')));
  } catch {
    return { ...DEFAULTS };
  }
}

/** 書きかけのファイルが残らないように、一時ファイルに書いてから、置き換える。失敗しても、アプリは止めない。 */
function saveSettings(file, settings) {
  const temporary = `${file}.tmp`;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(temporary, `${JSON.stringify(normalizeSettings(settings), null, 2)}\n`, 'utf8');
    fs.renameSync(temporary, file);
    return true;
  } catch {
    try { fs.rmSync(temporary, { force: true }); } catch { /* 後始末の失敗は、無視する */ }
    return false;
  }
}

module.exports = { CHOICES, DEFAULTS, EDITABLE, FEATURES, loadSettings, normalizeSettings, normalizeWindow, saveSettings };
