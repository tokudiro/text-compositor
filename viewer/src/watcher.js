'use strict';
// 開いている原稿と、それが参照するファイル（画像など）の変更を検知する（#170）。
//
// ファイルそのものではなく、ファイルのあるディレクトリを監視して、名前で絞る。エディタは、保存のときに、
// 一時ファイルへ書いてから名前を付け替える（原子的な保存）ことがあり、ファイルそのものの監視は、それで
// 外れてしまうため。また、まだ存在しない参照先（あとから作られる画像）も、監視できる。
// 連続した変更（保存が、複数の書き込みに分かれる場合）は、変化が止まるのを待って、1回にまとめる。

const fs = require('node:fs');
const path = require('node:path');

class FileWatcher {
  /**
   * @param {{onChange: (paths: string[]) => void, debounceMs?: number, watch?: typeof fs.watch, platform?: string}} options
   */
  constructor({ onChange, debounceMs = 150, watch = fs.watch, platform = process.platform }) {
    this._onChange = onChange;
    this._debounceMs = debounceMs;
    this._watch = watch;
    this._caseInsensitive = platform === 'win32' || platform === 'darwin';
    /** @type {Map<string, {watcher: fs.FSWatcher|null, names: Map<string, string>}>} ディレクトリ → 監視 */
    this._dirs = new Map();
    this._pending = new Set();
    this._timer = null;
    this._closed = false;
  }

  /** 監視するファイルの一覧（絶対パス）を、置き換える。増えた分を監視し、減った分を止める。 */
  setFiles(files) {
    if (this._closed) return;
    const wanted = new Map();
    for (const file of files) {
      const full = path.resolve(file);
      const dir = path.dirname(full);
      if (!wanted.has(dir)) wanted.set(dir, new Map());
      wanted.get(dir).set(this._key(path.basename(full)), full);
    }

    for (const [dir, entry] of this._dirs) {
      if (!wanted.has(dir)) { entry.watcher?.close(); this._dirs.delete(dir); }
    }
    for (const [dir, names] of wanted) {
      const existing = this._dirs.get(dir);
      if (existing) {
        existing.names = names;
        if (!existing.watcher) existing.watcher = this._open(dir);   // 前回、開けなかった（またはエラーになった）場合の再試行
      } else {
        this._dirs.set(dir, { watcher: this._open(dir), names });
      }
    }
  }

  /** 監視しているファイルの数。 */
  get size() {
    let n = 0;
    for (const { names } of this._dirs.values()) n += names.size;
    return n;
  }

  close() {
    this._closed = true;
    clearTimeout(this._timer);
    this._pending.clear();
    for (const { watcher } of this._dirs.values()) watcher?.close();
    this._dirs.clear();
  }

  // ---------------------------------------------------------------------

  _key(name) {
    return this._caseInsensitive ? name.toLowerCase() : name;
  }

  _open(dir) {
    let watcher;
    try {
      watcher = this._watch(dir, { persistent: false }, (_eventType, filename) => this._handle(dir, filename));
    } catch {
      return null;   // ディレクトリが無い等。次のsetFilesで、再試行する
    }
    watcher.on('error', () => {
      watcher.close();
      const entry = this._dirs.get(dir);
      if (entry && entry.watcher === watcher) entry.watcher = null;
    });
    return watcher;
  }

  _handle(dir, filename) {
    const entry = this._dirs.get(dir);
    if (!entry || this._closed) return;
    if (filename) {
      const full = entry.names.get(this._key(filename.toString()));
      if (full) this._pending.add(full);
    } else {
      // ファイル名が分からない通知は、そのディレクトリの、監視中のファイルすべての変更として扱う
      for (const full of entry.names.values()) this._pending.add(full);
    }
    if (this._pending.size === 0) return;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      const changed = [...this._pending];
      this._pending.clear();
      if (!this._closed) this._onChange(changed);
    }, this._debounceMs);
  }
}

module.exports = { FileWatcher };
