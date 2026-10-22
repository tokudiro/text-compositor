'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { MAX_RECENT_FILES, addRecentFile, normalizeRecentFiles, recentLabel, removeRecentFile } = require('../src/recent-files');
const { normalizeSettings } = require('../src/settings');

const abs = (...parts) => path.resolve(path.sep, ...parts);

test('addRecentFile: 新しいファイルは先頭に入り、元の一覧は変わらない', () => {
  const before = [abs('a.md')];
  const after = addRecentFile(before, abs('b.md'));
  assert.deepEqual(after, [abs('b.md'), abs('a.md')]);
  assert.deepEqual(before, [abs('a.md')]);
});

test('addRecentFile: すでにあるファイルは、重複させず、先頭へ移す', () => {
  const after = addRecentFile([abs('a.md'), abs('b.md'), abs('c.md')], abs('c.md'));
  assert.deepEqual(after, [abs('c.md'), abs('a.md'), abs('b.md')]);
});

test('addRecentFile: 上限を超えたら、いちばん古いものから捨てる', () => {
  let list = [];
  for (let i = 0; i < MAX_RECENT_FILES + 3; i += 1) list = addRecentFile(list, abs(`f${i}.md`));
  assert.equal(list.length, MAX_RECENT_FILES);
  assert.equal(list[0], abs(`f${MAX_RECENT_FILES + 2}.md`));
  assert.ok(!list.includes(abs('f0.md')));
});

test('Windowsは大文字と小文字を区別せず、ほかのOSは区別する', () => {
  assert.deepEqual(addRecentFile([abs('Docs', 'A.md')], abs('docs', 'a.md'), 'win32'), [abs('docs', 'a.md')]);
  assert.deepEqual(addRecentFile([abs('docs', 'A.md')], abs('docs', 'a.md'), 'linux'), [abs('docs', 'a.md'), abs('docs', 'A.md')]);
});

test('removeRecentFile: 指定したファイルだけを除く', () => {
  assert.deepEqual(removeRecentFile([abs('a.md'), abs('b.md')], abs('a.md')), [abs('b.md')]);
  assert.deepEqual(removeRecentFile([abs('a.md')], abs('zzz.md')), [abs('a.md')]);
});

test('normalizeRecentFiles: 絶対パスの文字列だけを採り、重複と上限を整える', () => {
  assert.deepEqual(normalizeRecentFiles(undefined), []);
  assert.deepEqual(normalizeRecentFiles('a.md'), []);
  assert.deepEqual(normalizeRecentFiles([abs('a.md'), 'relative.md', 42, null, abs('a.md'), abs('b.md')]), [abs('a.md'), abs('b.md')]);
  const many = Array.from({ length: 30 }, (_, i) => abs(`f${i}.md`));
  assert.equal(normalizeRecentFiles(many).length, MAX_RECENT_FILES);
});

test('設定: recentFilesは、保存された値から整えて読み、既定は空', () => {
  assert.deepEqual(normalizeSettings({}).recentFiles, []);
  assert.deepEqual(normalizeSettings({ recentFiles: [abs('a.md'), 'x']}).recentFiles, [abs('a.md')]);
});

test('recentLabel: ファイル名を先に、場所を後ろに出す', () => {
  assert.equal(recentLabel(abs('docs', 'a.md')), `a.md  (${abs('docs')})`);
});

test('recentLabel: &は、メニューのアクセスキーと読まれないよう、&&にする', () => {
  assert.ok(recentLabel(abs('R&D', 'a&b.md')).includes('a&&b.md'));
  assert.ok(recentLabel(abs('R&D', 'a&b.md')).includes('R&&D'));
});

test('recentLabel: 長い場所は、真ん中を省いて、ファイル名は残す', () => {
  const file = abs(...Array.from({ length: 20 }, (_, i) => `folder${i}`), 'report.md');
  const label = recentLabel(file);
  assert.ok(label.length <= 100, label);
  assert.ok(label.startsWith('report.md  ('));
  assert.ok(label.includes('…'));
});
