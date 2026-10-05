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
