'use strict';
// リンク先の表示（#362）。ホバーで下方に出す文字列と、右クリックのメニューの項目を、Electronなしで作る。
// 相対リンクは、ブラウザに任せると、変換結果の置き場所（キャッシュ）が基準になる。ここでは、原稿のフォルダを基準にした場所を示す（#361）。

const path = require('node:path');

const { isOpenableFile, resolveRelativeLink } = require('./targets');
const { REVEAL_LABEL } = require('./path-menu');

/**
 * リンクの飛び先を、利用者に見せる文字列にする。
 *   - 相対リンク: 原稿のフォルダを基準にした場所（アンカーがあれば、`#見出し`も付ける）
 *   - それ以外（http・mailto・文書内の`#…`）: hrefの属性の値のまま
 * href が空のとき、または、原稿が無いときの相対リンクは、null（表示するものがない）。
 */
function describeLink(href, markdownFile) {
  if (typeof href !== 'string' || !href) return null;
  if (!markdownFile) return /^#|^[a-z][a-z0-9+.-]*:/i.test(href) ? href : null;
  const target = resolveRelativeLink(href, markdownFile);
  if (!target) return href;
  return target.fragment ? `${target.path}#${target.fragment}` : target.path;
}

/**
 * 右クリックした位置の、リンク（`a[href]`）の href 属性を、ページ内で求める式。リンクの外なら、null。
 * xとyは、内容のビューの座標（DIP）。ページのズームで、CSSのピクセルとは違うため、ズームの倍率で割る（`lineAtPointScript`と同じ）。
 * `params.linkURL`は、変換結果の置き場所を基準に解決済みで、相対リンクの元の書き方が分からないため、属性の値を直接読む。
 */
function linkAtPointScript(x, y, zoomFactor = 1) {
  const factor = Number.isFinite(zoomFactor) && zoomFactor > 0 ? zoomFactor : 1;
  const cssX = Number(x) / factor;
  const cssY = Number(y) / factor;
  if (!Number.isFinite(cssX) || !Number.isFinite(cssY)) return 'null';
  return `(() => { const a = document.elementFromPoint(${cssX}, ${cssY})?.closest('a[href]'); `
    + `return a ? a.getAttribute('href') : null; })()`;
}

/**
 * 右クリックのメニューの、リンクの項目（アドレスのコピー・リンクを開く）。
 * 相対リンクのファイルには、続けて、「新しいタブで開く」（設定「複数のタブ」がオンで、開ける文書のときだけ）と、
 * 「エクスプローラーで表示」を出す（#428）。外部リンク・文書内のアンカー（#…）には、出さない。
 */
function buildLinkContextMenuTemplate({ href, markdownFile, canOpenInNewTab = false, onCopy, onOpen, onOpenInNewTab, onReveal }) {
  const address = describeLink(href, markdownFile);
  if (!address) return [];
  const items = [
    { label: 'リンクを開く', click: () => onOpen?.(href) },
    { label: 'リンクのアドレスをコピー', click: () => onCopy?.(address) },
  ];
  const target = markdownFile ? resolveRelativeLink(href, markdownFile) : null;
  if (target) {
    if (canOpenInNewTab && isOpenableFile(target.path)) items.push({ label: '新しいタブで開く', click: () => onOpenInNewTab?.(target.path) });
    items.push({ label: REVEAL_LABEL, click: () => onReveal?.(target.path, false) });
  }
  return items;
}

/**
 * 見出しのリンク（#337）としてコピーする文字列。`ファイル名#見出しのid`（フォルダは付けない）。別の文書から`[…](ファイル名#見出し)`と
 * 書けば、隣のファイルの見出しへ飛べる（#361）。idが空のときは、null。
 */
function headingLinkRef(file, id) {
  if (typeof id !== 'string' || !id || !file) return null;
  return `${path.basename(file)}#${id}`;
}

module.exports = { describeLink, linkAtPointScript, buildLinkContextMenuTemplate, headingLinkRef };
