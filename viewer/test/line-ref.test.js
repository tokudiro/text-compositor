'use strict';
// 右クリックのメニューの、行番号のコピー（#328・#357）。Electronを使わず、項目の内容と、位置から行を求める式を確認する。

const assert = require('node:assert/strict');
const path = require('node:path');
const { test } = require('node:test');

const { buildLineContextMenuTemplate, lineAtPointScript, lineRef } = require('../src/line-ref');

test('lineRef is the file name (without the folder) and the line', () => {
  assert.equal(lineRef(path.join('C:', 'docs', 'note.md'), 14), 'note.md:14');
  assert.equal(lineRef('check.md', 1), 'check.md:1');
});

test('the menu item shows the file name and the line in its label, and copies that text', () => {
  const copied = [];
  const [item, ...rest] = buildLineContextMenuTemplate({ file: path.join('C:', 'docs', 'note.md'), line: 14, onCopy: (text) => copied.push(text) });
  assert.equal(rest.length, 0);
  assert.equal(item.label, '行番号をコピー（note.md:14）');
  item.click();
  assert.deepEqual(copied, ['note.md:14']);
});

test('lineAtPointScript divides the position by the zoom factor (DIP to CSS pixels)', () => {
  assert.match(lineAtPointScript(300, 150, 1.5), /elementFromPoint\(200, 100\)/);
  assert.match(lineAtPointScript(30, 40), /elementFromPoint\(30, 40\)/);
  assert.match(lineAtPointScript(30, 40, 0), /elementFromPoint\(30, 40\)/);   // 不正な倍率は、1として扱う
});

test('lineAtPointScript is null for a non-numeric position, so nothing is injected into the page', () => {
  assert.equal(lineAtPointScript('1); alert(1', 5), 'null');
  assert.equal(lineAtPointScript(undefined, undefined), 'null');
});
