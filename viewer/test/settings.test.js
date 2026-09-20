'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { DEFAULTS, EDITABLE, loadSettings, normalizeSettings, normalizeWindow, saveSettings } = require('../src/settings');

function temporaryFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-settings-'));
  return { dir, file: path.join(dir, 'settings.json') };
}

test('a missing file gives the defaults', () => {
  const { dir, file } = temporaryFile();
  assert.deepEqual(loadSettings(file), DEFAULTS);
  fs.rmSync(dir, { recursive: true });
});

test('a broken file gives the defaults and does not throw', () => {
  const { dir, file } = temporaryFile();
  for (const text of ['{ not json', '', '[]', 'null', '"text"', '42']) {
    fs.writeFileSync(file, text);
    assert.deepEqual(loadSettings(file), DEFAULTS, `input: ${JSON.stringify(text)}`);
  }
  fs.rmSync(dir, { recursive: true });
});

test('only the unexpected values fall back; valid ones are kept', () => {
  assert.deepEqual(
    normalizeSettings({ toolbarPosition: 'bottom', theme: 'purple', autoReload: 'yes', unknown: 1 }),
    { toolbarPosition: 'bottom', theme: 'system', autoReload: true, csvHeader: true, window: null, openDirectoryMode: 'last', fixedDirectory: null, lastDirectory: null },
  );
  assert.deepEqual(
    normalizeSettings({ toolbarPosition: 'left', theme: 'dark', autoReload: false }),
    { toolbarPosition: 'top', theme: 'dark', autoReload: false, csvHeader: true, window: null, openDirectoryMode: 'last', fixedDirectory: null, lastDirectory: null },
  );
});

test('saved settings are read back, and no temporary file is left', () => {
  const { dir, file } = temporaryFile();
  const settings = { toolbarPosition: 'bottom', theme: 'dark', autoReload: false, csvHeader: false, window: { width: 900, height: 700, maximized: false, x: 10, y: 20 }, openDirectoryMode: 'fixed', fixedDirectory: path.resolve(path.sep, 'notes'), lastDirectory: path.resolve(path.sep, 'docs') };
  assert.equal(saveSettings(file, settings), true);
  assert.deepEqual(loadSettings(file), settings);
  assert.deepEqual(fs.readdirSync(dir), ['settings.json']);
  fs.rmSync(dir, { recursive: true });
});

test('saving creates the folder, and a failure is reported without throwing', () => {
  const { dir } = temporaryFile();
  const nested = path.join(dir, 'a', 'b', 'settings.json');
  assert.equal(saveSettings(nested, DEFAULTS), true);
  // 親がファイルのとき（書けない場所）
  const blocker = path.join(dir, 'blocker');
  fs.writeFileSync(blocker, 'x');
  assert.equal(saveSettings(path.join(blocker, 'settings.json'), DEFAULTS), false);
  fs.rmSync(dir, { recursive: true });
});

test('a saved window state is kept, with the position only when both x and y are valid', () => {
  assert.deepEqual(normalizeWindow({ x: 100, y: -20, width: 1000.4, height: 800, maximized: true }),
    { width: 1000, height: 800, maximized: true, x: 100, y: -20 });
  assert.deepEqual(normalizeWindow({ x: 100, width: 900, height: 700 }), { width: 900, height: 700, maximized: false });
  assert.deepEqual(normalizeWindow({ x: 'a', y: 5, width: 900, height: 700, maximized: 'yes' }),
    { width: 900, height: 700, maximized: false });
});

test('an unusable window size drops the whole window state (the default size is used)', () => {
  for (const value of [null, 3, 'x', [], {}, { width: 10, height: 700 }, { width: 900, height: 10 },
    { width: 'wide', height: 700 }, { width: 99999, height: 700 }, { width: NaN, height: 700 }]) {
    assert.equal(normalizeWindow(value), null, JSON.stringify(value));
  }
});
test('csvHeader is a boolean setting that defaults to true and is kept when valid (#220)', () => {
  assert.equal(normalizeSettings({}).csvHeader, true);
  assert.equal(normalizeSettings({ csvHeader: false }).csvHeader, false);
  for (const bad of ['false', 0, null, undefined, [false]]) assert.equal(normalizeSettings({ csvHeader: bad }).csvHeader, true, String(bad));
});
test('openDirectoryMode is one of os, last and fixed, and defaults to last (#226)', () => {
  assert.equal(normalizeSettings({}).openDirectoryMode, 'last');
  for (const mode of ['os', 'last', 'fixed']) assert.equal(normalizeSettings({ openDirectoryMode: mode }).openDirectoryMode, mode);
  for (const bad of ['', 'Last', 'documents', 1, null, ['os']]) assert.equal(normalizeSettings({ openDirectoryMode: bad }).openDirectoryMode, 'last', JSON.stringify(bad));
});

test('fixedDirectory is an absolute path or null; anything else is dropped', () => {
  const absolute = path.resolve(path.sep, 'docs', 'notes');
  assert.equal(normalizeSettings({}).fixedDirectory, null);
  assert.equal(normalizeSettings({ fixedDirectory: absolute }).fixedDirectory, absolute);
  for (const bad of ['', 'relative/dir', 42, null, [absolute], {}]) assert.equal(normalizeSettings({ fixedDirectory: bad }).fixedDirectory, null, JSON.stringify(bad));
});

test('the start folder mode can be changed from the settings screen, but the folders cannot (#226)', () => {
  assert.ok(EDITABLE.includes('openDirectoryMode'));
  assert.ok(!EDITABLE.includes('fixedDirectory') && !EDITABLE.includes('lastDirectory'));
});

test('lastDirectory is an absolute path or null; anything else is dropped', () => {
  const absolute = path.resolve(path.sep, 'docs', 'notes');
  assert.equal(normalizeSettings({}).lastDirectory, null);
  assert.equal(normalizeSettings({ lastDirectory: absolute }).lastDirectory, absolute);
  for (const bad of ['', 'relative/dir', 42, null, [absolute], {}]) assert.equal(normalizeSettings({ lastDirectory: bad }).lastDirectory, null, JSON.stringify(bad));
});
