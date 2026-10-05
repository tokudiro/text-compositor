'use strict';
// 右クリックのメニューの、選択に関する項目（#409）。Electronなしで、テストできる。

/**
 * 「コピー」（選択範囲があるときだけ）と、「すべて選択」（常に）。
 * `accelerator`は、メニューの右に、ショートカットを表示するためだけに付ける。`registerAccelerator: false`で、
 * キー操作そのものは、横取りしない（`Ctrl+C`・`Ctrl+A`は、Chromiumの既定の動きのまま）。
 * @param {{selectionText?: string}} params 右クリックしたときの、Electronの`context-menu`のパラメータ
 */
function buildSelectionContextMenuTemplate(params, { onCopy, onSelectAll } = {}) {
  const items = [];
  if (typeof params?.selectionText === 'string' && params.selectionText.trim() !== '') {
    items.push({ label: 'コピー', accelerator: 'CommandOrControl+C', registerAccelerator: false, click: () => onCopy?.() });
  }
  items.push({ label: 'すべて選択', accelerator: 'CommandOrControl+A', registerAccelerator: false, click: () => onSelectAll?.() });
  return items;
}

module.exports = { buildSelectionContextMenuTemplate };
