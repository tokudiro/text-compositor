'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { describe, test } = require('node:test');

const { checkOpenTarget, classifyNavigation, fileFromArgv, openDialogDirectory, openDialogFilters } = require('../src/targets');

describe('openDialogFilters', () => {
  const filters = openDialogFilters();
  const byName = (name) => filters.find((filter) => filter.name === name);

  test('the first filter is every openable kind, and the last is any file', () => {
    assert.equal(filters[0].name, '開けるファイルすべて');
    assert.deepEqual(filters.at(-1), { name: 'すべてのファイル', extensions: ['*'] });
    const kinds = filters.slice(1, -1).flatMap((filter) => filter.extensions);
    assert.deepEqual([...filters[0].extensions].sort(), [...kinds].sort());
  });

  test('each kind lists its extensions without the dot', () => {
    assert.deepEqual(byName('Markdown').extensions, ['md', 'markdown']);
    assert.deepEqual(byName('CSV').extensions, ['csv']);
    assert.deepEqual(byName('テキスト').extensions, ['txt']);
    const diagrams = filters.find((filter) => filter.name.startsWith('図'));
    for (const extension of ['mmd', 'puml', 'plantuml', 'pu', 'd2', 'dot', 'gv', 'svg']) assert.ok(diagrams.extensions.includes(extension), extension);
  });

  test('no extension appears in two kinds, and none has a dot', () => {
    const kinds = filters.slice(1, -1).flatMap((filter) => filter.extensions);
    assert.equal(new Set(kinds).size, kinds.length);
    assert.ok(kinds.every((extension) => !extension.startsWith('.')));
  });
});

describe('openDialogDirectory (#226)', () => {
  const fallback = path.resolve(path.sep, 'Users', 'me', 'Documents');
  const last = path.resolve(path.sep, 'work', 'docs');
  const fixed = path.resolve(path.sep, 'work', 'pinned');
  const statOf = (isDirectory) => () => ({ isDirectory: () => isDirectory });
  const missing = () => { throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' }); };
  const settings = (openDirectoryMode, extra = {}) => ({ openDirectoryMode, lastDirectory: last, fixedDirectory: fixed, ...extra });

  test('os leaves the start folder to the OS (no folder is given)', () => {
    assert.equal(openDialogDirectory(settings('os'), fallback, { statSync: statOf(true) }), undefined);
  });
  test('last starts in the folder opened last, and fixed in the chosen folder', () => {
    assert.equal(openDialogDirectory(settings('last'), fallback, { statSync: statOf(true) }), last);
    assert.equal(openDialogDirectory(settings('fixed'), fallback, { statSync: statOf(true) }), fixed);
  });
  test('an unset, gone or non-folder start folder falls back to the fallback', () => {
    for (const mode of ['last', 'fixed']) {
      for (const value of [null, undefined, '', 42]) {
        assert.equal(openDialogDirectory(settings(mode, { lastDirectory: value, fixedDirectory: value }), fallback), fallback, `${mode} ${String(value)}`);
      }
      assert.equal(openDialogDirectory(settings(mode), fallback, { statSync: missing }), fallback, mode);
      assert.equal(openDialogDirectory(settings(mode), fallback, { statSync: statOf(false) }), fallback, mode);
    }
  });
  test('each mode reads only its own folder', () => {
    assert.equal(openDialogDirectory(settings('fixed', { fixedDirectory: null }), fallback, { statSync: statOf(true) }), fallback);
    assert.equal(openDialogDirectory(settings('last', { lastDirectory: null }), fallback, { statSync: statOf(true) }), fallback);
  });
});

describe('checkOpenTarget (#196)', () => {
  const statOf = (isDirectory) => () => ({ isDirectory: () => isDirectory });
  const missing = () => { throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' }); };

  test('any existing file can be opened, whatever its extension; the worker decides by content', () => {
    for (const name of ['a.md', 'memo.txt', 'README', 'app.log', 'x.unknown', 'image.png', 'data.csv']) {
      assert.deepEqual(checkOpenTarget(path.join('docs', name), { statSync: statOf(false) }), { ok: true }, name);
    }
  });

  test('a missing file says so, with its name', () => {
    const result = checkOpenTarget(path.join('docs', '見つからない.txt'), { statSync: missing });
    assert.equal(result.ok, false);
    assert.equal(result.message, 'ファイルが見つかりません: 見つからない.txt');
  });

  test('a folder is not opened, and the message says what to choose', () => {
    const result = checkOpenTarget(path.join('docs', 'sub'), { statSync: statOf(true) });
    assert.equal(result.ok, false);
    assert.match(result.message, /^フォルダは開けません: sub/);
  });

  test('an empty or non-string path is rejected', () => {
    for (const value of ['', undefined, null, 42]) assert.equal(checkOpenTarget(value).ok, false);
  });
});

describe('fileFromArgv', () => {
  const cwd = path.resolve(path.sep, 'work');

  test('the first file argument wins, and options are skipped; the extension does not matter', () => {
    assert.equal(fileFromArgv(['--flag', 'notes.txt', 'b.md'], { cwd }), path.join(cwd, 'notes.txt'));
    assert.equal(fileFromArgv(['README'], { cwd }), path.join(cwd, 'README'));
  });
  test('relative paths use the given working directory; absolute paths are kept', () => {
    assert.equal(fileFromArgv([path.join('docs', 'a.md')], { cwd }), path.join(cwd, 'docs', 'a.md'));
    const absolute = path.resolve(path.sep, 'x', 'y.txt');
    assert.equal(fileFromArgv([absolute], { cwd }), absolute);
  });
  test('a missing file is not skipped here (it is reported when opening)', () => {
    assert.equal(fileFromArgv(['missing.md'], { cwd }), path.join(cwd, 'missing.md'));
  });
  test('no arguments, or only options and empty strings', () => {
    assert.equal(fileFromArgv([], { cwd }), null);
    assert.equal(fileFromArgv(['--a', '-b', ''], { cwd }), null);
  });
});

describe('classifyNavigation', () => {
  test('web links open in the default browser', () => {
    assert.deepEqual(classifyNavigation('https://example.com/a'), { type: 'external', url: 'https://example.com/a' });
    assert.equal(classifyNavigation('http://example.com').type, 'external');
    assert.equal(classifyNavigation('mailto:a@example.com').type, 'external');
  });
  test('a dropped or linked local file opens in the viewer, whatever its extension (#196)', () => {
    const markdown = path.resolve(path.sep, 'docs', '日本語 の.md');
    assert.deepEqual(classifyNavigation(pathToFileURL(markdown).href), { type: 'open', path: markdown });
    const text = path.resolve(path.sep, 'logs', 'app.txt');
    assert.deepEqual(classifyNavigation(pathToFileURL(text).href), { type: 'open', path: text });
    assert.equal(classifyNavigation(pathToFileURL(path.resolve(path.sep, 'a.exe')).href).type, 'open');   // 開くときに、バイナリとして案内する
  });
  test('scripts and garbage never navigate the viewer', () => {
    assert.equal(classifyNavigation('javascript:alert(1)').type, 'ignore');
    assert.equal(classifyNavigation('data:text/html,<b>x</b>').type, 'ignore');
    assert.equal(classifyNavigation('not a url').type, 'ignore');
  });
});
