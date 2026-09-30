'use strict';
// リンク先の表示（#362）。ホバーの文字列と、右クリックのメニューの項目を、Electronなしで確認する。

const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const { buildLinkContextMenuTemplate, describeLink, linkAtPointScript } = require('../src/link-info');

const md = path.resolve('docs', 'a.md');

describe('describeLink', () => {
  test('a relative link is shown as a place under the manuscript folder, with the anchor', () => {
    assert.equal(describeLink('other.md', md), path.resolve('docs', 'other.md'));
    assert.equal(describeLink('other.md#x', md), `${path.resolve('docs', 'other.md')}#x`);
    assert.equal(describeLink('other.md#%E8%A6%8B', md), `${path.resolve('docs', 'other.md')}#見`);
  });

  test('an anchor and a link with a scheme are shown as written', () => {
    for (const href of ['#sec', 'https://example.com/a?b=1', 'mailto:a@b.c']) assert.equal(describeLink(href, md), href);
  });

  test('nothing is shown for an empty href, or a relative link without a manuscript', () => {
    assert.equal(describeLink('', md), null);
    assert.equal(describeLink(null, md), null);
    assert.equal(describeLink('other.md', null), null);
    assert.equal(describeLink('#sec', null), '#sec');
  });
});

describe('buildLinkContextMenuTemplate', () => {
  test('offers open and copy; copy puts the shown address on the clipboard', () => {
    const copied = [];
    const opened = [];
    const [open, copy, ...rest] = buildLinkContextMenuTemplate({
      href: 'other.md#x', markdownFile: md, onCopy: (t) => copied.push(t), onOpen: (h) => opened.push(h),
    });
    assert.equal(rest.length, 0);
    assert.equal(open.label, 'リンクを開く');
    assert.equal(copy.label, 'リンクのアドレスをコピー');
    open.click();
    copy.click();
    assert.deepEqual(opened, ['other.md#x']);
    assert.deepEqual(copied, [`${path.resolve('docs', 'other.md')}#x`]);
  });

  test('has no items when there is nothing to show', () => {
    assert.deepEqual(buildLinkContextMenuTemplate({ href: '', markdownFile: md }), []);
  });
});

describe('linkAtPointScript', () => {
  test('divides the position by the zoom factor and reads the href attribute', () => {
    assert.match(linkAtPointScript(300, 150, 1.5), /elementFromPoint\(200, 100\)/);
    assert.match(linkAtPointScript(30, 40), /closest\('a\[href\]'\)/);
    assert.match(linkAtPointScript(30, 40), /getAttribute\('href'\)/);
  });

  test('is null for a non-numeric position, so nothing is injected into the page', () => {
    assert.equal(linkAtPointScript('1); alert(1', 5), 'null');
    assert.equal(linkAtPointScript(undefined, undefined), 'null');
  });
});
