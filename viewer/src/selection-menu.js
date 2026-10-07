'use strict';
// 右クリックのメニューの、選択に関する項目（#409）。Electronなしで、テストできる。

/**
 * 「コピー」（選択範囲があるときだけ）と、「すべて選択」（常に）。
 * `onSpeak`を渡したときは、続けて、読み上げの項目（#430）を出す。「選択範囲を読み上げる」は、選択範囲があるときだけ。
 * 読み上げ中（`speaking`）は、「読み上げを一時停止」（一時停止中は「読み上げを再開」）と「読み上げを止める」も出す。
 * 選択が外れていても、操作できるようにする。
 * `accelerator`は、メニューの右に、ショートカットを表示するためだけに付ける。`registerAccelerator: false`で、
 * キー操作そのものは、横取りしない（`Ctrl+C`・`Ctrl+A`は、Chromiumの既定の動きのまま）。
 * @param {{selectionText?: string}} params 右クリックしたときの、Electronの`context-menu`のパラメータ
 */
function buildSelectionContextMenuTemplate(params, { onCopy, onSelectAll, onSpeak, onStopSpeaking, onPause, onResume, speaking = false, paused = false } = {}) {
  const items = [];
  const hasSelection = typeof params?.selectionText === 'string' && params.selectionText.trim() !== '';
  if (hasSelection) {
    items.push({ label: 'コピー', accelerator: 'CommandOrControl+C', registerAccelerator: false, click: () => onCopy?.() });
  }
  items.push({ label: 'すべて選択', accelerator: 'CommandOrControl+A', registerAccelerator: false, click: () => onSelectAll?.() });
  if (onSpeak) {
    const speech = [];
    if (hasSelection) speech.push({ label: '選択範囲を読み上げる', click: () => onSpeak(params.selectionText) });
    if (speaking && paused) speech.push({ label: '読み上げを再開', click: () => onResume?.() });
    else if (speaking) speech.push({ label: '読み上げを一時停止', click: () => onPause?.() });
    if (speaking) speech.push({ label: '読み上げを止める', click: () => onStopSpeaking?.() });
    if (speech.length > 0) items.push({ type: 'separator' }, ...speech);
  }
  return items;
}

module.exports = { buildSelectionContextMenuTemplate };
