'use strict';
// プロジェクトモード（#373）: 設定ファイル（`chapters`）を開いたとき、サイドバーに章の一覧を出すための、純粋な関数。
// Electronに依存しない。章の一覧そのものは、Pythonのワーカー（`list_chapters`）が作る。ここでは、その結果を、
// ファイルツリー（chrome/tree.js）が読める形（フォルダ＝見出し、ファイル＝章）にする。

const path = require('node:path');

const { isOpenableFile } = require('./targets');

/** プロジェクトの設定ファイルとみなす名前。CLIが、`--config`省略時に探す名前と同じ（`config.py`の`find_config_in_cwd`）。 */
const PROJECT_CONFIG_NAMES = ['text-compositor.config.yaml', 'text-compositor.config.json'];

/** 名前だけで判定する（中身は読まない。軽さを保つ）。別名の設定ファイルは、対象外。 */
function isProjectConfigFile(file) {
  return typeof file === 'string' && PROJECT_CONFIG_NAMES.includes(path.basename(file).toLowerCase());
}

// Windowsのパスは、大文字小文字を区別しない
const keyOf = (file) => (process.platform === 'win32' ? path.resolve(file).toLowerCase() : path.resolve(file));

/** 見出しの項目の、ツリー上の識別子（ファイルツリーでは、フォルダのパスの位置に入る）。 */
const sectionKey = (index) => `section:${index}`;

/**
 * ワーカーの`list_chapters`の結果から、サイドバーの材料を作る。
 * 出すのは、Obunzuで開けるファイルの章と、章を持つ見出しだけ（図表ファイルも、開けるなら出す。開けないものは出さない）。
 * @param {string} config 設定ファイルの絶対パス（ツリーのルートの識別子を兼ねる）
 * @param {{kind: 'file'|'section', name: string, path?: string, children?: object[]}[]} items
 * @returns {{config: string, entries: Map<string, {name: string, path: string, type: 'file'|'directory'}[]>, files: Set<string>}}
 */
function buildProject(config, items) {
  const entries = new Map();
  const files = new Set([keyOf(config)]);   // 設定ファイル自身も、プロジェクトの中（開いたまま、モードを保つ）
  let sections = 0;
  const build = (list) => {
    const result = [];
    for (const item of list) {
      if (item.kind === 'section') {
        const key = sectionKey(sections++);
        const children = build(Array.isArray(item.children) ? item.children : []);
        entries.set(key, children);
        if (children.length > 0) result.push({ name: item.name, path: key, type: 'directory' });
      } else if (item.kind === 'file' && typeof item.path === 'string' && isOpenableFile(item.name)) {
        result.push({ name: item.name, path: item.path, type: 'file' });
        files.add(keyOf(item.path));
      }
    }
    return result;
  };
  entries.set(config, build(items));
  return { config, entries, files };
}

/** ファイルツリーの一覧の依頼（ルート、または見出しの識別子）に答える。形は、`directory-list.js`の`listDirectory`と同じ。 */
function projectEntries(project, key) {
  const entries = project?.entries.get(key);
  return entries ? { ok: true, entries } : { ok: false, message: 'この見出しは、読めません' };
}

/** `file`が、プロジェクトの中（章または設定ファイル自身）か。 */
function isInsideProject(project, file) {
  return Boolean(project) && typeof file === 'string' && path.isAbsolute(file) && project.files.has(keyOf(file));
}

module.exports = { PROJECT_CONFIG_NAMES, isProjectConfigFile, buildProject, projectEntries, isInsideProject };
