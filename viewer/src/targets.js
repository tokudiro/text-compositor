'use strict';
// 開くファイルの判定（起動引数・リンク・ドロップ）。Electronに依存しない、純粋な関数（#190）。

const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');

/**
 * Viewerで開ける拡張子（#196）。Markdown・図の単体ファイル（SVGを含む）・CSV（表）・テキスト（.txt）。
 * それ以外は、開こうとすると、ワーカーが、案内つきのエラーにする（.yaml・.json・ソースコードの表示は、#218）。
 */
const MARKDOWN_EXTENSIONS = ['.md', '.markdown'];
const DIAGRAM_EXTENSIONS = ['.mmd', '.puml', '.plantuml', '.pu', '.d2', '.dot', '.gv', '.svg'];
const CSV_EXTENSIONS = ['.csv'];
const TEXT_EXTENSIONS = ['.txt'];

/** ファイルを開くダイアログの、種類ごとの絞り込み。#218で.yaml・.json・ソースコードに対応したら、ここに種類を足す。 */
const OPEN_FILE_KINDS = [
  { name: 'Markdown', extensions: MARKDOWN_EXTENSIONS },
  { name: '図（Mermaid・PlantUML・D2・Graphviz・SVG）', extensions: DIAGRAM_EXTENSIONS },
  { name: 'CSV', extensions: CSV_EXTENSIONS },
  { name: 'テキスト', extensions: TEXT_EXTENSIONS },
];

/**
 * ファイルを開くダイアログの絞り込み（Electronの`filters`の形）。先頭は、開けるものすべて（既定）、
 * 末尾は、拡張子を問わないすべてのファイル（対象外の場合は、開くときに、ワーカーが案内する）。
 */
function openDialogFilters() {
  const dotless = (extensions) => extensions.map((extension) => extension.slice(1));
  return [
    { name: '開けるファイルすべて', extensions: dotless(OPEN_FILE_KINDS.flatMap((kind) => kind.extensions)) },
    ...OPEN_FILE_KINDS.map((kind) => ({ name: kind.name, extensions: dotless(kind.extensions) })),
    { name: 'すべてのファイル', extensions: ['*'] },
  ];
}

/**
 * ファイルを開くダイアログが、最初に見せるフォルダ（設定の`openDirectoryMode`、#226）。
 *   os: 指定しない（`undefined`。OSの既定の動きになる）
 *   last: 前回開いたファイルのフォルダ（`lastDirectory`）
 *   fixed: 利用者が指定したフォルダ（`fixedDirectory`）
 * 指定したフォルダが、未設定・消えている・フォルダでないときは、`fallback`（「ドキュメント」）にする。
 * 何も指定しないと、場所はOS任せになり、開いている文書とは無関係な場所（例: 起動したフォルダ）から始まることがある。
 */
function openDialogDirectory(settings, fallback, { statSync = fs.statSync } = {}) {
  if (settings.openDirectoryMode === 'os') return undefined;
  const directory = settings.openDirectoryMode === 'fixed' ? settings.fixedDirectory : settings.lastDirectory;
  if (typeof directory !== 'string' || !directory) return fallback;
  try {
    return statSync(directory).isDirectory() ? directory : fallback;
  } catch {
    return fallback;
  }
}

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

module.exports = { checkOpenTarget, fileFromArgv, classifyNavigation, openDialogFilters, openDialogDirectory };
