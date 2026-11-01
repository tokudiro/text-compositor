'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { DocumentTab } = require('../src/document-tab');

test('a new tab has no document and an empty history', () => {
  const tab = new DocumentTab();
  assert.equal(tab.file, null);
  assert.equal(tab.hasDocument, false);
  assert.equal(tab.canGoBack, false);
  assert.equal(tab.canGoForward, false);
  assert.equal(tab.isCsv, false);
});

test('isCsv follows the file name', () => {
  const tab = new DocumentTab();
  tab.file = 'C:\\data\\table.CSV';
  assert.equal(tab.isCsv, true);
  tab.file = 'C:\\docs\\note.md';
  assert.equal(tab.isCsv, false);
});

test('canGoBack and canGoForward come from the history', () => {
  const tab = new DocumentTab();
  tab.history.push('a.md');
  tab.history.push('b.md');
  assert.equal(tab.canGoBack, true);
  assert.equal(tab.canGoForward, false);
  tab.history.back();
  assert.equal(tab.canGoForward, true);
});

test('whenIdle resolves at once when nothing is converting', async () => {
  const tab = new DocumentTab();
  await tab.whenIdle();
});

test('whenIdle waits for the conversion and the last endOpen wakes every waiter', async () => {
  const tab = new DocumentTab();
  tab.beginOpen();
  const order = [];
  const first = tab.whenIdle().then(() => order.push('first'));
  const second = tab.whenIdle().then(() => order.push('second'));
  await Promise.resolve();
  assert.deepEqual(order, []);
  tab.endOpen();
  await Promise.all([first, second]);
  assert.deepEqual(order, ['first', 'second']);
  assert.equal(tab.idleWaiters.length, 0);
});

test('overlapping opens: the tab stays busy and in flight until the last one ends', async () => {
  const tab = new DocumentTab();
  assert.equal(tab.inFlight, false);
  tab.beginOpen();
  tab.beginOpen();   // 変換中に重なった依頼
  assert.deepEqual([tab.inFlight, tab.busy, tab.pending], [true, true, 2]);
  let idle = false;
  const waiting = tab.whenIdle().then(() => { idle = true; });
  tab.endOpen();   // 古い依頼が、置き換えられた
  await Promise.resolve();
  assert.deepEqual([tab.inFlight, tab.busy, idle], [true, true, false]);
  tab.endOpen();
  await waiting;
  assert.deepEqual([tab.inFlight, tab.busy, tab.pending, idle], [false, false, 0, true]);
  tab.endOpen();   // 数え間違いでも、負にならない
  assert.equal(tab.pending, 0);
});

test('snapshot carries what the toolbar needs and nothing about the window', () => {
  const tab = new DocumentTab();
  tab.file = 'note.csv';
  tab.status = 'ok';
  const snapshot = tab.snapshot();
  assert.deepEqual(Object.keys(snapshot).sort(), [
    'busy', 'canGoBack', 'canGoForward', 'currentHeading', 'diagnostics', 'file', 'hasDocument', 'isCsv', 'line', 'outline', 'search', 'status',
  ]);
  assert.equal(snapshot.file, 'note.csv');
  assert.equal(snapshot.isCsv, true);
  assert.equal(snapshot.status, 'ok');
});

test('the outline starts empty and is not shared between tabs (#329)', () => {
  const a = new DocumentTab();
  const b = new DocumentTab();
  assert.deepEqual(a.snapshot().outline, []);
  a.outline = [{ id: 'x', level: 1, text: 'X', depth: 0 }];
  assert.deepEqual(b.snapshot().outline, []);
  assert.equal(a.snapshot().outline.length, 1);
  // 見出しの位置（headingTops）は、画面へ送らない。いま読んでいる見出しは、タブごと
  a.headingTops = [{ id: 'x', top: 10 }];
  a.currentHeading = 'x';
  assert.equal('headingTops' in a.snapshot(), false);
  assert.equal(a.snapshot().currentHeading, 'x');
  assert.equal(b.snapshot().currentHeading, null);
});

test('two tabs do not share state', () => {
  const a = new DocumentTab();
  const b = new DocumentTab();
  a.history.push('a.md');
  a.search = { ...a.search, query: 'x' };
  assert.equal(b.history.canGoBack, false);
  assert.equal(b.search.query, '');
});

function shownTab(id, md, deps = []) {
  const tab = new DocumentTab(id);
  tab.file = md;
  tab.shown = { md, html: `${md}.html`, deps };
  return tab;
}

test('title is the file name, or a placeholder for an empty tab', () => {
  assert.equal(new DocumentTab(1).title, '新しいタブ');
  assert.equal(shownTab(2, 'C:\\docs\\note.md').title, 'note.md');
  assert.equal(shownTab(3, '/home/u/note.md').title, 'note.md');
});
