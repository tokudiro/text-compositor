'use strict';
// 内容のビュー（生成したHTMLを表示する）の、ドラッグ＆ドロップの受け口と、文書内検索（#325）、スクロール位置の通知（#330）。
// ドロップされたファイルのパスを、メインプロセスへ渡すだけで、文書には何も公開しない。
// 何もしないと、ファイルへ、ページが遷移してしまい、（JavaScriptを無効にしているため）ドロップを受け取れない。
//
// 検索のハイライトは、ここ（プリロード）でDOMを直接書き換える。表示するHTMLは、script-src 'none'で、
// ページ自身はスクリプトを持てない（原稿やエラーの内容を、スクリプトとして実行させないため）。プリロードは、
// ページのCSPの対象外（<script>タグを増やすわけではなく、既にあるDOMへ要素を足すだけ）のため、ここで行える。
const { ipcRenderer, webUtils } = require('electron');

window.addEventListener('dragover', (event) => event.preventDefault(), true);
window.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) ipcRenderer.send('open-path', webUtils.getPathForFile(file));
}, true);

// スクロール位置をメインプロセスへ伝える（#330）。
// 画面遷移時に非同期IPCで問い合わせると、openFileのキュー順序が崩れる（#342レビュー指摘）。
// スクロール時に最新の位置をメインプロセスへ送っておき、キュー処理は同期のまま保つ。
let scrollRaf = null;
window.addEventListener('scroll', () => {
  if (scrollRaf) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null;
    ipcRenderer.send('content-scroll', window.scrollY);
  });
}, { passive: true });

window.addEventListener('pagehide', () => {
  if (scrollRaf) {
    cancelAnimationFrame(scrollRaf);
    scrollRaf = null;
  }
  ipcRenderer.send('content-scroll', window.scrollY);
});

// -- 文書内検索（#325） ---------------------------------------------------------
// マッチングそのもの（buildMatcher・findMatches）は、`../search-match.js`と同じ内容を、ここに複製している。
// サンドボックス化したプリロード（sandbox: true）は、`electron`以外のローカルファイルをrequireできない
// （実測。エラー「module not found」）。ここを直すときは、`../search-match.js`とテスト（test/search-match.test.js）
// も、あわせて直すこと。

/**
 * 検索語から、検索に使うRegExpを作る。空の検索語は、検索なし（null）として扱う。
 * 通常の文字列検索も、正規表現の特殊文字を無効化したうえで、内部ではRegExpにそろえる（実装を1本にするため）。
 */
function buildMatcher(query, { regex = false, caseSensitive = false } = {}) {
  if (!query) return { ok: true, regex: null };
  const source = regex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  try {
    return { ok: true, regex: new RegExp(source, caseSensitive ? 'g' : 'gi') };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

/**
 * 1つの文字列の中から、一致する範囲（{start, end}）をすべて探す。空文字列に一致する正規表現（`a*`など）は、
 * 無限ループになるため、1文字分進めて続ける。件数にも、上限を設ける（病的な正規表現の影響を抑える）。
 */
function findMatches(text, matcherRegex) {
  if (!matcherRegex || !text) return [];
  const matches = [];
  matcherRegex.lastIndex = 0;
  let match;
  while ((match = matcherRegex.exec(text))) {
    if (match[0].length === 0) {
      matcherRegex.lastIndex += 1;
      if (matcherRegex.lastIndex > text.length) break;
      continue;
    }
    matches.push({ start: match.index, end: match.index + match[0].length });
    if (matches.length >= 5000) break;
  }
  return matches;
}

const MARK_CLASS = 'tc-search-mark';
const CURRENT_CLASS = 'tc-search-current';

let marks = [];     // 一致箇所（<mark>要素）。文書順
let current = -1;   // marksの中の、今の位置（-1は、一致なし）

/** ハイライト用の見た目。文書自体のCSSには無いため、ここで一度だけ足す（style-srcは、制限されていない）。 */
function ensureStyle() {
  if (document.getElementById('tc-search-style')) return;
  const style = document.createElement('style');
  style.id = 'tc-search-style';
  style.textContent = `
    mark.${MARK_CLASS} { background: #ffd93d; color: #1f2328; border-radius: 2px; }
    mark.${MARK_CLASS}.${CURRENT_CLASS} { background: #ff8c00; color: #fff; }
    @media (prefers-color-scheme: dark) {
      mark.${MARK_CLASS} { background: #8a6d1a; color: #f5f5f5; }
      mark.${MARK_CLASS}.${CURRENT_CLASS} { background: #b25900; color: #fff; }
    }
  `;
  document.head.appendChild(style);
}

/** 表示中の文字列（地の文）のテキストノードを、文書順で集める。スクリプト・スタイル・図（svg）の中は除く。 */
function collectTextNodes() {
  if (!document.body) return [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !node.nodeValue) return NodeFilter.FILTER_REJECT;
      if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE' || parent.closest('svg')) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) nodes.push(node);
  return nodes;
}

/** 1つのテキストノードの一致箇所を、<mark>で挟む。挟んだ<mark>は、marksへ積む（文書順が保たれる）。 */
function wrapNode(node, matches) {
  const text = node.textContent;
  const fragment = document.createDocumentFragment();
  let last = 0;
  for (const { start, end } of matches) {
    if (start > last) fragment.appendChild(document.createTextNode(text.slice(last, start)));
    const mark = document.createElement('mark');
    mark.className = MARK_CLASS;
    mark.textContent = text.slice(start, end);
    fragment.appendChild(mark);
    marks.push(mark);
    last = end;
  }
  if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
  node.replaceWith(fragment);
}

/** ハイライトを消し、元の文字列に戻す。 */
function clearMarks() {
  for (const mark of marks) mark.replaceWith(document.createTextNode(mark.textContent));
  document.body?.normalize();   // 隣り合うテキストノードを、1つに戻す
  marks = [];
  current = -1;
}

/** 今の位置の<mark>だけ、見た目を変え、見えるところまでスクロールする。 */
function applyCurrent() {
  for (const mark of marks) mark.classList.remove(CURRENT_CLASS);
  if (current >= 0 && marks[current]) {
    marks[current].classList.add(CURRENT_CLASS);
    marks[current].scrollIntoView({ block: 'center' });
  }
}

function result(error = null) {
  return { count: marks.length, current: marks.length ? current + 1 : 0, error };
}

function runSearch({ query, regex, caseSensitive }) {
  clearMarks();
  const built = buildMatcher(query, { regex, caseSensitive });
  if (!built.ok) return result(built.error);
  if (built.regex) {
    ensureStyle();
    for (const node of collectTextNodes()) {
      const found = findMatches(node.textContent, built.regex);
      if (found.length) wrapNode(node, found);
    }
    current = marks.length ? 0 : -1;
    applyCurrent();
  }
  return result();
}

function moveSearch(delta) {
  if (marks.length) {
    current = (current + delta + marks.length) % marks.length;
    applyCurrent();
  }
  return result();
}

ipcRenderer.on('search-run', (_event, payload) => ipcRenderer.send('search-result', runSearch(payload ?? {})));
ipcRenderer.on('search-move', (_event, delta) => ipcRenderer.send('search-result', moveSearch(delta)));
ipcRenderer.on('search-clear', () => clearMarks());
