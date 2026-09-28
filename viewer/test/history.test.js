'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { NavigationHistory, DEFAULT_MAX_ENTRIES } = require('../src/history');

test('NavigationHistory: initial state is empty', () => {
  const history = new NavigationHistory();
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.equal(history.current, null);
  assert.equal(history.peekBack(), null);
  assert.equal(history.peekForward(), null);
  assert.equal(history.back(), null);
  assert.equal(history.forward(), null);
});

test('NavigationHistory: push single entry', () => {
  const history = new NavigationHistory();
  assert.equal(history.push('doc-a.md'), true);
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.deepEqual(history.current, { file: 'doc-a.md', scrollY: 0 });
});

test('NavigationHistory: pushing same file does not add duplicate entry', () => {
  const history = new NavigationHistory();
  assert.equal(history.push('doc-a.md'), true);
  assert.equal(history.push('doc-a.md'), false);
  assert.equal(history.entries.length, 1);
  assert.equal(history.canGoBack, false);
});

test('NavigationHistory: updateCurrentScroll updates scrollY of current entry', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.updateCurrentScroll(250);
  assert.deepEqual(history.current, { file: 'doc-a.md', scrollY: 250 });
});

test('NavigationHistory: navigate between multiple files and go back and forward', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.updateCurrentScroll(120);

  history.push('doc-b.md');
  history.updateCurrentScroll(340);

  history.push('doc-c.md');

  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
  assert.deepEqual(history.current, { file: 'doc-c.md', scrollY: 0 });

  // peekBack does not mutate index
  assert.deepEqual(history.peekBack(), { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.current.file, 'doc-c.md');

  // Go back to doc-b
  const back1 = history.back();
  assert.deepEqual(back1, { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, true);
  assert.deepEqual(history.peekForward(), { file: 'doc-c.md', scrollY: 0 });

  // Go back to doc-a
  const back2 = history.back();
  assert.deepEqual(back2, { file: 'doc-a.md', scrollY: 120 });
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, true);

  // Go forward to doc-b
  const fwd1 = history.forward();
  assert.deepEqual(fwd1, { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, true);

  // Go forward to doc-c
  const fwd2 = history.forward();
  assert.deepEqual(fwd2, { file: 'doc-c.md', scrollY: 0 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: new navigation truncates forward history (branching)', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');
  history.push('doc-c.md');

  history.back(); // at doc-b
  assert.equal(history.canGoForward, true);

  history.push('doc-d.md');
  assert.equal(history.canGoForward, false);
  assert.equal(history.canGoBack, true);
  assert.deepEqual(history.entries.map((e) => e.file), ['doc-a.md', 'doc-b.md', 'doc-d.md']);
  assert.equal(history.current.file, 'doc-d.md');
});

test('NavigationHistory: max entries limit drops oldest entries', () => {
  const history = new NavigationHistory({ maxEntries: 3 });
  history.push('1.md');
  history.push('2.md');
  history.push('3.md');
  assert.equal(history.entries.length, 3);
  assert.deepEqual(history.entries.map((e) => e.file), ['1.md', '2.md', '3.md']);

  history.push('4.md');
  assert.equal(history.entries.length, 3);
  assert.deepEqual(history.entries.map((e) => e.file), ['2.md', '3.md', '4.md']);
  assert.equal(history.current.file, '4.md');
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: updating scroll position after going back and forth', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');
  history.back(); // at doc-a
  history.updateCurrentScroll(500); // user scrolled doc-a
  assert.equal(history.current.scrollY, 500);

  history.forward(); // at doc-b
  history.updateCurrentScroll(300); // user scrolled doc-b
  assert.equal(history.current.scrollY, 300);

  history.back(); // back at doc-a
  assert.equal(history.current.scrollY, 500);
});

test('NavigationHistory: rollback on navigation failure', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');

  // Attempt to go back
  const target = history.back();
  assert.equal(target.file, 'doc-a.md');
  assert.equal(history.current.file, 'doc-a.md');

  // If opening doc-a fails, rollback by calling forward()
  history.forward();
  assert.equal(history.current.file, 'doc-b.md');
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: clear resets all state', () => {
  const history = new NavigationHistory();
  history.push('a.md');
  history.push('b.md');
  history.clear();
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.equal(history.current, null);
  assert.equal(history.entries.length, 0);
});

