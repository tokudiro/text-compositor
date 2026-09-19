'use strict';
// アイコン（#193）の成果物が、そろっていて、形式が正しいこと。書き出し（npm run build-icons）を忘れた変更を、検出する。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const assets = path.join(__dirname, '..', 'assets');
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

test('the source SVG exists', () => {
  const svg = fs.readFileSync(path.join(assets, 'icon.svg'), 'utf8');
  assert.match(svg, /<svg[^>]*viewBox="0 0 128 128"/);
});

test('icon.ico contains PNG images of every required size', () => {
  const ico = fs.readFileSync(path.join(assets, 'icon.ico'));
  assert.equal(ico.readUInt16LE(0), 0);   // 予約
  assert.equal(ico.readUInt16LE(2), 1);   // 種類: アイコン
  const count = ico.readUInt16LE(4);
  const sizes = [];
  for (let i = 0; i < count; i += 1) {
    const at = 6 + i * 16;
    sizes.push(ico.readUInt8(at) || 256);   // 0は256を表す
    const length = ico.readUInt32LE(at + 8);
    const offset = ico.readUInt32LE(at + 12);
    assert.ok(offset + length <= ico.length, 'the image stays inside the file');
    assert.ok(ico.subarray(offset, offset + 8).equals(PNG_SIGNATURE), 'each image is a PNG');
  }
  assert.deepEqual(sizes, [16, 24, 32, 48, 64, 128, 256]);
});

test('icon.png is a 256 px PNG', () => {
  const png = fs.readFileSync(path.join(assets, 'icon.png'));
  assert.ok(png.subarray(0, 8).equals(PNG_SIGNATURE));
  assert.equal(png.readUInt32BE(16), 256);   // IHDRの幅
  assert.equal(png.readUInt32BE(20), 256);   // IHDRの高さ
});
