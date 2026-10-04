'use strict';
// 1つの文書（タブ）が持つ状態（#332）。
//
// 文書ごとに変わるものだけを、ここに集める。設定・キャッシュ・ズーム・設定画面の開閉・ウィンドウなど、
// アプリ全体（またはウィンドウ全体）で1つのものは、main.jsの`state`に残す。
// ワーカー・描画用の非表示ウィンドウは、全タブで共有する（#332の決定。ワーカーが変換を1件ずつ処理するため、描画依頼も同時には来ない）。

const { summarize } = require('./diagnostics');
const { NavigationHistory } = require('./history');

class DocumentTab {
  constructor(id = 1) {
    this.id = id;                // タブを区別する番号（ウィンドウ本体のタブ列が、操作の対象を伝えるのに使う）
    this.file = null;           // 開いている（または、開こうとしている）ファイル
    this.line = null;            // マウスを乗せた、ブロックの、原稿での行（ツールバーに出す。#328）。乗せていない間も、最後の行を保つ。表示し直すと、消す
    this.busy = false;
    this.status = '';
    this.hasDocument = false;    // 内容を表示しているか
    this.diagnostics = summarize([]);
    // 文書内検索（#325）。ハイライトそのものは、内容のビューのプリロードが持つ（DOMを持っているのは、そちら）。
    // ここは、検索欄の入力と、その結果（件数・現在位置・正規表現エラー）だけを覚える。
    this.search = { open: false, query: '', regex: false, caseSensitive: false, count: 0, current: 0, error: null };
    this.history = new NavigationHistory();   // 戻る・進む（#330）
    this.contentView = null;     // 内容のビュー（WebContentsView）
    this.shown = null;           // 表示中の文書 {md, html, deps}
    this.inFlight = false;       // 変換中か
    this.queued = null;          // 変換中に来た、次の依頼（最後の1件だけを残す）
    this.idleWaiters = [];       // 変換が終わるのを待つ処理（キャッシュの削除）
    this.closed = false;         // 閉じたタブか（変換の途中で閉じられたとき、結果を捨てる）
  }

  /** 開いているのが、.csvか（ツールバーの、見出し行の切り替えを出す。#220）。 */
  get isCsv() {
    return /\.csv$/i.test(this.file ?? '');
  }

  get canGoBack() {
    return this.history.canGoBack;
  }

  get canGoForward() {
    return this.history.canGoForward;
  }

  /** 変換が終わるまで待つ（変換中に、変換の材料を消さないため）。 */
  whenIdle() {
    return this.inFlight ? new Promise((resolve) => this.idleWaiters.push(resolve)) : Promise.resolve();
  }

  /** 変換が終わったことを、待っている処理へ知らせる。 */
  releaseIdleWaiters() {
    for (const resolve of this.idleWaiters.splice(0)) resolve();
  }

  /** 監視するファイル: 表示中の原稿と、その参照ファイル。変換に失敗しても、原稿は監視し続ける（直して保存したときに、自動で更新できるように）。 */
  get watchedFiles() {
    if (!this.file) return [];
    return [this.file, ...(this.shown && this.shown.md === this.file ? this.shown.deps : [])];
  }

  /** タブ列に出す名前。文書があればファイル名、無ければ「新しいタブ」。 */
  get title() {
    if (!this.file) return '新しいタブ';
    const name = this.file.split(/[\\/]/).pop();
    return name || this.file;
  }

  /** タブ列へ送る、このタブの要約（`active`は、呼び出し側が付ける）。 */
  summary() {
    return { id: this.id, title: this.title, file: this.file, busy: this.busy, hasError: this.diagnostics.hasError };
  }

  /** ウィンドウ本体（chrome/）へ送る、文書ごとの状態。アプリ全体の状態と合わせて、1つの`state`として送る。 */
  snapshot() {
    return {
      file: this.file,
      line: this.line,
      busy: this.busy,
      status: this.status,
      hasDocument: this.hasDocument,
      isCsv: this.isCsv,
      diagnostics: this.diagnostics,
      canGoBack: this.canGoBack,
      canGoForward: this.canGoForward,
      search: this.search,
    };
  }
}

/** 保存されたファイル（`paths`）を、監視している（原稿または参照ファイルとして持っている）タブだけを、返す。 */
function tabsAffectedBy(tabs, paths) {
  return tabs.filter((tab) => tab.watchedFiles.some((watched) => paths.includes(watched)));
}

module.exports = { DocumentTab, tabsAffectedBy };
