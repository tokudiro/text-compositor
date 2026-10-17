'use strict';
// 目次（アウトライン）パネル（#329）の、純粋な関数。Electronに依存しない。
// 見出しの一覧は、内容のビューのプリロード（chrome/content-preload.js）が、表示中のHTMLから集めて、メインプロセスへ送る。
// ここでは、その「信用できない入力」を、使える形にする。サイドバーが、どの表示（ファイル・目次）を出すかも、決める。

const MAX_HEADINGS = 3000;       // 極端に長い文書でも、状態の送受信が重くならないための上限
const MAX_TEXT = 200;            // 目次の1行の文字数の上限（長い見出しは、省略する）
const MAX_ID = 500;

/**
 * プリロードから届いた見出しの一覧を、検証して、整える。形の違う項目は、捨てる。
 * @param {unknown} raw `[{id, level, text}]`のはず
 * @returns {{id: string, level: number, text: string, depth: number}[]}
 *   `depth`は、一覧の中で一番浅い見出しを0とした、深さ（H2から始まる文書で、不自然に字下げされないように）。
 */
function sanitizeOutline(raw) {
  if (!Array.isArray(raw)) return [];
  const items = [];
  for (const entry of raw) {
    if (items.length >= MAX_HEADINGS) break;
    if (entry === null || typeof entry !== 'object') continue;
    const { id, level, text } = entry;
    if (typeof id !== 'string' || id === '' || id.length > MAX_ID) continue;
    if (!Number.isInteger(level) || level < 1 || level > 6) continue;
    const label = typeof text === 'string' ? text.replace(/\s+/g, ' ').trim() : '';
    items.push({ id, level, text: label === '' ? id : (label.length > MAX_TEXT ? `${label.slice(0, MAX_TEXT)}…` : label) });
  }
  const shallowest = items.reduce((min, item) => Math.min(min, item.level), 6);
  return items.map((item) => ({ ...item, depth: item.level - shallowest }));
}

/**
 * サイドバーが、いま出す表示（'files'＝ファイルツリー・章の一覧、'outline'＝目次）を決める。
 * 利用者が選んだ表示（explicit）があり、使えるなら、それ。無ければ、フォルダ・設定ファイルを開いているときは「ファイル」、
 * 開いていない（単一のファイル）ときは「目次」（ファイルの一覧は、空の案内になるため）。使える表示が1つだけなら、それ。
 * @returns {'files'|'outline'|null} どちらも使えないときは、null
 */
function effectiveSidebarView({ explicit, showFileTree, showOutline, hasRoot }) {
  const available = { files: Boolean(showFileTree), outline: Boolean(showOutline) };
  if (!available.files && !available.outline) return null;
  if (!available.outline) return 'files';
  if (!available.files) return 'outline';
  if (explicit === 'files' || explicit === 'outline') return explicit;
  return hasRoot ? 'files' : 'outline';
}

module.exports = { MAX_HEADINGS, MAX_ID, MAX_TEXT, effectiveSidebarView, sanitizeOutline };
