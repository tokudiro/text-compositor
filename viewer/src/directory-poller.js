'use strict';
// ファイルツリーの自動更新（#549）のための、フォルダの更新時刻の確認。Electronに依存しない、純粋な部品。
//
// 方式: ツリーで展開中のフォルダ（と、ルート）の更新時刻を、一定の間隔で比べ、変わったフォルダだけを、画面が読み直す。
// `fs.watch`は使わない。理由は、通知が来ない・遅いネットワークドライブがあること、消えたフォルダでエラーになること、
// 監視の数に上限があること。更新時刻の比較なら、どれも起きない（ワーカーの変更検知#284も、更新時刻とサイズの比較）。
//
// 実測（Windows、NTFS）: フォルダの更新時刻は、ファイルの作成・改名・削除・原子的な保存（一時ファイルを作って名前を付け替える）で
// 変わる。ファイルの中身の書き換えと、子フォルダの中の変更では変わらない（子フォルダの中は、その子フォルダが展開中なら、
// 子自身の更新時刻が見る）。100フォルダの確認は、約3ms。

const fsPromises = require('node:fs/promises');

class DirectoryPoller {
  /** @param {{stat?: (path: string) => Promise<{mtimeMs: number, isDirectory: () => boolean}>}} [options] */
  constructor({ stat = fsPromises.stat } = {}) {
    this._stat = stat;
    this._baselines = new Map();   // フォルダ → 画面が最後に読んだ時点の更新時刻
    this._watched = new Set();     // 確認の対象のフォルダ（展開中のフォルダと、ルート）
    this._quiet = new Set();       // 変更を知らせた（または、読めない）フォルダ。画面が読み直す（`record`する）まで、重ねて知らせない
    this._timer = null;
    this._running = false;
  }

  /**
   * フォルダを読む直前に呼ぶ。そのときの更新時刻を、基準にする。
   * 読む「前」に控えるのは、読んでいる間の変更を取りこぼさないため（変更があれば、次の確認で、基準との差になる）。
   * 更新時刻を取れないフォルダ（消えた・権限がない）は、基準を持たず、静かにする（毎回、読み直しにならないように）。
   */
  async record(directory) {
    try {
      const info = await this._stat(directory);
      this._baselines.set(directory, info.mtimeMs);
      this._quiet.delete(directory);
    } catch {
      this._baselines.delete(directory);
      this._quiet.add(directory);
    }
  }

  /** 確認の対象を、渡した一覧に置き換える。対象から外れたフォルダの基準は、捨てる（展開し直せば、読むときに、取り直す）。 */
  setWatched(directories) {
    this._watched = new Set(directories);
    for (const known of [...this._baselines.keys()]) if (!this._watched.has(known)) this._baselines.delete(known);
    for (const known of [...this._quiet]) if (!this._watched.has(known)) this._quiet.delete(known);
  }

  get watched() { return [...this._watched]; }

  /**
   * 対象のフォルダを1回ずつ確かめ、読み直すべきフォルダの一覧を返す。
   * - 更新時刻が、基準と違う → 返す。
   * - 更新時刻を取れない（消えた・読めない） → 返す（画面が読み直し、案内を出すか、親の更新で取り除く）。
   * - 基準がまだ無い（画面が読む前に、対象になった） → 基準を、いまの更新時刻にして、返さない。
   * 返したフォルダは、画面が`record`するまで、重ねて返さない。
   * @returns {Promise<string[]>}
   */
  async poll() {
    const changed = [];
    for (const directory of this._watched) {
      if (this._quiet.has(directory)) continue;
      let info;
      try {
        info = await this._stat(directory);
      } catch {
        info = null;
      }
      if (info === null || !info.isDirectory()) {
        this._quiet.add(directory);
        changed.push(directory);
        continue;
      }
      if (!this._baselines.has(directory)) {
        this._baselines.set(directory, info.mtimeMs);
        continue;
      }
      if (info.mtimeMs !== this._baselines.get(directory)) {
        this._quiet.add(directory);
        changed.push(directory);
      }
    }
    return changed;
  }

  /** 一定の間隔で`poll`し、読み直すフォルダがあれば、`onChange(一覧)`を呼ぶ。重ねて動かさない。 */
  start(intervalMs, onChange) {
    this.stop();
    this._timer = setInterval(async () => {
      if (this._running) return;   // 前回の確認が終わっていない（遅いドライブ）。重ねない
      this._running = true;
      try {
        const changed = await this.poll();
        if (changed.length > 0) onChange(changed);
      } catch {
        // 確認の失敗で、アプリを止めない。次の間隔で、やり直す
      } finally {
        this._running = false;
      }
    }, intervalMs);
    this._timer.unref?.();
  }

  stop() {
    if (this._timer !== null) clearInterval(this._timer);
    this._timer = null;
  }

  get running() { return this._timer !== null; }
}

module.exports = { DirectoryPoller };
