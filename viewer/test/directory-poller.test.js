'use strict';
// ファイルツリーの自動更新（#549）の、更新時刻の確認のテスト。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { describe, test } = require('node:test');

const { DirectoryPoller } = require('../src/directory-poller');

/** フォルダ名 → 更新時刻 の表から、`stat`の代わりを作る。表に無い名前は、「無い」エラー。値がnullなら、フォルダでないもの。 */
function fakeStat(table) {
  return async (directory) => {
    if (!(directory in table)) throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
    const mtimeMs = table[directory];
    return { mtimeMs: mtimeMs ?? 0, isDirectory: () => mtimeMs !== null };
  };
}

describe('DirectoryPoller (fake stat)', () => {
  test('a folder whose modification time did not change is not reported', async () => {
    const table = { '/r': 100 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r');
    poller.setWatched(['/r']);
    assert.deepEqual(await poller.poll(), []);
    assert.deepEqual(await poller.poll(), []);
  });

  test('a changed folder is reported once, until the screen reads it again (record)', async () => {
    const table = { '/r': 100 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r');
    poller.setWatched(['/r']);
    table['/r'] = 200;
    assert.deepEqual(await poller.poll(), ['/r']);
    assert.deepEqual(await poller.poll(), [], 'not reported again before it is re-read');
    await poller.record('/r');           // the screen re-read it
    assert.deepEqual(await poller.poll(), []);
    table['/r'] = 300;                   // a later change is found again
    assert.deepEqual(await poller.poll(), ['/r']);
  });

  test('only the changed folders are reported', async () => {
    const table = { '/r': 1, '/r/a': 2, '/r/b': 3 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    for (const d of Object.keys(table)) await poller.record(d);
    poller.setWatched(Object.keys(table));
    table['/r/b'] = 4;
    assert.deepEqual(await poller.poll(), ['/r/b']);
  });

  test('a change between recording and the first poll is not missed (the baseline is taken before reading)', async () => {
    const table = { '/r': 100 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r');           // just before the screen reads the folder
    table['/r'] = 150;                   // a file is added while it is being read
    poller.setWatched(['/r']);
    assert.deepEqual(await poller.poll(), ['/r']);
  });

  test('a folder that became a watch target without a baseline gets one, and is not reported', async () => {
    const table = { '/r': 100 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    poller.setWatched(['/r']);
    assert.deepEqual(await poller.poll(), []);
    table['/r'] = 101;
    assert.deepEqual(await poller.poll(), ['/r']);
  });

  test('a deleted folder is reported once and then stays quiet (no endless re-reading)', async () => {
    const table = { '/r': 1, '/r/a': 2 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r');
    await poller.record('/r/a');
    poller.setWatched(['/r', '/r/a']);
    delete table['/r/a'];
    assert.deepEqual(await poller.poll(), ['/r/a']);
    assert.deepEqual(await poller.poll(), []);
    await poller.record('/r/a');         // the re-read failed too: still quiet
    assert.deepEqual(await poller.poll(), []);
  });

  test('a folder replaced by a file is reported', async () => {
    const table = { '/r': 1, '/r/a': 2 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r/a');
    poller.setWatched(['/r/a']);
    table['/r/a'] = null;                // now a file
    assert.deepEqual(await poller.poll(), ['/r/a']);
  });

  test('folders removed from the watch list are no longer checked, and their baselines are dropped', async () => {
    const table = { '/r': 1, '/r/a': 2 };
    const poller = new DirectoryPoller({ stat: fakeStat(table) });
    await poller.record('/r');
    await poller.record('/r/a');
    poller.setWatched(['/r', '/r/a']);
    poller.setWatched(['/r']);           // /r/a was collapsed
    table['/r/a'] = 99;
    assert.deepEqual(await poller.poll(), []);
    assert.deepEqual(poller.watched, ['/r']);
    poller.setWatched(['/r', '/r/a']);   // expanded again, but the screen has not read it yet: no baseline, no report
    assert.deepEqual(await poller.poll(), []);
  });

  test('an unreadable folder at record time is quiet instead of being re-read every time', async () => {
    const poller = new DirectoryPoller({ stat: fakeStat({}) });
    await poller.record('/gone');
    poller.setWatched(['/gone']);
    assert.deepEqual(await poller.poll(), []);
  });
});

describe('DirectoryPoller (real folders)', () => {
  function makeRoot() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-poller-'));
  }
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  test('adding, renaming and deleting files, and creating a subfolder, are all found', async () => {
    const root = makeRoot();
    try {
      const poller = new DirectoryPoller();
      await poller.record(root);
      poller.setWatched([root]);
      assert.deepEqual(await poller.poll(), []);
      for (const change of [
        () => fs.writeFileSync(path.join(root, 'a.md'), 'x'),
        () => fs.renameSync(path.join(root, 'a.md'), path.join(root, 'b.md')),
        () => fs.mkdirSync(path.join(root, 'sub')),
        () => fs.unlinkSync(path.join(root, 'b.md')),
        () => { fs.writeFileSync(path.join(root, 'd.tmp'), '1'); fs.renameSync(path.join(root, 'd.tmp'), path.join(root, 'd.md')); },
      ]) {
        await wait(40);                  // the timestamp resolution of the file system
        change();
        assert.deepEqual(await poller.poll(), [root]);
        await poller.record(root);
      }
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  test('rewriting a file does not report the folder, but a change inside an expanded subfolder reports that subfolder', async () => {
    const root = makeRoot();
    try {
      fs.mkdirSync(path.join(root, 'sub'));
      fs.writeFileSync(path.join(root, 'a.md'), 'x');
      const poller = new DirectoryPoller();
      await poller.record(root);
      await poller.record(path.join(root, 'sub'));
      poller.setWatched([root, path.join(root, 'sub')]);
      await wait(40);
      fs.writeFileSync(path.join(root, 'a.md'), 'yy');   // content only
      assert.deepEqual(await poller.poll(), []);
      await wait(40);
      fs.writeFileSync(path.join(root, 'sub', 'c.md'), 'x');
      assert.deepEqual(await poller.poll(), [path.join(root, 'sub')]);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  test('deleting an expanded folder is found', async () => {
    const root = makeRoot();
    try {
      const sub = path.join(root, 'sub');
      fs.mkdirSync(sub);
      const poller = new DirectoryPoller();
      await poller.record(root);
      await poller.record(sub);
      poller.setWatched([root, sub]);
      await wait(40);
      fs.rmSync(sub, { recursive: true });
      assert.deepEqual((await poller.poll()).sort(), [root, sub].sort());
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  test('start() calls back with the changed folders, and stop() ends it', async () => {
    const root = makeRoot();
    try {
      const poller = new DirectoryPoller();
      await poller.record(root);
      poller.setWatched([root]);
      const seen = [];
      poller.start(20, (changed) => seen.push(changed));
      assert.equal(poller.running, true);
      await wait(60);
      fs.writeFileSync(path.join(root, 'a.md'), 'x');
      await wait(150);
      assert.deepEqual(seen, [[root]], 'reported exactly once');
      poller.stop();
      assert.equal(poller.running, false);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});
