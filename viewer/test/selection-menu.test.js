'use strict';
// 右クリックのメニューの、コピー・すべて選択（#409）。Electronを使わず、項目の内容と、出る条件を確認する。

const assert = require('node:assert/strict');
const { test } = require('node:test');

const { buildSelectionContextMenuTemplate } = require('../src/selection-menu');

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
  assert.deepEqual(labels(speaking).slice(3), ['選択範囲を読み上げる', '読み上げを止める']);
});

test('without a selection, Read aloud is hidden, but Stop stays while speaking', () => {
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {} })), ['すべて選択']);
  assert.deepEqual(labels(buildSelectionContextMenuTemplate({ selectionText: '' }, { onSpeak: () => {}, speaking: true })), ['すべて選択', undefined, '読み上げを止める']);
});

test('the speech items call the handlers with the selected text', () => {
  const calls = [];
  const template = buildSelectionContextMenuTemplate({ selectionText: '選んだ文字' }, { onSpeak: (t) => calls.push(['speak', t]), onStopSpeaking: () => calls.push(['stop']), speaking: true });
  for (const item of template.filter((i) => i.click)) item.click();
  assert.deepEqual(calls.filter(([k]) => k !== undefined), [['speak', '選んだ文字'], ['stop']]);
});
