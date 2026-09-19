'use strict';
// 開くファイルの判定（起動引数・リンク・ドロップ）。Electronに依存しない、純粋な関数（#190）。

const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');

/**
 * Viewerで開ける拡張子（#196）。Markdown・図の単体ファイル・テキスト（.txt）・CSV（表）・SVG（画像）。
 * それ以外は、開こうとすると、ワーカーが、案内つきのエラーにする（.yaml・.json・ソースコードの表示は、#218）。
 */
const MARKDOWN_EXTENSIONS = ['.md', '.markdown'];
const DIAGRAM_EXTENSIONS = ['.mmd', '.puml', '.plantuml', '.pu', '.d2', '.dot', '.gv'];
const OTHER_EXTENSIONS = ['.txt', '.csv', '.svg'];

/**
 * 開こうとするファイルの、事前の確認（存在するか、フォルダでないか）。拡張子では、絞らない。
 * 中身がテキストか（バイナリか）は、ワーカーが、中身を見て判断する（#196）。
 * @returns {{ok: true} | {ok: false, message: string}}
 */
function checkOpenTarget(filePath, { statSync = fs.statSync } = {}) {
  if (typeof filePath !== 'string' || !filePath) return { ok: false, message: '開くファイルが指定されていません。' };
  const name = path.basename(filePath);
  let stat;
  try {
    stat = statSync(filePath);
  } catch {
    return { ok: false, message: `ファイルが見つかりません: ${name}` };
  }
  if (stat.isDirectory()) {
    return { ok: false, message: `フォルダは開けません: ${name}（Markdown・図・テキストのファイルを、選んでください）` };
  }
  return { ok: true };
}

/**
 * コマンドライン引数から、開くファイルを探す。オプション（`-`で始まる）は、読み飛ばし、最初のファイルの指定を、
 * 絶対パスにして返す（存在の確認は、`checkOpenTarget`で行い、無ければ、案内を出す）。相対パスは、`cwd`が基準。
 */
function fileFromArgv(argv, { cwd = process.cwd() } = {}) {
  for (const arg of argv) {
    if (!arg || arg.startsWith('-')) continue;
    return path.resolve(cwd, arg);
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
      return { type: 'open', path: file };   // 開けるかは、開くときに、ワーカーが確認して、対象外なら、案内を出す（#196）
    } catch { /* 不正なfile URL */ }
  }
  return { type: 'ignore' };
}

module.exports = { checkOpenTarget, fileFromArgv, classifyNavigation, MARKDOWN_EXTENSIONS, DIAGRAM_EXTENSIONS, OTHER_EXTENSIONS };
