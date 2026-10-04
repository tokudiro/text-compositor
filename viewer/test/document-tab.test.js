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
