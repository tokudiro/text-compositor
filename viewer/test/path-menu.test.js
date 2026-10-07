'use strict';
// 右クリックのメニューの、ファイル・フォルダ・タブの項目（#428）。Electronなしで、項目の出し分けと、呼び出しを確認する。

const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const path = require('node:path');

const { buildPathContextMenuTemplate, buildTabContextMenuTemplate, isSidebarPath } = require('../src/path-menu');
const { isInsideDirectory } = require('../src/directory-list');

const labels = (template) => template.map((item) => item.label);

describe('buildPathContextMenuTemplate', () => {
  test('a file has Copy path, Reveal and, with tabs on, Open in new tab, in that order', () => {
    assert.deepEqual(labels(buildPathContextMenuTemplate({ filePath: '/a/b.md' })), ['パスをコピー', 'エクスプローラーで表示']);
    assert.deepEqual(labels(buildPathContextMenuTemplate({ filePath: '/a/b.md', canOpenInNewTab: true })),
      ['パスをコピー', 'エクスプローラーで表示', '新しいタブで開く']);
  });

  test('a folder has no Open in new tab, even with tabs on', () => {
    assert.deepEqual(labels(buildPathContextMenuTemplate({ filePath: '/a', isDirectory: true, canOpenInNewTab: true })),
      ['パスをコピー', 'エクスプローラーで表示']);
  });

  test('an item without a path (a heading of the chapter list) gets no menu', () => {
    for (const filePath of [undefined, null, '']) assert.deepEqual(buildPathContextMenuTemplate({ filePath }), []);
  });

  test('the items call the handlers with the path (and whether it is a folder)', () => {
    const calls = [];
    const file = buildPathContextMenuTemplate({
      filePath: '/a/b.md', canOpenInNewTab: true,
      onCopy: (p) => calls.push(['copy', p]), onReveal: (p, d) => calls.push(['reveal', p, d]), onOpenInNewTab: (p) => calls.push(['tab', p]),
    });
    for (const item of file) item.click();
    const folder = buildPathContextMenuTemplate({ filePath: '/a', isDirectory: true, onReveal: (p, d) => calls.push(['reveal', p, d]) });
    folder[1].click();
    assert.deepEqual(calls, [['copy', '/a/b.md'], ['reveal', '/a/b.md', false], ['tab', '/a/b.md'], ['reveal', '/a', true]]);
  });

  test('clicking without handlers does not throw', () => {
    for (const item of buildPathContextMenuTemplate({ filePath: '/a/b.md', canOpenInNewTab: true })) item.click();
  });
});

describe('buildTabContextMenuTemplate', () => {
  test('a tab with a file: Close, Close others, a separator, Copy path, Reveal', () => {
    const template = buildTabContextMenuTemplate({ file: '/a/b.md', tabCount: 3 });
    assert.deepEqual(labels(template), ['閉じる', '他のタブを閉じる', undefined, 'パスをコピー', 'エクスプローラーで表示']);
    assert.equal(template[2].type, 'separator');
  });

  test('Close others is disabled when there is no other tab', () => {
    assert.equal(buildTabContextMenuTemplate({ file: '/a/b.md', tabCount: 1 })[1].enabled, false);
    assert.equal(buildTabContextMenuTemplate({ file: '/a/b.md', tabCount: 2 })[1].enabled, true);
  });

  test('a tab without a file has only the close items', () => {
    assert.deepEqual(labels(buildTabContextMenuTemplate({ file: null, tabCount: 2 })), ['閉じる', '他のタブを閉じる']);
  });

  test('the items call the handlers', () => {
    const calls = [];
    const template = buildTabContextMenuTemplate({
      file: '/a/b.md', tabCount: 2, onClose: () => calls.push('close'), onCloseOthers: () => calls.push('others'),
      onCopy: (p) => calls.push(['copy', p]), onReveal: (p, d) => calls.push(['reveal', p, d]),
    });
    for (const item of template.filter((i) => i.click)) item.click();
    assert.deepEqual(calls, ['close', 'others', ['copy', '/a/b.md'], ['reveal', '/a/b.md', false]]);
  });
});

describe('isSidebarPath', () => {
  const root = path.resolve('notes');
  const inside = path.join(root, 'sub', 'a.md');
  const check = (overrides) => isSidebarPath({
    filePath: inside, type: 'file', showFileTree: true, tree: { kind: 'folder', root }, projectFiles: null,
    isAbsolute: path.isAbsolute, isInside: isInsideDirectory, ...overrides,
  });

  test('accepts a file or a folder inside the opened folder', () => {
    assert.equal(check({}), true);
    assert.equal(check({ filePath: path.join(root, 'sub'), type: 'directory' }), true);
  });

  test('rejects a path outside the root, a relative path, an unknown type and a non-string', () => {
    assert.equal(check({ filePath: path.resolve('other', 'a.md') }), false);
    assert.equal(check({ filePath: path.join(root, '..', 'secret.md') }), false);
    assert.equal(check({ filePath: 'a.md' }), false);
    assert.equal(check({ type: 'link' }), false);
    for (const filePath of [undefined, null, 5, {}]) assert.equal(check({ filePath }), false);
  });

  test('rejects everything when the sidebar is off or no folder is open', () => {
    assert.equal(check({ showFileTree: false }), false);
    assert.equal(check({ tree: { kind: null, root: null } }), false);
  });

  test('in the chapter list, only files on the list are accepted; the heading folders are not', () => {
    const tree = { kind: 'project', root: path.resolve('c.yaml') };
    const projectFiles = new Set([inside]);
    assert.equal(check({ tree, projectFiles }), true);
    assert.equal(check({ tree, projectFiles, filePath: path.resolve('x.md') }), false);
    assert.equal(check({ tree, projectFiles, filePath: 'section-key', type: 'directory' }), false);
    assert.equal(check({ tree, projectFiles, type: 'directory' }), false);
    assert.equal(check({ tree, projectFiles: null }), false);
  });
});
