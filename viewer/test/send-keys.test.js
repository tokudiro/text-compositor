'use strict';
const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { findMenuShortcut, parseKey } = require('../scripts/send-keys');

describe('parseKey (#551)', () => {
  test('a single key has no modifiers', () => {
    assert.deepEqual(parseKey('F5'), { keyCode: 'F5', modifiers: [] });
  });

  test('Esc is spelled out as Escape', () => {
    assert.deepEqual(parseKey('Esc'), { keyCode: 'Escape', modifiers: [] });
  });

  test('modifiers are lower-cased into the names sendInputEvent expects', () => {
    assert.deepEqual(parseKey('Ctrl+,'), { keyCode: ',', modifiers: ['control'] });
    assert.deepEqual(parseKey('Ctrl+Shift+F'), { keyCode: 'F', modifiers: ['control', 'shift'] });
  });

  test('a plus sign can be the key itself', () => {
    assert.deepEqual(parseKey('Ctrl++'), { keyCode: '+', modifiers: ['control'] });
  });

  test('an unknown modifier is an error, not a silently dropped key', () => {
    assert.throws(() => parseKey('Hyper+F'), /Hyper/);
  });
});

describe('parseKey with menu accelerators (#551)', () => {
  test('CommandOrControl is Ctrl on Windows and Linux, Cmd on macOS', () => {
    assert.deepEqual(parseKey('CommandOrControl+,', 'win32'), { keyCode: ',', modifiers: ['control'] });
    assert.deepEqual(parseKey('CmdOrCtrl+,', 'linux'), { keyCode: ',', modifiers: ['control'] });
    assert.deepEqual(parseKey('CommandOrControl+,', 'darwin'), { keyCode: ',', modifiers: ['meta'] });
  });

  test('Plus and Return are spelled as the characters sendInputEvent expects', () => {
    assert.deepEqual(parseKey('CommandOrControl+Plus', 'win32'), { keyCode: '+', modifiers: ['control'] });
    assert.deepEqual(parseKey('Return'), { keyCode: 'Enter', modifiers: [] });
  });
});

describe('findMenuShortcut (#551)', () => {
  const items = [
    { path: [0, 0], accelerator: 'CommandOrControl+O', enabled: true },
    { path: [0, 3], accelerator: 'CommandOrControl+W', enabled: false },
    { path: [0, 5], accelerator: 'F5', enabled: true },
    { path: [0, 6], accelerator: 'CommandOrControl+R', enabled: true },
    { path: [2, 9], accelerator: 'CommandOrControl+,', enabled: true },
    { path: [2, 1], accelerator: 'Ctrl+Shift+Tab', enabled: true },
  ];

  test('Ctrl+, finds CommandOrControl+, whatever the case and spelling', () => {
    assert.deepEqual(findMenuShortcut(items, 'Ctrl+,', 'win32')?.path, [2, 9]);
    assert.deepEqual(findMenuShortcut(items, 'control+,', 'win32')?.path, [2, 9]);
  });

  test('the order of the modifiers does not matter', () => {
    assert.deepEqual(findMenuShortcut(items, 'Shift+Ctrl+Tab', 'win32')?.path, [2, 1]);
  });

  test('a key without a menu item is not found (it is sent as a key instead)', () => {
    assert.equal(findMenuShortcut(items, 'Esc', 'win32'), null);
    assert.equal(findMenuShortcut(items, 'F6', 'win32'), null);
  });

  test('a disabled item is still found, so the caller can leave it alone', () => {
    const hit = findMenuShortcut(items, 'Ctrl+W', 'win32');
    assert.deepEqual([hit.path, hit.enabled], [[0, 3], false]);
  });

  test('an enabled item wins over a disabled one with the same shortcut', () => {
    const both = [{ path: [1], accelerator: 'F5', enabled: false }, { path: [2], accelerator: 'F5', enabled: true }];
    assert.deepEqual(findMenuShortcut(both, 'F5', 'win32')?.path, [2]);
  });

  test('an accelerator it cannot read is skipped, not an error', () => {
    const odd = [{ path: [0], accelerator: 'Hyper+F', enabled: true }, { path: [1], accelerator: 'F5', enabled: true }];
    assert.deepEqual(findMenuShortcut(odd, 'F5', 'win32')?.path, [1]);
  });
});
