'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { describe, test } = require('node:test');

const { classifyNavigation, fileFromArgv, isOpenable } = require('../src/targets');

describe('isOpenable', () => {
  test('markdown and diagram files, case-insensitive', () => {
    for (const name of ['a.md', 'A.MARKDOWN', 'x.mmd', 'x.puml', 'x.d2', 'x.dot']) assert.equal(isOpenable(name), true, name);
  });
  test('other files are not openable', () => {
    for (const name of ['a.txt', 'a.pdf', 'a', 'a.md.bak']) assert.equal(isOpenable(name), false, name);
    assert.equal(isOpenable(undefined), false);
  });
});

describe('fileFromArgv', () => {
  const cwd = path.resolve(path.sep, 'work');
  const existing = (...files) => (p) => files.includes(p);

  test('the first existing openable file wins; options and other files are skipped', () => {
    const doc = path.join(cwd, 'docs', 'a.md');
    const result = fileFromArgv(['--flag', 'notes.txt', path.join('docs', 'a.md'), 'b.md'], { cwd, exists: existing(doc) });
    assert.equal(result, doc);
  });
  test('a file that does not exist is skipped', () => {
    assert.equal(fileFromArgv(['missing.md'], { cwd, exists: () => false }), null);
  });
  test('no arguments', () => {
    assert.equal(fileFromArgv([], { cwd }), null);
  });
});

describe('classifyNavigation', () => {
  test('web links open in the default browser', () => {
    assert.deepEqual(classifyNavigation('https://example.com/a'), { type: 'external', url: 'https://example.com/a' });
    assert.equal(classifyNavigation('http://example.com').type, 'external');
    assert.equal(classifyNavigation('mailto:a@example.com').type, 'external');
  });
  test('a dropped or linked markdown file opens in the viewer', () => {
    const file = path.resolve(path.sep, 'docs', '日本語 の.md');
    assert.deepEqual(classifyNavigation(pathToFileURL(file).href), { type: 'open', path: file });
  });
  test('other files, scripts and garbage never navigate the viewer', () => {
    assert.equal(classifyNavigation(pathToFileURL(path.resolve(path.sep, 'a.exe')).href).type, 'ignore');
    assert.equal(classifyNavigation('javascript:alert(1)').type, 'ignore');
    assert.equal(classifyNavigation('data:text/html,<b>x</b>').type, 'ignore');
    assert.equal(classifyNavigation('not a url').type, 'ignore');
  });
});
