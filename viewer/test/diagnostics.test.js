'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const { formatLocation, splitMessage, summarize, visibleDiagnostics } = require('../src/diagnostics');

describe('formatLocation', () => {
  test('file name and line', () => {
    assert.equal(formatLocation(path.join('C:', 'docs', 'a.md'), 5), 'a.md:5');
  });
  test('file name only, or empty when unknown', () => {
    assert.equal(formatLocation(path.join('docs', 'a.md'), null), 'a.md');
    assert.equal(formatLocation(null, 3), '');
  });
});

describe('summarize', () => {
  const diagnostics = [
    { severity: 'info', message: 'reused browser' },
    { severity: 'warning', message: 'image not found', file: '/x/a.md', line: 3 },
    { severity: 'error', message: 'unknown variable: foo', file: '/x/a.md', line: 34, detail: 'compile output' },
    { severity: 'hint', message: 'try this' },
  ];

  test('info is hidden and errors come first', () => {
    const items = visibleDiagnostics(diagnostics);
    assert.deepEqual(items.map((d) => d.severity), ['error', 'warning', 'hint']);
    assert.equal(items[0].detail, 'compile output');
  });

  test('the banner shows the first error with its markdown line', () => {
    const summary = summarize(diagnostics);
    assert.equal(summary.hasError, true);
    assert.equal(summary.banner, 'unknown variable: foo（a.md:34）');
    assert.equal(summary.warnings, 1);
  });

  test('no errors: empty banner, warnings are counted', () => {
    const summary = summarize([{ severity: 'warning', message: 'w' }]);
    assert.deepEqual([summary.hasError, summary.banner, summary.warnings], [false, '', 1]);
  });

  test('an error without a location has no parentheses', () => {
    assert.equal(summarize([{ severity: 'error', message: 'boom' }]).banner, 'boom');
  });

  test('errors and warnings are counted, and the first warning is summarized', () => {
    const summary = summarize(diagnostics);
    assert.deepEqual([summary.errors, summary.warnings], [1, 1]);
    assert.equal(summary.warningBanner, 'image not found（a.md:3）');
    assert.equal(summarize([]).warningBanner, '');
  });
});

describe('a long message is split into a summary and a detail (#202)', () => {
  test('only the first line is the summary; the rest goes to the detail', () => {
    const { message, detail } = splitMessage('rendering failed for a.md:\nParse error on line 3\n  ^', null);
    assert.equal(message, 'rendering failed for a.md:');
    assert.equal(detail, 'Parse error on line 3\n  ^');
  });

  test('an existing detail is kept after the extra lines; a single line has no detail', () => {
    assert.equal(splitMessage('short', null).detail, null);
    assert.equal(splitMessage('short', 'compile output').detail, 'compile output');
    assert.equal(splitMessage('first\nsecond', 'compile output').detail, 'second\ncompile output');
  });

  test('the banner shows the summary only, so the same long text does not appear twice', () => {
    const summary = summarize([{ severity: 'error', message: 'failed:\nlong original text', file: '/x/a.md', line: 5 }]);
    assert.equal(summary.banner, 'failed:（a.md:5）');
    assert.equal(summary.items[0].detail, 'long original text');
  });
});
