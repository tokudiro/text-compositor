'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { DocumentTab, tabsAffectedBy } = require('../src/document-tab');

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

test('whenIdle waits for the conversion and releaseIdleWaiters wakes every waiter', async () => {
  const tab = new DocumentTab();
  tab.inFlight = true;
  const order = [];
  const first = tab.whenIdle().then(() => order.push('first'));
  const second = tab.whenIdle().then(() => order.push('second'));
  await Promise.resolve();
  assert.deepEqual(order, []);
  tab.inFlight = false;
  tab.releaseIdleWaiters();
  await Promise.all([first, second]);
  assert.deepEqual(order, ['first', 'second']);
  assert.equal(tab.idleWaiters.length, 0);
});

test('snapshot carries what the toolbar needs and nothing about the window', () => {
  const tab = new DocumentTab();
  tab.file = 'note.csv';
  tab.status = 'ok';
  const snapshot = tab.snapshot();
  assert.deepEqual(Object.keys(snapshot).sort(), [
    'busy', 'canGoBack', 'canGoForward', 'diagnostics', 'file', 'hasDocument', 'isCsv', 'line', 'search', 'status',
  ]);
  assert.equal(snapshot.file, 'note.csv');
  assert.equal(snapshot.isCsv, true);
  assert.equal(snapshot.status, 'ok');
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

test('watchedFiles: the manuscript and its dependencies; only the manuscript when it failed to convert', () => {
  const tab = shownTab(1, 'a.md', ['a.png']);
  assert.deepEqual(tab.watchedFiles, ['a.md', 'a.png']);
  tab.file = 'b.md';   // 別の原稿を開こうとして、変換に失敗した（表示は、前の原稿のまま）
  assert.deepEqual(tab.watchedFiles, ['b.md']);
  assert.deepEqual(new DocumentTab(2).watchedFiles, []);
});

test('tabsAffectedBy: only the tabs that watch a saved file, including a tab that is not shown', () => {
  const a = shownTab(1, 'a.md', ['shared.png']);
  const b = shownTab(2, 'b.md', ['shared.png']);
  const c = shownTab(3, 'c.md');
  const empty = new DocumentTab(4);
  const tabs = [a, b, c, empty];
  assert.deepEqual(tabsAffectedBy(tabs, ['b.md']).map((t) => t.id), [2]);
  assert.deepEqual(tabsAffectedBy(tabs, ['shared.png']).map((t) => t.id), [1, 2]);
  assert.deepEqual(tabsAffectedBy(tabs, ['a.md', 'c.md']).map((t) => t.id), [1, 3]);
  assert.deepEqual(tabsAffectedBy(tabs, ['other.md']), []);
});

test('title is the file name, or a placeholder for an empty tab', () => {
  assert.equal(new DocumentTab(1).title, '新しいタブ');
  assert.equal(shownTab(2, 'C:\\docs\\note.md').title, 'note.md');
  assert.equal(shownTab(3, '/home/u/note.md').title, 'note.md');
});
