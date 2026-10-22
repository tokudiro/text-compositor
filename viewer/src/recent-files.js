'use strict';
// 最近開いたファイルの一覧（MRU。#331）。Electronに依存しない、純粋な関数だけを置く。
// 一覧は、設定（settings.json）の`recentFiles`に、新しい順の絶対パスで保存する。

const path = require('node:path');

const MAX_RECENT_FILES = 10;
const MAX_LABEL_LENGTH = 90;

/** 同じファイルか。Windowsは大文字と小文字を区別しないため、別の綴りで開いても、一覧に重複を作らない。 */
function sameFile(a, b, platform = process.platform) {
  return platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b;
}

/** 保存された値を、使える一覧にする。絶対パスの文字列だけを採り、重複を除き、上限で切る（先頭ほど新しい）。 */
function normalizeRecentFiles(value, platform = process.platform) {
  if (!Array.isArray(value)) return [];
  const result = [];
  for (const item of value) {
    if (typeof item !== 'string' || !path.isAbsolute(item)) continue;
    if (result.some((each) => sameFile(each, item, platform))) continue;
    result.push(item);
    if (result.length >= MAX_RECENT_FILES) break;
  }
  return result;
}

/** fileを先頭に足した、新しい一覧を返す（すでにあれば、先頭へ移す）。元の配列は変えない。 */
function addRecentFile(list, file, platform = process.platform) {
  return normalizeRecentFiles([file, ...list.filter((each) => !sameFile(each, file, platform))], platform);
}

/** fileを除いた、新しい一覧を返す。 */
function removeRecentFile(list, file, platform = process.platform) {
  return list.filter((each) => !sameFile(each, file, platform));
}

/**
 * メニューに出す名前。ファイル名を先に、場所を後ろに出す。長い場所は、真ん中を省く。
 * Electronのメニューは、`&`を文字の下線（アクセスキー）の印として読むため、`&&`に直す。
 */
function recentLabel(file) {
  const name = path.basename(file);
  let directory = path.dirname(file);
  const room = MAX_LABEL_LENGTH - name.length - 4;
  if (directory.length > room) {
    const keep = Math.max(room - 1, 8);
    const head = Math.ceil(keep / 2);
    directory = `${directory.slice(0, head)}…${directory.slice(directory.length - (keep - head))}`;
  }
  return `${name}  (${directory})`.replace(/&/g, '&&');
}

module.exports = { MAX_RECENT_FILES, addRecentFile, normalizeRecentFiles, recentLabel, removeRecentFile, sameFile };
