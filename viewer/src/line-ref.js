'use strict';
// 行番号（#328・#357）。右クリックのメニューに、`ファイル名:行`をコピーする項目を出す。
// メニューを出す位置（x・y）から、いちばん内側のブロックの行を求める式と、メニューの項目は、ここに置く（Electronなしで、テストできる）。

const path = require('node:path');

/** `ファイル名:行`（フォルダは付けない）。例: `check.md:14`。 */
function lineRef(file, line) {
  return `${path.basename(file)}:${line}`;
}

/**
 * 右クリックした位置の、いちばん内側のブロックの`data-line`を、ページ内で求める式。ブロックの外なら、null。
 * xとyは、内容のビューの座標（DIP）。ページのズームで、CSSのピクセルとは違うため、ズームの倍率で割る。
 */
function lineAtPointScript(x, y, zoomFactor = 1) {
  const factor = Number.isFinite(zoomFactor) && zoomFactor > 0 ? zoomFactor : 1;
  const cssX = Number(x) / factor;
  const cssY = Number(y) / factor;
  if (!Number.isFinite(cssX) || !Number.isFinite(cssY)) return 'null';
  return `(() => { const e = document.elementFromPoint(${cssX}, ${cssY})?.closest('[data-line]'); `
    + `const n = e ? Number.parseInt(e.getAttribute('data-line'), 10) : NaN; return Number.isInteger(n) ? n : null; })()`;
}

/** 右クリックのメニューの、行番号をコピーする項目。 */
function buildLineContextMenuTemplate({ file, line, onCopy }) {
  return [{ label: `行番号をコピー（${lineRef(file, line)}）`, click: () => onCopy?.(lineRef(file, line)) }];
}

module.exports = { buildLineContextMenuTemplate, lineAtPointScript, lineRef };
