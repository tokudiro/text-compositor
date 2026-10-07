'use strict';
// 右クリックのメニューの、選択に関する項目（#409）。Electronなしで、テストできる。

// 「選択範囲で検索」（#429）。検索は、1つのテキストの中（1行程度）の一致を探すため、複数行の選択は、先頭の行だけを検索語にする。
// 長い選択は、検索語として使いにくいため、項目を出さない。
const SEARCH_SELECTION_MAX = 200;
const SEARCH_LABEL_MAX = 30;

/** 選択範囲から、検索語を作る。空・長すぎる選択は、null（項目を出さない）。 */
function searchTermFromSelection(selectionText) {
  if (typeof selectionText !== 'string' || selectionText.length > SEARCH_SELECTION_MAX) return null;
  const firstLine = selectionText.split(/\r?\n/).map((line) => line.replace(/\s+/g, ' ').trim()).find((line) => line !== '');
  return firstLine ?? null;
}

/** メニューに出す、検索語の表示。長いときは、先頭だけにして、「…」を付ける（検索語そのものは、省略しない）。 */
function searchLabel(term) {
  const shown = [...term].length > SEARCH_LABEL_MAX ? `${[...term].slice(0, SEARCH_LABEL_MAX).join('')}…` : term;
  return `「${shown}」を検索`;
}

/**
 * 「コピー」（選択範囲があるときだけ）と、「すべて選択」（常に）。
 * `onSearch`を渡したときは、「コピー」の次に、「選択範囲で検索」（#429）を出す。
 * `onSpeak`を渡したときは、続けて、読み上げの項目（#430）を出す。「選択範囲を読み上げる」は、選択範囲があるときだけ。
 * 読み上げ中（`speaking`）は、「読み上げを一時停止」（一時停止中は「読み上げを再開」）と「読み上げを止める」も出す。
 * 選択が外れていても、操作できるようにする。
 * `accelerator`は、メニューの右に、ショートカットを表示するためだけに付ける。`registerAccelerator: false`で、
 * キー操作そのものは、横取りしない（`Ctrl+C`・`Ctrl+A`は、Chromiumの既定の動きのまま）。
 * @param {{selectionText?: string}} params 右クリックしたときの、Electronの`context-menu`のパラメータ
 */
function buildSelectionContextMenuTemplate(params, { onCopy, onSearch, onSelectAll, onSpeak, onStopSpeaking, onPause, onResume, speaking = false, paused = false } = {}) {
  const items = [];
  const hasSelection = typeof params?.selectionText === 'string' && params.selectionText.trim() !== '';
  if (hasSelection) {
    items.push({ label: 'コピー', accelerator: 'CommandOrControl+C', registerAccelerator: false, click: () => onCopy?.() });
  }
  const term = onSearch && hasSelection ? searchTermFromSelection(params.selectionText) : null;
  if (term !== null) items.push({ label: searchLabel(term), click: () => onSearch(term) });
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

module.exports = { buildSelectionContextMenuTemplate, searchTermFromSelection, searchLabel, SEARCH_SELECTION_MAX };
