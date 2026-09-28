'use strict';
// ナビゲーション履歴の管理（#330）。Electronに依存しない純粋なクラス。

const DEFAULT_MAX_ENTRIES = 50;

class NavigationHistory {
  constructor({ maxEntries = DEFAULT_MAX_ENTRIES } = {}) {
    this.maxEntries = maxEntries;
    this.entries = [];
    this.currentIndex = -1;
  }

  get canGoBack() {
    return this.currentIndex > 0;
  }

  get canGoForward() {
    return this.currentIndex >= 0 && this.currentIndex < this.entries.length - 1;
  }

  get current() {
    return this.entries[this.currentIndex] ?? null;
  }

  /**
   * 現在表示中の文書のスクロール位置を更新する。
   */
  updateCurrentScroll(scrollY) {
    if (this.currentIndex >= 0 && this.entries[this.currentIndex]) {
      this.entries[this.currentIndex].scrollY = scrollY;
    }
  }

  /**
   * 戻り先の項目を確認する（インデックスは動かさない）。
   */
  peekBack() {
    return this.canGoBack ? this.entries[this.currentIndex - 1] : null;
  }

  /**
   * 進み先の項目を確認する（インデックスは動かさない）。
   */
  peekForward() {
    return this.canGoForward ? this.entries[this.currentIndex + 1] : null;
  }

  /**
   * 新しいファイルへ遷移したときに追加する。
   * 同じファイルへの再読み込みの場合は追加しない。
   */
  push(file, { scrollY = 0 } = {}) {
    if (this.currentIndex >= 0) {
      const current = this.entries[this.currentIndex];
      if (current && current.file === file) {
        return false;
      }
      // 現在位置以降の履歴（進む履歴）を切り捨てる
      this.entries = this.entries.slice(0, this.currentIndex + 1);
    }
    this.entries.push({ file, scrollY });
    // 上限を超えたら古いものを捨てる
    if (this.entries.length > this.maxEntries) {
      this.entries.shift();
    }
    this.currentIndex = this.entries.length - 1;
    return true;
  }

  /**
   * 戻る。戻り先の { file, scrollY } を返す。戻れないときは null。
   */
  back() {
    if (!this.canGoBack) return null;
    this.currentIndex--;
    return this.entries[this.currentIndex];
  }

  /**
   * 進む。進み先の { file, scrollY } を返す。進めないときは null。
   */
  forward() {
    if (!this.canGoForward) return null;
    this.currentIndex++;
    return this.entries[this.currentIndex];
  }

  clear() {
    this.entries = [];
    this.currentIndex = -1;
  }
}

module.exports = { NavigationHistory, DEFAULT_MAX_ENTRIES };
