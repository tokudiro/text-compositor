'use strict';
// 右クリックのメニューの、コピー・すべて選択（#409）。Electronを使わず、項目の内容と、出る条件を確認する。

const assert = require('node:assert/strict');
const { test } = require('node:test');

const { buildSelectionContextMenuTemplate, searchLabel, searchTermFromSelection, SEARCH_SELECTION_MAX } = require('../src/selection-menu');

const labels = (template) => template.map((item) => item.label);

test('with a selection, the menu has Copy and then Select all', () => {
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '選んだ文字' })), ['コピー', 'すべて選択']);
});

test('without a selection, only Select all is shown', () => {
  for (const selectionText of ['', '   ', '\n\t', undefined]) {
    assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText })), ['すべて選択'], JSON.stringify(selectionText));
  }
  assert.deepEqual(labels(buildSelectionContextMenuTemplate(undefined)), ['すべて選択']);
});

test('the items call the given handlers', () => {
  const calls = [];
  const template = buildSelectionContextMenuTemplate({ selectionText: 'x' }, { onCopy: () => calls.push('copy'), onSelectAll: () => calls.push('all') });
  for (const item of template) item.click();
  assert.deepEqual(calls, ['copy', 'all']);
});

test('clicking without handlers does not throw', () => {
  for (const item of buildSelectionContextMenuTemplate({ selectionText: 'x' })) item.click();
});

test('the shortcuts are shown but not registered, so the key presses are left to Chromium', () => {
  for (const item of buildSelectionContextMenuTemplate({ selectionText: 'x' })) {
    assert.ok(item.accelerator);
    assert.equal(item.registerAccelerator, false);
  }
});

test('speech items appear only when onSpeak is given (#430)', () => {
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: 'x' }, { speaking: true })), ['コピー', 'すべて選択']);
});

test('with a selection, Read aloud follows a separator; Stop is shown only while speaking', () => {
  const idle = buildSelectionContextMenuTemplate({ selectionText: 'x' }, { onSpeak: () => {} });
  assert.deepEqual(labels(idle), ['コピー', 'すべて選択', undefined, '選択範囲を読み上げる']);
  assert.equal(idle[2].type, 'separator');
  const speaking = buildSelectionContextMenuTemplate({ selectionText: 'x' }, { onSpeak: () => {}, speaking: true });
  assert.deepEqual(labels(speaking).slice(3), ['選択範囲を読み上げる', '読み上げを一時停止', '読み上げを止める']);
});

test('without a selection, Read aloud is hidden, but Stop stays while speaking', () => {
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {} })), ['すべて選択']);
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {}, speaking: true })), ['すべて選択', undefined, '読み上げを一時停止', '読み上げを止める']);
});

test('the speech items call the handlers with the selected text', () => {
  const calls = [];
  const template = buildSelectionContextMenuTemplate({ selectionText: '選んだ文字' }, { onSpeak: (t) => calls.push(['speak', t]), onStopSpeaking: () => calls.push(['stop']), speaking: true });
  for (const item of template.filter((i) => i.click)) item.click();
  assert.deepEqual(calls.filter(([k]) => k !== undefined), [['speak', '選んだ文字'], ['stop']]);
});

test('while paused, Resume replaces Pause; the handlers are called', () => {
  const calls = [];
  const template = buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {}, onPause: () => calls.push('pause'), onResume: () => calls.push('resume'), speaking: true, paused: true });
  assert.deepEqual(labels(template), ['すべて選択', undefined, '読み上げを再開', '読み上げを止める']);
  template[2].click();
  const running = buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {}, onPause: () => calls.push('pause'), speaking: true });
  running[2].click();
  assert.deepEqual(calls, ['resume', 'pause']);
});

// -- 選択範囲で検索（#429） ---------------------------------------------------------------------

test('Search for the selection appears after Copy only when onSearch is given and there is a selection', () => {
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '検索語' })), ['コピー', 'すべて選択']);
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '検索語' }, { onSearch: () => {} })), ['コピー', '「検索語」を検索', 'すべて選択']);
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '  ' }, { onSearch: () => {} })), ['すべて選択']);
});

test('clicking Search passes the search term (not the label) to onSearch', () => {
  const calls = [];
  const template = buildSelectionContextMenuTemplate({ selectionText: '  a   b  ' }, { onSearch: (term) => calls.push(term) });
  template[1].click();
  assert.deepEqual(calls, ['a b']);
});

test('a long selection is not offered, the limit is inclusive', () => {
  assert.equal(searchTermFromSelection('x'.repeat(SEARCH_SELECTION_MAX)), 'x'.repeat(SEARCH_SELECTION_MAX));
  assert.equal(searchTermFromSelection('x'.repeat(SEARCH_SELECTION_MAX + 1)), null);
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: 'x'.repeat(SEARCH_SELECTION_MAX + 1) }, { onSearch: () => {} })), ['コピー', 'すべて選択']);
});

test('a multi-line selection searches its first non-empty line, with whitespace collapsed', () => {
  assert.equal(searchTermFromSelection('\n\n  最初の  行 \r\n次の行'), '最初の 行');
  assert.equal(searchTermFromSelection(' \n\t'), null);
  assert.equal(searchTermFromSelection(undefined), null);
});

test('the label is shortened for display only, by characters, not by UTF-16 units', () => {
  assert.equal(searchLabel('短い'), '「短い」を検索');
  const long = '𠮷'.repeat(31);
  assert.equal(searchLabel(long), `「${'𠮷'.repeat(30)}…」を検索`);
  assert.equal(searchLabel('あ'.repeat(30)), `「${'あ'.repeat(30)}」を検索`);
});
