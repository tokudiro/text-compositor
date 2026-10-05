'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { after, describe, test } = require('node:test');

const { isInsideDirectory, listDirectory } = require('../src/directory-list');
const { isOpenableFile } = require('../src/targets');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-dirlist-'));
after(() => fs.rmSync(root, { recursive: true, force: true }));

function makeTree(name, files, directories = []) {
  const base = path.join(root, name);
  fs.mkdirSync(base, { recursive: true });
  for (const directory of directories) fs.mkdirSync(path.join(base, directory), { recursive: true });
  for (const file of files) fs.writeFileSync(path.join(base, file), 'x');
  return base;
}

describe('isOpenableFile', () => {
  test('accepts the kinds the open dialog offers, ignoring case', () => {
    for (const name of ['a.md', 'A.MD', 'b.markdown', 'c.txt', 'd.csv', 'e.mmd', 'f.svg', 'g.yaml', 'h.py']) assert.ok(isOpenableFile(name), name);
  });

  test('rejects other files and names without an extension', () => {
    for (const name of ['a.png', 'b.pdf', 'c.exe', 'README', '.md-backup']) assert.equal(isOpenableFile(name), false, name);
  });
});

describe('isInsideDirectory', () => {
  const base = path.resolve(path.sep, 'docs', 'usage');

  test('the root itself and anything below it are inside', () => {
    assert.ok(isInsideDirectory(base, base));
    assert.ok(isInsideDirectory(base, path.join(base, 'images')));
    assert.ok(isInsideDirectory(base, path.join(base, 'a', 'b', 'c')));
  });

  test('siblings, parents and look-alike prefixes are outside', () => {
    assert.equal(isInsideDirectory(base, path.resolve(base, '..')), false);
    assert.equal(isInsideDirectory(base, path.resolve(path.sep, 'docs', 'other')), false);
    assert.equal(isInsideDirectory(base, `${base}-backup`), false);
  });

  test('dot-dot segments are resolved before comparing', () => {
    assert.equal(isInsideDirectory(base, path.join(base, '..', 'other')), false);
    assert.ok(isInsideDirectory(base, path.join(base, 'a', '..', 'b')));
  });

  test('a relative, empty or non-string argument is outside', () => {
    for (const value of ['', 'images', '..', undefined, null, 42]) assert.equal(isInsideDirectory(base, value), false, String(value));
    for (const value of ['', 'usage', undefined, null]) assert.equal(isInsideDirectory(value, base), false, String(value));
  });
});

describe('listDirectory', () => {
  test('lists only the direct children, folders first and then files by name', async () => {
    const base = makeTree('basic', ['b.md', 'a.md', 'c.csv'], ['zeta', 'alpha']);
    fs.writeFileSync(path.join(base, 'alpha', 'inner.md'), 'x');   // 孫は、一覧に出ない（再帰しない）
    const result = await listDirectory(base);
    assert.equal(result.ok, true);
    assert.deepEqual(result.entries.map((e) => `${e.type}:${e.name}`), ['directory:alpha', 'directory:zeta', 'file:a.md', 'file:b.md', 'file:c.csv']);
    assert.equal(result.entries[0].path, path.join(base, 'alpha'));
  });

  test('keeps only files the Viewer can open', async () => {
    const base = makeTree('filter', ['a.md', 'b.png', 'c.pdf', 'd.txt', 'noext']);
    const result = await listDirectory(base);
    assert.deepEqual(result.entries.map((e) => e.name), ['a.md', 'd.txt']);
  });

  test('hides dot folders, node_modules and .text-compositor, but not ordinary folders', async () => {
    const base = makeTree('hidden', [], ['.git', '.hidden', 'node_modules', '.text-compositor', 'docs']);
    const result = await listDirectory(base);
    assert.deepEqual(result.entries.map((e) => e.name), ['docs']);
  });

  test('sorts numbers by value', async () => {
    const base = makeTree('numeric', ['10.md', '2.md', '1.md']);
    const result = await listDirectory(base);
    assert.deepEqual(result.entries.map((e) => e.name), ['1.md', '2.md', '10.md']);
  });

  test('an empty folder gives an empty list', async () => {
    const result = await listDirectory(makeTree('empty', []));
    assert.deepEqual(result, { ok: true, entries: [] });
  });

  test('a missing folder fails with a message instead of throwing', async () => {
    const result = await listDirectory(path.join(root, 'missing'));
    assert.equal(result.ok, false);
    assert.match(result.message, /missing/);
  });

  test('a path that is a file fails with a message', async () => {
    const base = makeTree('afile', ['a.md']);
    const result = await listDirectory(path.join(base, 'a.md'));
    assert.equal(result.ok, false);
  });

  test('an empty or non-string argument fails with a message', async () => {
    for (const value of ['', undefined, null, 42]) assert.equal((await listDirectory(value)).ok, false);
  });

  test('follows a symbolic link by its target kind and skips a broken one', async (t) => {
    const base = makeTree('links', ['real.md'], ['realdir']);
    try {
      fs.symlinkSync(path.join(base, 'real.md'), path.join(base, 'link.md'));
      fs.symlinkSync(path.join(base, 'realdir'), path.join(base, 'linkdir'), 'junction');
      fs.symlinkSync(path.join(base, 'nothing.md'), path.join(base, 'broken.md'));
    } catch {
      t.skip('symbolic links cannot be created here');
      return;
    }
    const result = await listDirectory(base);
    assert.deepEqual(result.entries.map((e) => `${e.type}:${e.name}`), ['directory:linkdir', 'directory:realdir', 'file:link.md', 'file:real.md']);
  });

  test('reads through the injected readdir (so a slow or failing source can be simulated)', async () => {
    const result = await listDirectory('/virtual', { readdir: async () => { throw new Error('offline'); } });
    assert.equal(result.ok, false);
  });
});
