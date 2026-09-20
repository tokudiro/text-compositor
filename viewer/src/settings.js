'use strict';
// 設定の読み書き（#200）。ユーザーのデータの場所に、JSONで保存する。
// 壊れている・存在しない・値が想定外のときは、既定値にして、起動を止めない。

const fs = require('node:fs');
const path = require('node:path');

const DEFAULTS = Object.freeze({
  toolbarPosition: 'top',   // 'top' | 'bottom'
  theme: 'system',          // 'system' | 'light' | 'dark'
  autoReload: true,         // 保存したら、自動で更新する（#170）
  csvHeader: true,          // .csvの1行目を、見出し行にする（#220）。ツールバーで切り替え、覚える
  window: null,             // 前回のウィンドウの大きさ・位置（#192）。設定画面では変えない
  openDirectoryMode: 'last', // ファイルを開くダイアログの、最初の場所（#226）。'os'（OSにゆだねる） | 'last'（前回開いたフォルダ） | 'fixed'（特定のフォルダ）
  fixedDirectory: null,     // 'fixed'のときのフォルダ。設定画面の、フォルダを選ぶボタンで決める
  workLocation: 'app',      // 変換したHTML・図のキャッシュの置き場所（#258）。'app'（アプリの領域。原稿のフォルダには書かない） | 'beside'（原稿の隣の.text-compositor/）
  lastDirectory: null,      // 前回開いたファイルのフォルダ。アプリが自動で保存する。設定画面では変えない
});

/** 設定画面から変えられる項目（ウィンドウの状態などは、アプリが自動で保存する） */
const EDITABLE = Object.freeze(['toolbarPosition', 'theme', 'autoReload', 'csvHeader', 'openDirectoryMode', 'workLocation']);

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

module.exports = { CHOICES, DEFAULTS, EDITABLE, loadSettings, normalizeSettings, normalizeWindow, saveSettings };
