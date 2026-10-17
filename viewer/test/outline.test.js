'use strict';
const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { MAX_HEADINGS, MAX_ID, MAX_TEXT, effectiveSidebarView, sanitizeOutline } = require('../src/outline');

describe('sanitizeOutline (#329)', () => {
  test('keeps the order and gives each heading a depth relative to the shallowest one', () => {
    const result = sanitizeOutline([
      { id: 'a', level: 1, text: 'A' }, { id: 'b', level: 2, text: 'B' }, { id: 'c', level: 3, text: 'C' }, { id: 'd', level: 2, text: 'D' },
    ]);
    assert.deepEqual(result.map((i) => [i.id, i.depth]), [['a', 0], ['b', 1], ['c', 2], ['d', 1]]);
  });

  test('a document that starts at H2 is not indented (depth is relative)', () => {
    const result = sanitizeOutline([{ id: 'x', level: 2, text: 'X' }, { id: 'y', level: 3, text: 'Y' }]);
    assert.deepEqual(result.map((i) => i.depth), [0, 1]);
    assert.deepEqual(result.map((i) => i.level), [2, 3]);   // 元のレベルは、そのまま残す
  });

  test('items of the wrong shape are dropped, and anything that is not a list gives an empty outline', () => {
    const result = sanitizeOutline([
      null, 5, 'h', { id: '', level: 1, text: 'no id' }, { id: 5, level: 1, text: 'id not a string' },
      { id: 'a', level: 0, text: 'low' }, { id: 'b', level: 7, text: 'high' }, { id: 'c', level: 1.5, text: 'fraction' }, { id: 'd', level: '2', text: 'string' },
      { id: 'ok', level: 2, text: 'fine' },
    ]);
    assert.deepEqual(result.map((i) => i.id), ['ok']);
    for (const value of [undefined, null, 'x', 3, {}, { length: 2 }]) assert.deepEqual(sanitizeOutline(value), []);
    assert.deepEqual(sanitizeOutline([]), []);
  });

  test('white space in the text is collapsed, a missing or blank text falls back to the id, a long text is shortened', () => {
    const result = sanitizeOutline([
      { id: 'a', level: 1, text: '  two\n  lines\t here ' }, { id: 'blank', level: 1, text: '   ' }, { id: 'none', level: 1 },
      { id: 'long', level: 1, text: 'x'.repeat(MAX_TEXT + 50) },
    ]);
    assert.equal(result[0].text, 'two lines here');
    assert.equal(result[1].text, 'blank');
    assert.equal(result[2].text, 'none');
    assert.equal(result[3].text.length, MAX_TEXT + 1);
    assert.equal(result[3].text.endsWith('…'), true);
  });

  test('an id that is too long is dropped, and the list is capped', () => {
    assert.deepEqual(sanitizeOutline([{ id: 'x'.repeat(MAX_ID + 1), level: 1, text: 't' }]), []);
    const many = Array.from({ length: MAX_HEADINGS + 10 }, (_, i) => ({ id: `h${i}`, level: 1, text: `T${i}` }));
    assert.equal(sanitizeOutline(many).length, MAX_HEADINGS);
  });

  test('text that looks like HTML stays plain text (it is shown with textContent)', () => {
    assert.equal(sanitizeOutline([{ id: 'a', level: 1, text: '<img src=x onerror=alert(1)>' }])[0].text, '<img src=x onerror=alert(1)>');
  });

  test('the input is not changed', () => {
    const input = [{ id: 'a', level: 2, text: ' A ' }];
    sanitizeOutline(input);
    assert.deepEqual(input, [{ id: 'a', level: 2, text: ' A ' }]);
  });
});

describe('effectiveSidebarView (#329)', () => {
  const view = (overrides) => effectiveSidebarView({ explicit: null, showFileTree: true, showOutline: true, hasRoot: false, ...overrides });

  test('with no choice, a single file shows the outline and an open folder or project shows the files', () => {
    assert.equal(view({ hasRoot: false }), 'outline');
    assert.equal(view({ hasRoot: true }), 'files');
  });

  test('the choice of the user wins when that view is available', () => {
    assert.equal(view({ explicit: 'files', hasRoot: false }), 'files');
    assert.equal(view({ explicit: 'outline', hasRoot: true }), 'outline');
  });

  test('a view that is switched off is never shown, even if it was chosen', () => {
    assert.equal(view({ explicit: 'outline', showOutline: false, hasRoot: false }), 'files');
    assert.equal(view({ explicit: 'files', showFileTree: false, hasRoot: true }), 'outline');
  });

  test('with both switched off there is no view', () => {
    assert.equal(view({ showFileTree: false, showOutline: false }), null);
  });

  test('an unknown choice is ignored', () => {
    assert.equal(view({ explicit: 'other', hasRoot: true }), 'files');
    assert.equal(view({ explicit: 5, hasRoot: false }), 'outline');
  });
});
