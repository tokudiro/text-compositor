'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { cacheRoot, cacheUsage, clearCache, htmlFileName, isWritableBeside, workLocation } = require('../src/workdir');

function temporaryDirectory() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-workdir-'));
}

test('the app folder sits under the same cache folder as the Python side (#258)', () => {
  assert.equal(cacheRoot({ platform: 'win32', env: { LOCALAPPDATA: 'C:\\Users\\a\\AppData\\Local' }, home: 'C:\\Users\\a' }),
    'C:\\Users\\a\\AppData\\Local\\text-compositor\\Cache\\viewer');
  assert.equal(cacheRoot({ platform: 'win32', env: {}, home: 'C:\\Users\\a' }), 'C:\\Users\\a\\AppData\\Local\\text-compositor\\Cache\\viewer');
  assert.equal(cacheRoot({ platform: 'darwin', env: {}, home: '/Users/a' }), '/Users/a/Library/Caches/text-compositor/viewer');
  assert.equal(cacheRoot({ platform: 'linux', env: {}, home: '/home/a' }), '/home/a/.cache/text-compositor/viewer');
  assert.equal(cacheRoot({ platform: 'linux', env: { XDG_CACHE_HOME: '/x/cache' }, home: '/home/a' }), '/x/cache/text-compositor/viewer');
});

test('the HTML file name follows the document path: same path, same name; different folders, different names', () => {
  assert.equal(htmlFileName('/a/doc.md', 'linux'), htmlFileName('/a/doc.md', 'linux'));
  assert.notEqual(htmlFileName('/a/doc.md', 'linux'), htmlFileName('/b/doc.md', 'linux'));
  assert.match(htmlFileName('/a/doc.md', 'linux'), /^[0-9a-f]{16}\.html$/);
  // Windowsは、大文字・小文字を区別しない。Linuxは、区別する
  assert.equal(htmlFileName('C:\\Docs\\A.md', 'win32'), htmlFileName('c:\\docs\\a.md', 'win32'));
  assert.notEqual(htmlFileName('/a/A.md', 'linux'), htmlFileName('/a/a.md', 'linux'));
});

test("'app' passes an output and a cache folder inside the app folder and never touches the document folder", () => {
  const docs = temporaryDirectory();
  const file = path.join(docs, 'doc.md');
  const root = path.join(temporaryDirectory(), 'viewer');
  const { params, fellBack } = workLocation('app', file, { root });
  assert.equal(fellBack, false);
  assert.equal(params.output, path.join(root, 'html', htmlFileName(file)));
  assert.equal(params.cache_dir, path.join(root, 'cache'));
  assert.deepEqual(fs.readdirSync(docs), []);   // 原稿のフォルダに、何も作らない
});

test("'beside' passes nothing (the worker's default) when the document folder is writable", () => {
  const docs = temporaryDirectory();
  const { params, fellBack } = workLocation('beside', path.join(docs, 'doc.md'), { root: path.join(docs, 'x', 'viewer') });
  assert.deepEqual(params, {});
  assert.equal(fellBack, false);
});

test("'beside' falls back to the app folder when the document folder cannot be written", () => {
  const docs = temporaryDirectory();
  const file = path.join(docs, 'doc.md');
  const root = path.join(temporaryDirectory(), 'viewer');
  const readOnly = { ...fs, mkdirSync: () => { throw Object.assign(new Error('read-only'), { code: 'EROFS' }); } };
  assert.equal(isWritableBeside(file, readOnly), false);
  const { params, fellBack } = workLocation('beside', file, { root, fsApi: readOnly });
  assert.equal(fellBack, true);
  assert.equal(params.output, path.join(root, 'html', htmlFileName(file)));
});

test('an unknown mode is treated as the default (the app folder)', () => {
  const { params } = workLocation('none', '/a/doc.md', { root: '/r/viewer', platform: 'linux' });
  assert.equal(params.output, path.posix.join('/r/viewer', 'html', htmlFileName('/a/doc.md', 'linux')));
});

test('usage counts only html/ and cache/, and clearing removes only those two folders', async () => {
  const root = path.join(temporaryDirectory(), 'viewer');
  fs.mkdirSync(path.join(root, 'html'), { recursive: true });
  fs.mkdirSync(path.join(root, 'cache', 'nested'), { recursive: true });
  fs.writeFileSync(path.join(root, 'html', 'a.html'), 'x'.repeat(100));
  fs.writeFileSync(path.join(root, 'cache', 'svg_1.svg'), 'y'.repeat(50));
  fs.writeFileSync(path.join(root, 'cache', 'nested', 'svg_2.svg'), 'z'.repeat(25));
  fs.writeFileSync(path.join(root, 'keep.txt'), 'not managed');
  assert.deepEqual(await cacheUsage(root), { bytes: 175, files: 3 });

  assert.deepEqual(await clearCache(root), { bytes: 175, files: 3 });
  assert.deepEqual(await cacheUsage(root), { bytes: 0, files: 0 });
  assert.deepEqual(fs.readdirSync(root), ['keep.txt']);
});

test('usage of a folder that does not exist yet is zero, and clearing it does not fail', async () => {
  const root = path.join(temporaryDirectory(), 'viewer');
  assert.deepEqual(await cacheUsage(root), { bytes: 0, files: 0 });
  assert.deepEqual(await clearCache(root), { bytes: 0, files: 0 });
});

test('clearing refuses a folder that is not named viewer (so that a wrong path cannot delete something else)', async () => {
  const other = temporaryDirectory();
  fs.mkdirSync(path.join(other, 'html'));
  fs.writeFileSync(path.join(other, 'html', 'a.html'), 'x');
  await assert.rejects(() => clearCache(other), /Refusing/);
  assert.ok(fs.existsSync(path.join(other, 'html', 'a.html')));
});