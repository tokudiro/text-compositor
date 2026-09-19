'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { DEFAULTS, loadSettings, normalizeSettings, saveSettings } = require('../src/settings');

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
    { toolbarPosition: 'bottom', theme: 'system', autoReload: true },
  );
  assert.deepEqual(
    normalizeSettings({ toolbarPosition: 'left', theme: 'dark', autoReload: false }),
    { toolbarPosition: 'top', theme: 'dark', autoReload: false },
  );
});

test('saved settings are read back, and no temporary file is left', () => {
  const { dir, file } = temporaryFile();
  const settings = { toolbarPosition: 'bottom', theme: 'dark', autoReload: false };
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
