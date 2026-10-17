'use strict';
// 目次（アウトライン）パネル（#329）の、純粋な関数。Electronに依存しない。
// 見出しの一覧は、内容のビューのプリロード（chrome/content-preload.js）が、表示中のHTMLから集めて、メインプロセスへ送る。
// ここでは、その「信用できない入力」を、使える形にする。サイドバーが、どの表示（ファイル・目次）を出すかも、決める。

const MAX_HEADINGS = 3000;       // 極端に長い文書でも、状態の送受信が重くならないための上限
const MAX_TEXT = 200;            // 目次の1行の文字数の上限（長い見出しは、省略する）
const MAX_ID = 500;
const HEADING_MARGIN = 24;       // 「いま読んでいる見出し」を求める線を、画面の上端から、少し下げる（px）。見出しの直前まで来たら、その見出しにする

/**
 * プリロードから届いた見出しの一覧を、検証して、整える。形の違う項目は、捨てる。
 * @param {unknown} raw `[{id, level, text, top}]`のはず（`top`は、文書の先頭から、見出しの上端までの距離。px）
 * @returns {{id: string, level: number, text: string, depth: number, top: number}[]}
 *   `depth`は、一覧の中で一番浅い見出しを0とした、深さ（H2から始まる文書で、不自然に字下げされないように）。
 *   `top`は、有限の0以上の数だけを採り（丸める）、それ以外は0（現在位置の強調で使う。#329）。
 */
function sanitizeOutline(raw) {
  if (!Array.isArray(raw)) return [];
  const items = [];
  for (const entry of raw) {
    if (items.length >= MAX_HEADINGS) break;
    if (entry === null || typeof entry !== 'object') continue;
    const { id, level, text, top } = entry;
    if (typeof id !== 'string' || id === '' || id.length > MAX_ID) continue;
    if (!Number.isInteger(level) || level < 1 || level > 6) continue;
    const label = typeof text === 'string' ? text.replace(/\s+/g, ' ').trim() : '';
    items.push({
      id, level, text: label === '' ? id : (label.length > MAX_TEXT ? `${label.slice(0, MAX_TEXT)}…` : label),
      top: Number.isFinite(top) && top >= 0 ? Math.round(top) : 0,
    });
  }
  const shallowest = items.reduce((min, item) => Math.min(min, item.level), 6);
  return items.map((item) => ({ ...item, depth: item.level - shallowest }));
}

/**
 * いま読んでいる見出しのidを求める（目次で強調する。#329）。
 * 規則: スクロール位置（画面の上端）に、少し余白を足した線より上に、上端がある見出しのうち、文書の順で、最後のもの。
 * 最初の見出しより上にいる間は、null（強調なし）。文書が、実際にスクロールされていて、末尾まで来たとき（atBottom）は、
 * 最後の見出し（末尾の見出しは、画面の先頭まで上がれないため）。スクロールしない短い文書（scrollYが0）は、対象外。
 * @param {{id: string, top: number}[]} headings 文書の順の見出し
 * @param {number} scrollY 画面の上端の位置（文書の先頭から。px）
 * @param {boolean} atBottom 文書の末尾までスクロールしているか
 * @returns {string|null}
 */
function currentHeadingId(headings, scrollY, atBottom = false, margin = HEADING_MARGIN) {
  if (!Array.isArray(headings) || headings.length === 0) return null;
  if (atBottom && scrollY > 0) return headings[headings.length - 1].id;
  const line = scrollY + margin;
  let found = null;
  for (const heading of headings) if (heading.top <= line) found = heading.id;   // 数千件でも、スクロールのたびに、十分軽い
  return found;
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

module.exports = { HEADING_MARGIN, MAX_HEADINGS, MAX_ID, MAX_TEXT, currentHeadingId, effectiveSidebarView, sanitizeOutline };
