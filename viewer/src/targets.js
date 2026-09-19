'use strict';
// 開くファイルの判定（起動引数・リンク・ドロップ）。Electronに依存しない、純粋な関数（#190）。

const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');

/** Viewerで開ける拡張子。Markdownと、図の単体ファイル（`render_html`の対象）。 */
const MARKDOWN_EXTENSIONS = ['.md', '.markdown'];
const DIAGRAM_EXTENSIONS = ['.mmd', '.puml', '.plantuml', '.pu', '.d2', '.dot', '.gv'];
const OPENABLE_EXTENSIONS = new Set([...MARKDOWN_EXTENSIONS, ...DIAGRAM_EXTENSIONS]);

function isOpenable(filePath) {
  return typeof filePath === 'string' && OPENABLE_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

/**
 * コマンドライン引数から、開くファイルを探す。オプション（`-`で始まる）と、開けない拡張子は、読み飛ばす。
 * 相対パスは、`cwd`が基準。
 */
function fileFromArgv(argv, { cwd = process.cwd(), exists = fs.existsSync } = {}) {
  for (const arg of argv) {
    if (!arg || arg.startsWith('-') || !isOpenable(arg)) continue;
    const full = path.resolve(cwd, arg);
    if (exists(full)) return full;
  }
  return null;
}

/**
 * 文書の中のリンク・ドロップによる遷移を、どう扱うか。
 *   open: Viewerで開く（file: の、開けるファイル）
 *   external: 既定のブラウザ・メールで開く（http・https・mailto）
 *   ignore: 何もしない（アプリの表示を、他のページへ遷移させない）
 */
function classifyNavigation(url) {
  let parsed;
  try { parsed = new URL(url); } catch { return { type: 'ignore' }; }
  if (parsed.protocol === 'http:' || parsed.protocol === 'https:' || parsed.protocol === 'mailto:') {
    return { type: 'external', url: parsed.toString() };
  }
  if (parsed.protocol === 'file:') {
    try {
      const file = fileURLToPath(parsed);
      if (isOpenable(file)) return { type: 'open', path: file };
    } catch { /* 不正なfile URL */ }
  }
  return { type: 'ignore' };
}

module.exports = { isOpenable, fileFromArgv, classifyNavigation, MARKDOWN_EXTENSIONS, DIAGRAM_EXTENSIONS };
