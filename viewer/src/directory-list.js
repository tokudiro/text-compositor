'use strict';
// ファイルツリー（#339）のための、フォルダの一覧取得。Electronに依存しない、純粋な関数。
// ワーカー（変換の直列キュー）を通さず、メインプロセスが直接読む。変換中でも、ツリーの展開が待たされないため。

const fsPromises = require('node:fs/promises');
const path = require('node:path');

const { isOpenableFile } = require('./targets');

/** ツリーに出さないフォルダ。`.`で始まるもの（.git など）と、依存・生成物の置き場所。 */
const HIDDEN_DIRECTORY_NAMES = new Set(['node_modules', '.text-compositor']);

function isHiddenDirectory(name) {
  return name.startsWith('.') || HIDDEN_DIRECTORY_NAMES.has(name);
}

/** フォルダが先、同じ種類の中では名前順（数字は数の大きさで比べる: `2.md`が`10.md`より前）。 */
function compareEntries(a, b) {
  if (a.type !== b.type) return a.type === 'directory' ? -1 : 1;
  return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
}

/**
 * フォルダの直下だけを読み、ツリーに出す項目を返す（再帰しない。中身は、展開のときに、そのフォルダを読む）。
 * 出すのは、隠さないフォルダと、Viewerで開ける拡張子のファイルだけ。ファイルの中身は読まない。
 * 読めないフォルダ（権限・消えた・ネットワークの切断）は、例外にせず、案内つきの失敗で返す。
 * @returns {Promise<{ok: true, entries: {name: string, path: string, type: 'directory'|'file'}[]} | {ok: false, message: string}>}
 */
async function listDirectory(directory, { readdir = fsPromises.readdir, stat = fsPromises.stat } = {}) {
  if (typeof directory !== 'string' || !directory) return { ok: false, message: '開くフォルダが指定されていません。' };
  let dirents;
  try {
    dirents = await readdir(directory, { withFileTypes: true });
  } catch {
    return { ok: false, message: `フォルダを読めません: ${path.basename(directory) || directory}` };
  }
  const entries = [];
  for (const dirent of dirents) {
    const entryPath = path.join(directory, dirent.name);
    let type = dirent.isDirectory() ? 'directory' : dirent.isFile() ? 'file' : null;
    if (dirent.isSymbolicLink()) {
      // リンクは、リンク先の種類で扱う。リンク先が無い（壊れたリンク）ものは、出さない。
      try {
        const target = await stat(entryPath);
        type = target.isDirectory() ? 'directory' : target.isFile() ? 'file' : null;
      } catch {
        type = null;
      }
    }
    if (type === 'directory' && !isHiddenDirectory(dirent.name)) entries.push({ name: dirent.name, path: entryPath, type });
    else if (type === 'file' && isOpenableFile(dirent.name)) entries.push({ name: dirent.name, path: entryPath, type });
  }
  entries.sort(compareEntries);
  return { ok: true, entries };
}

/**
 * `candidate`が、`root`の中（`root`自身を含む）のフォルダか。字面（パスの解決）だけで判定し、ファイルシステムは見ない。
 * 画面からの一覧の依頼を、ツリーのルートの外へ広げないための門番（`..`を含むパスも、解決してから比べる）。
 */
function isInsideDirectory(root, candidate) {
  if (typeof root !== 'string' || !root || typeof candidate !== 'string' || !path.isAbsolute(root) || !path.isAbsolute(candidate)) return false;
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

module.exports = { listDirectory, isInsideDirectory };
