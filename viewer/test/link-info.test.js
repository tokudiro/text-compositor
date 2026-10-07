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
  test('offers open and copy, then Reveal for a relative file; copy puts the shown address on the clipboard', () => {
    const copied = [];
    const opened = [];
    const [open, copy, ...rest] = buildLinkContextMenuTemplate({
      href: 'other.md#x', markdownFile: md, onCopy: (t) => copied.push(t), onOpen: (h) => opened.push(h),
    });
    assert.deepEqual(rest.map((item) => item.label), ['エクスプローラーで表示']);
    assert.equal(open.label, 'リンクを開く');
    assert.equal(copy.label, 'リンクのアドレスをコピー');
    open.click();
    copy.click();
    assert.deepEqual(opened, ['other.md#x']);
    assert.deepEqual(copied, [`${path.resolve('docs', 'other.md')}#x`]);
  });

  test('Open in new tab appears only with tabs on and an openable document; Reveal goes with a relative file (#428)', () => {
    const labels = (options) => buildLinkContextMenuTemplate({ markdownFile: md, ...options }).map((item) => item.label);
    assert.deepEqual(labels({ href: 'other.md' }), ['リンクを開く', 'リンクのアドレスをコピー', 'エクスプローラーで表示']);
    assert.deepEqual(labels({ href: 'other.md', canOpenInNewTab: true }),
      ['リンクを開く', 'リンクのアドレスをコピー', '新しいタブで開く', 'エクスプローラーで表示']);
    // 開けない種類（画像・zipなど）には、「新しいタブで開く」を出さない。場所の表示は、出す
    assert.deepEqual(labels({ href: 'a.zip', canOpenInNewTab: true }), ['リンクを開く', 'リンクのアドレスをコピー', 'エクスプローラーで表示']);
  });

  test('external links and in-page anchors get neither Open in new tab nor Reveal (#428)', () => {
    for (const href of ['https://example.com/', 'mailto:a@example.com', '#section']) {
      const labels = buildLinkContextMenuTemplate({ href, markdownFile: md, canOpenInNewTab: true }).map((item) => item.label);
      assert.deepEqual(labels, ['リンクを開く', 'リンクのアドレスをコピー'], href);
    }
  });

  test('the new items pass the resolved file path to the handlers', () => {
    const calls = [];
    const items = buildLinkContextMenuTemplate({
      href: 'other.md#x', markdownFile: md, canOpenInNewTab: true,
      onOpenInNewTab: (file) => calls.push(['tab', file]), onReveal: (file, isDirectory) => calls.push(['reveal', file, isDirectory]),
    });
    for (const item of items.slice(2)) item.click();
    const file = path.resolve('docs', 'other.md');
    assert.deepEqual(calls, [['tab', file], ['reveal', file, false]]);
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

describe('headingLinkRef', () => {
  test('is the file name (without the folder) and the heading id', () => {
    const { headingLinkRef } = require('../src/link-info');
    assert.equal(headingLinkRef(path.resolve('docs', 'note.md'), '見出し'), 'note.md#見出し');
    assert.equal(headingLinkRef('check.md', 'a-1'), 'check.md#a-1');
  });

  test('is null when there is no id or no file', () => {
    const { headingLinkRef } = require('../src/link-info');
    assert.equal(headingLinkRef('check.md', ''), null);
    assert.equal(headingLinkRef('check.md', undefined), null);
    assert.equal(headingLinkRef(null, 'a'), null);
  });
});
