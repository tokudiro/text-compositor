'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { after, before, describe, test } = require('node:test');

const { FileWatcher } = require('../src/watcher');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'viewer-watch-'));
let counter = 0;
const watchers = [];

after(() => { for (const w of watchers) w.close(); fs.rmSync(root, { recursive: true, force: true }); });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 条件が満たされるまで待つ。満たされなければ、falseを返す。 */
async function waitFor(condition, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (condition()) return true;
    await sleep(10);
  }
  return condition();
}

/** 専用のディレクトリと、その中を監視するFileWatcherを作る。 */
function setup(debounceMs = 40) {
  const dir = path.join(root, `case-${++counter}`);
  fs.mkdirSync(dir);
  const calls = [];
  const watcher = new FileWatcher({ debounceMs, onChange: (paths) => calls.push(paths) });
  watchers.push(watcher);
  return { dir, calls, watcher };
}

describe('FileWatcher', () => {
  test('a change to a watched file is reported once, with its path', async () => {
    const { dir, calls, watcher } = setup();
    const file = path.join(dir, 'a.md');
    fs.writeFileSync(file, '1');
    watcher.setFiles([file]);
    await sleep(50);
    fs.writeFileSync(file, '2');
    assert.ok(await waitFor(() => calls.length > 0));
    assert.deepEqual(calls[0], [file]);
    await sleep(150);
    assert.equal(calls.length, 1);
  });

  test('a burst of writes is merged into one report', async () => {
    const { dir, calls, watcher } = setup(120);
    const file = path.join(dir, 'a.md');
    fs.writeFileSync(file, '0');
    watcher.setFiles([file]);
    await sleep(50);
    for (let i = 1; i <= 5; i++) { fs.writeFileSync(file, String(i)); await sleep(15); }
    assert.ok(await waitFor(() => calls.length > 0));
    await sleep(300);
    assert.equal(calls.length, 1);
  });

  test('an atomic save (write a temp file, then rename over) is detected', async () => {
    const { dir, calls, watcher } = setup();
    const file = path.join(dir, 'a.md');
    fs.writeFileSync(file, 'old');
    watcher.setFiles([file]);
    await sleep(50);
    const tmp = path.join(dir, 'a.md.tmp');
    fs.writeFileSync(tmp, 'new');
    fs.renameSync(tmp, file);
    assert.ok(await waitFor(() => calls.length > 0));
    assert.deepEqual(calls[0], [file]);
  });

  test('other files in the same directory are ignored', async () => {
    const { dir, calls, watcher } = setup();
    const file = path.join(dir, 'a.md');
    fs.writeFileSync(file, '1');
    watcher.setFiles([file]);
    await sleep(50);
    fs.writeFileSync(path.join(dir, 'other.md'), 'x');
    await sleep(250);
    assert.equal(calls.length, 0);
  });

  test('a file that does not exist yet is reported when it is created', async () => {
    const { dir, calls, watcher } = setup();
    const image = path.join(dir, 'later.png');
    watcher.setFiles([image]);
    await sleep(50);
    fs.writeFileSync(image, 'png');
    assert.ok(await waitFor(() => calls.length > 0));
    assert.deepEqual(calls[0], [image]);
  });

  test('files in several directories, and replacing the list, work', async () => {
    const { dir, calls, watcher } = setup();
    const sub = path.join(dir, 'img');
    fs.mkdirSync(sub);
    const md = path.join(dir, 'a.md');
    const image = path.join(sub, 'p.png');
    fs.writeFileSync(md, '1');
    fs.writeFileSync(image, '1');
    watcher.setFiles([md, image]);
    assert.equal(watcher.size, 2);
    await sleep(50);
    fs.writeFileSync(image, '2');
    assert.ok(await waitFor(() => calls.length === 1));
    assert.deepEqual(calls[0], [image]);

    watcher.setFiles([md]);   // 画像を、監視から外す
    assert.equal(watcher.size, 1);
    await sleep(50);
    fs.writeFileSync(image, '3');
    await sleep(250);
    assert.equal(calls.length, 1);
  });

  test('close stops reporting', async () => {
    const { dir, calls, watcher } = setup();
    const file = path.join(dir, 'a.md');
    fs.writeFileSync(file, '1');
    watcher.setFiles([file]);
    await sleep(50);
    watcher.close();
    fs.writeFileSync(file, '2');
    await sleep(250);
    assert.equal(calls.length, 0);
  });

  test('a directory that does not exist is retried on the next setFiles', async () => {
    const { dir, calls, watcher } = setup();
    const later = path.join(dir, 'made-later');
    const file = path.join(later, 'a.md');
    watcher.setFiles([file]);       // ディレクトリが無く、開けない
    fs.mkdirSync(later);
    watcher.setFiles([file]);       // 再試行
    await sleep(50);
    fs.writeFileSync(file, '1');
    assert.ok(await waitFor(() => calls.length > 0));
  });
});
