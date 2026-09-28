'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { NavigationHistory, DEFAULT_MAX_ENTRIES } = require('../src/history');

test('NavigationHistory: 初期状態は空で、戻る・進むナビゲーションは無効', () => {
  const history = new NavigationHistory();
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.equal(history.current, null);
  assert.equal(history.peekBack(), null);
  assert.equal(history.peekForward(), null);
  assert.equal(history.back(), null);
  assert.equal(history.forward(), null);
});

test('NavigationHistory: 最初のファイルを追加したときは、まだ戻る先はない', () => {
  const history = new NavigationHistory();
  assert.equal(history.push('doc-a.md'), true);
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.deepEqual(history.current, { file: 'doc-a.md', scrollY: 0 });
});

test('NavigationHistory: 同じファイルの再読み込みでは重複して履歴に積まない', () => {
  // 手動再読み込み（F5）や原稿保存による自動更新で履歴が重複すると、
  // 「戻る」を押しても同じファイルにとどまってしまうため、同一ファイルの連続pushは弾く。
  const history = new NavigationHistory();
  assert.equal(history.push('doc-a.md'), true);
  assert.equal(history.push('doc-a.md'), false);
  assert.equal(history.entries.length, 1);
  assert.equal(history.canGoBack, false);
});

test('NavigationHistory: 表示中の文書のスクロール位置を更新できる', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.updateCurrentScroll(250);
  assert.deepEqual(history.current, { file: 'doc-a.md', scrollY: 250 });
});

test('NavigationHistory: 複数ファイルを移動した後、戻る・進むで元の文書とスクロール位置が復元される', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.updateCurrentScroll(120);

  history.push('doc-b.md');
  history.updateCurrentScroll(340);

  history.push('doc-c.md');

  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
  assert.deepEqual(history.current, { file: 'doc-c.md', scrollY: 0 });

  // peekBackは、インデックスを進めずに戻り先を確認できること（到達可能性チェック用）
  assert.deepEqual(history.peekBack(), { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.current.file, 'doc-c.md');

  // doc-bへ戻る
  const back1 = history.back();
  assert.deepEqual(back1, { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, true);
  assert.deepEqual(history.peekForward(), { file: 'doc-c.md', scrollY: 0 });

  // doc-aへ戻る
  const back2 = history.back();
  assert.deepEqual(back2, { file: 'doc-a.md', scrollY: 120 });
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, true);

  // doc-bへ進む
  const fwd1 = history.forward();
  assert.deepEqual(fwd1, { file: 'doc-b.md', scrollY: 340 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, true);

  // doc-cへ進む
  const fwd2 = history.forward();
  assert.deepEqual(fwd2, { file: 'doc-c.md', scrollY: 0 });
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: 戻った後に別文書を開くと、進む履歴が切り捨てられて新しい分岐になる', () => {
  // ブラウザの履歴仕様に合わせ、途中の履歴から別文書へ進んだ場合は、
  // それより未来にあった進むスタックを破棄して新たな分岐として積む。
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');
  history.push('doc-c.md');

  history.back(); // doc-bに戻る
  assert.equal(history.canGoForward, true);

  history.push('doc-d.md');
  assert.equal(history.canGoForward, false);
  assert.equal(history.canGoBack, true);
  assert.deepEqual(history.entries.map((e) => e.file), ['doc-a.md', 'doc-b.md', 'doc-d.md']);
  assert.equal(history.current.file, 'doc-d.md');
});

test('NavigationHistory: 履歴保持の上限を超えたら古い履歴から破棄される', () => {
  // セッション内の閲覧が長期に及んでもメモリ使用量が肥大化しないよう、上限を超えたら先頭から切り詰める。
  const history = new NavigationHistory({ maxEntries: 3 });
  history.push('1.md');
  history.push('2.md');
  history.push('3.md');
  assert.equal(history.entries.length, 3);
  assert.deepEqual(history.entries.map((e) => e.file), ['1.md', '2.md', '3.md']);

  history.push('4.md');
  assert.equal(history.entries.length, 3);
  assert.deepEqual(history.entries.map((e) => e.file), ['2.md', '3.md', '4.md']);
  assert.equal(history.current.file, '4.md');
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: 戻った先でスクロールした位置も個別に記憶される', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');
  history.back(); // doc-aに戻る
  history.updateCurrentScroll(500); // doc-aでスクロール
  assert.equal(history.current.scrollY, 500);

  history.forward(); // doc-bへ進む
  history.updateCurrentScroll(300); // doc-bでスクロール
  assert.equal(history.current.scrollY, 300);

  history.back(); // 再度doc-aに戻る
  assert.equal(history.current.scrollY, 500);
});

test('NavigationHistory: 意図した位置に戻る・進むインデックス操作ができる', () => {
  const history = new NavigationHistory();
  history.push('doc-a.md');
  history.push('doc-b.md');

  const target = history.back();
  assert.equal(target.file, 'doc-a.md');
  assert.equal(history.current.file, 'doc-a.md');

  // 逆方向へ進めば直前の位置に戻る
  history.forward();
  assert.equal(history.current.file, 'doc-b.md');
  assert.equal(history.canGoBack, true);
  assert.equal(history.canGoForward, false);
});

test('NavigationHistory: clearで履歴がすべてリセットされる', () => {
  const history = new NavigationHistory();
  history.push('a.md');
  history.push('b.md');
  history.clear();
  assert.equal(history.canGoBack, false);
  assert.equal(history.canGoForward, false);
  assert.equal(history.current, null);
  assert.equal(history.entries.length, 0);
});
