'use strict';
// 改名前の設定の引き継ぎ（#394）。実際の一時フォルダで確かめる。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { describe, test } = require('node:test');

const { migrateLegacySettings } = require('../src/legacy-settings');

function setup() {
  const appData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-legacy-'));
  return { appData, userData: path.join(appData, 'Obunzu Markdown Viewer'), legacy: path.join(appData, 'Obunzu') };
}

describe('migrateLegacySettings', () => {
  test('copies settings.json from the old folder when the new folder has none', () => {
    const { appData, userData, legacy } = setup();
    fs.mkdirSync(legacy);
    fs.writeFileSync(path.join(legacy, 'settings.json'), '{"theme":"dark"}');
    assert.equal(migrateLegacySettings({ userData, appData }), true);
    assert.equal(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8'), '{"theme":"dark"}');
    assert.ok(fs.existsSync(path.join(legacy, 'settings.json')), 'the old file is kept');
  });

  test('never overwrites settings that already exist in the new folder', () => {
    const { appData, userData, legacy } = setup();
    fs.mkdirSync(legacy);
    fs.mkdirSync(userData);
    fs.writeFileSync(path.join(legacy, 'settings.json'), '{"theme":"dark"}');
    fs.writeFileSync(path.join(userData, 'settings.json'), '{"theme":"light"}');
    assert.equal(migrateLegacySettings({ userData, appData }), false);
    assert.equal(fs.readFileSync(path.join(userData, 'settings.json'), 'utf8'), '{"theme":"light"}');
  });

  test('does nothing when there are no old settings, or the folders are the same', () => {
    const { appData, userData, legacy } = setup();
    assert.equal(migrateLegacySettings({ userData, appData }), false);
    assert.equal(fs.existsSync(userData), false);
    fs.mkdirSync(legacy);
    fs.writeFileSync(path.join(legacy, 'settings.json'), '{}');
    assert.equal(migrateLegacySettings({ userData: legacy, appData }), false);
  });

  test('a failure to copy does not throw', () => {
    const { appData, userData, legacy } = setup();
    fs.mkdirSync(legacy);
    fs.writeFileSync(path.join(legacy, 'settings.json'), '{}');
    const fsApi = { ...fs, existsSync: fs.existsSync, mkdirSync: fs.mkdirSync, copyFileSync: () => { throw new Error('disk full'); } };
    assert.equal(migrateLegacySettings({ userData, appData, fsApi }), false);
  });
});
