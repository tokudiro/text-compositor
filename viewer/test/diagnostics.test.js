'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const { formatLocation, summarize, visibleDiagnostics } = require('../src/diagnostics');

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
});
