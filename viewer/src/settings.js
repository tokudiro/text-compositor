'use strict';
// 設定の読み書き（#200）。ユーザーのデータの場所に、JSONで保存する。
// 壊れている・存在しない・値が想定外のときは、既定値にして、起動を止めない。

const fs = require('node:fs');
const path = require('node:path');

const DEFAULTS = Object.freeze({
  toolbarPosition: 'top',   // 'top' | 'bottom'
  theme: 'system',          // 'system' | 'light' | 'dark'
  autoReload: true,         // 保存したら、自動で更新する（#170）
});

const CHOICES = Object.freeze({
  toolbarPosition: ['top', 'bottom'],
  theme: ['system', 'light', 'dark'],
});

/** 任意の値から、正しい設定を作る。項目ごとに、想定外の値だけを既定値に戻し、知らない項目は捨てる。 */
function normalizeSettings(value) {
  const source = value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const result = { ...DEFAULTS };
  for (const [key, choices] of Object.entries(CHOICES)) {
    if (choices.includes(source[key])) result[key] = source[key];
  }
  if (typeof source.autoReload === 'boolean') result.autoReload = source.autoReload;
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

module.exports = { CHOICES, DEFAULTS, loadSettings, normalizeSettings, saveSettings };
