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
  if (file) ipcRenderer.send('open-path', webUtils.getPathForFile(file), event.ctrlKey);
}, true);

// 相対パスのリンク（`other.md`）は、ブラウザに解決させない。表示中のHTMLは、変換結果の置き場所にあり、原稿の隣の
// ファイルに届かないため、属性の値をそのままメインプロセスへ渡し、原稿のフォルダを基準に解決してもらう（#361）。
// スキーム付きのリンクと、文書内のアンカー（`#…`）は、これまでどおり（前者はwill-navigate、後者はブラウザ）。
window.addEventListener('click', (event) => {
  if (event.button !== 0 || !(event.target instanceof Element)) return;
  const href = event.target.closest('a[href]')?.getAttribute('href');
  if (!href || href.startsWith('#') || /^[a-z][a-z0-9+.-]*:/i.test(href)) return;
  event.preventDefault();
  ipcRenderer.send('open-link', href);
}, true);

// 画像ファイル（#413）は、クリックで、窓の幅に収める表示と、原寸を切り替える。窓より広い画像（スクリーンショットなど）は、
// 収めると文字が読めないため。ページはscriptを持てないので、クラスの付け外しは、ここで行う（CSSは、html_output.py）。
window.addEventListener('click', (event) => {
  if (event.button !== 0 || !(event.target instanceof Element)) return;
  event.target.closest('main.image-file .image-view img')?.classList.toggle('actual-size');
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
      // 見出しの「#」・コードの「コピー」（#337・#336）は、原稿の文字ではない。検索の対象から外す
      if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE' || parent.closest('svg, .tc-ui')) return NodeFilter.FILTER_REJECT;
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

// -- 行番号の表示（#328） -----------------------------------------------------------
// マウスを乗せたブロックの`data-line`（元のMarkdownの行番号）を、メインプロセスへ送る。ツールバーが、ファイル名の右横に
// 出す（表示・クリックでコピーは、ツールバー側）。文書自身は、script-src 'none'で、スクリプトを持てないため、
// ここ（プリロード）で、`mouseover`を受ける。ブロックが変わったときだけ送り、ブロックの外（余白）に乗ったときは、送らない
// （ツールバーは、最後の行を保つ）。オフのときは、何も送らない。
let lineIndicatorOn = false;
let lastLine = null;

ipcRenderer.on('line-indicator', (_event, on) => {
  lineIndicatorOn = on === true;
  lastLine = null;
});

window.addEventListener('mouseover', (event) => {
  if (!lineIndicatorOn || !(event.target instanceof Element)) return;
  const element = event.target.closest('[data-line]');
  if (!element) return;
  const line = Number.parseInt(element.getAttribute('data-line'), 10);
  if (!Number.isInteger(line) || line === lastLine) return;
  lastLine = line;
  ipcRenderer.send('content-line', line);
}, true);

// -- リンク先の表示（#362） --------------------------------------------------------------
// リンクにマウスを乗せたとき、飛び先を、画面の左下に出す（Chromeのステータスバブルと同じ）。表示する文字列は、
// メインプロセスが作る（相対リンクは、原稿のフォルダを基準にした場所にするため）。ここは、乗せた・離れたを伝え、返ってきた文字列を描く。
let hoveredHref = null;
let bubble = null;

function ensureBubble() {
  if (bubble && bubble.isConnected) return bubble;
  bubble = document.createElement('div');
  bubble.id = 'tc-link-bubble';
  bubble.style.cssText = 'position:fixed;left:0;bottom:0;z-index:2147483647;max-width:70%;padding:2px 8px;'
    + 'font:12px/1.5 system-ui,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none;'
    + 'border:1px solid #d0d7de;border-left:0;border-bottom:0;border-radius:0 6px 0 0;background:#f6f8fa;color:#1f2328;display:none;';
  if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    bubble.style.background = '#161b22'; bubble.style.color = '#e6edf3'; bubble.style.borderColor = '#30363d';
  }
  document.documentElement.appendChild(bubble);
  return bubble;
}

window.addEventListener('mouseover', (event) => {
  const href = event.target instanceof Element ? event.target.closest('a[href]')?.getAttribute('href') ?? null : null;
  if (href === hoveredHref) return;
  hoveredHref = href;
  if (href === null && bubble) bubble.style.display = 'none';
  else ipcRenderer.send('link-hover', href);
}, true);

// ウィンドウの外へ出たときは、mouseoverが来ないため、ここで消す
window.addEventListener('mouseout', (event) => {
  if (event.relatedTarget !== null) return;
  hoveredHref = null;
  if (bubble) bubble.style.display = 'none';
}, true);

ipcRenderer.on('link-hover-text', (_event, text) => {
  if (hoveredHref === null || !text) { if (bubble) bubble.style.display = 'none'; return; }
  const element = ensureBubble();
  element.textContent = text;
  element.title = text;
  element.style.display = 'block';
});

// -- 見出しのリンク（#337）・コードのコピーボタン（#336） ------------------------------------
// ホバーしたときだけ出す、小さな部品。文書のHTMLは、script-src 'none'でスクリプトを持てないため、プリロードが、
// 表示中のDOMへ足す。足した要素は`tc-ui`クラスで印を付け、検索の対象から外す（「#」「コピー」が、一致しないように）。
// クリップボードへの書き込みは、メインプロセスが行う（ここは、何をコピーするかを伝えるだけ）。
const UI_CLASS = 'tc-ui';
let contentFeatures = { headingAnchor: false, codeCopy: false };
const flashTimers = new WeakMap();

function ensureUiStyle() {
  if (document.getElementById('tc-ui-style')) return;
  const style = document.createElement('style');
  style.id = 'tc-ui-style';
  style.textContent = `
    .tc-ui { user-select: none; cursor: pointer; opacity: 0; transition: opacity 0.12s; }
    .tc-anchor { margin-left: 0.4em; color: #59636e; font-weight: normal; text-decoration: none; }
    :is(h1, h2, h3, h4, h5, h6):hover > .tc-anchor { opacity: 1; }
    pre { position: relative; }
    .tc-copy { position: absolute; top: 6px; right: 6px; padding: 2px 8px; font: 12px/1.5 system-ui, sans-serif;
      color: #1f2328; background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; }
    pre:hover > .tc-copy { opacity: 1; }
    @media (prefers-color-scheme: dark) {
      .tc-anchor { color: #9198a1; }
      .tc-copy { color: #e6edf3; background: #161b22; border-color: #30363d; }
    }
  `;
  document.head.appendChild(style);
}

/** 押した直後だけ、表示を変えて（コピーした合図）、少しして戻す。 */
function flash(element, doneLabel, restoreLabel) {
  clearTimeout(flashTimers.get(element));
  element.textContent = doneLabel;
  element.style.opacity = '1';
  flashTimers.set(element, setTimeout(() => { element.textContent = restoreLabel; element.style.opacity = ''; }, 1200));
}

function makeUi(className, label, title) {
  const element = document.createElement('span');
  element.className = `${UI_CLASS} ${className}`;
  element.textContent = label;
  element.title = title;
  element.setAttribute('role', 'button');
  return element;
}

/** コードブロックの中身（<pre>の直下のうち、足した部品を除いた文字）。 */
function codeText(pre) {
  return Array.from(pre.childNodes).filter((node) => !(node.classList && node.classList.contains(UI_CLASS))).map((node) => node.textContent).join('');
}

function removeUi() {
  for (const element of document.querySelectorAll(`.${UI_CLASS}`)) element.remove();
}

function buildUi() {
  removeUi();
  if (!document.body || (!contentFeatures.headingAnchor && !contentFeatures.codeCopy)) return;
  ensureUiStyle();
  if (contentFeatures.headingAnchor) {
    for (const heading of document.querySelectorAll('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]')) {
      const anchor = makeUi('tc-anchor', '#', 'この見出しへのリンクをコピー');
      anchor.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        ipcRenderer.send('copy-heading-link', heading.id);
        flash(anchor, '✓', '#');
      });
      heading.appendChild(anchor);
    }
  }
  if (contentFeatures.codeCopy) {
    for (const pre of document.querySelectorAll('pre')) {
      const button = makeUi('tc-copy', 'コピー', 'コードをコピー');
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        ipcRenderer.send('copy-code', codeText(pre));
        flash(button, 'コピーしました', 'コピー');
      });
      pre.appendChild(button);
    }
  }
}

ipcRenderer.on('content-features', (_event, features) => {
  contentFeatures = { headingAnchor: features?.headingAnchor === true, codeCopy: features?.codeCopy === true };
  buildUi();
});

// -- 図の拡大表示（#338） -------------------------------------------------------------------------------------------
// 本文の図（.diagram img）をクリックすると、同じページの上に、全面のオーバーレイを重ねて、図だけを大きく見せる。
// ホイールで拡大・縮小（カーソルの位置を中心に）、ドラッグでパン、ダブルクリックと0キーで「画面に収める」に戻す。Escか背景のクリックで閉じる。
// ページ全体のズーム（Ctrl＋ホイール）とは別。ページはscriptを持てないため、ここ（プリロード）でDOMを足す。
// 図は、.diagramの中の<img>のまま複製する。ダークの反転フィルター（#209。CSSは、html_output.pyの`.diagram img`）が、そのまま掛かるため。
// 右クリックの「画像を保存」（#327）も、<img>なので、そのまま使える。倍率は、「画面に収めた大きさ」を1として、0.5〜32倍。
const LIGHTBOX_MIN_SCALE = 0.5;
const LIGHTBOX_MAX_SCALE = 32;
const LIGHTBOX_FIT_RATIO = 0.92;   // 収めるときの、画面に対する大きさ（縁を少し残す）
let lightbox = null;

function ensureLightboxStyle() {
  if (document.getElementById('tc-lightbox-style')) return;
  const style = document.createElement('style');
  style.id = 'tc-lightbox-style';
  style.textContent = `
    .diagram img { cursor: zoom-in; }
    .tc-lightbox { position: fixed; inset: 0; z-index: 2147483000; display: flex; align-items: center; justify-content: center;
      overflow: hidden; background: Canvas; color-scheme: light dark; cursor: grab; user-select: none; touch-action: none; }
    .tc-lightbox.dragging { cursor: grabbing; }
    .tc-lightbox .diagram { margin: 0; flex: none; transform-origin: center center; will-change: transform; }
    .tc-lightbox .diagram img { display: block; max-width: none; cursor: inherit; -webkit-user-drag: none; }
  `;
  document.head.appendChild(style);
}

function openLightbox(source) {
  if (lightbox || !document.body) return;
  ensureLightboxStyle();
  const overlay = document.createElement('div');
  overlay.className = 'tc-lightbox';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', '図の拡大表示');
  const stage = document.createElement('div');
  stage.className = 'diagram';
  const image = document.createElement('img');
  image.alt = source.alt || '';
  stage.appendChild(image);
  overlay.appendChild(stage);
  document.body.appendChild(overlay);

  const view = { scale: 1, x: 0, y: 0 };
  const apply = () => { stage.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`; };
  // 画面に収める大きさを、画像の元の大きさ（SVGは、viewBoxなどで決まる大きさ）から求める。0のときは、本文での表示の大きさを使う
  const fit = () => {
    const rect = source.getBoundingClientRect();
    const naturalWidth = image.naturalWidth || rect.width || 1;
    const naturalHeight = image.naturalHeight || rect.height || 1;
    const ratio = Math.min(window.innerWidth * LIGHTBOX_FIT_RATIO / naturalWidth, window.innerHeight * LIGHTBOX_FIT_RATIO / naturalHeight);
    image.style.width = `${naturalWidth * ratio}px`;
    view.scale = 1; view.x = 0; view.y = 0;
    apply();
  };
  // 画面の中心を原点にして、(px, py)の下にある図の点が、動かないように、拡大・縮小する
  const zoomAt = (factor, px = window.innerWidth / 2, py = window.innerHeight / 2) => {
    const next = Math.min(LIGHTBOX_MAX_SCALE, Math.max(LIGHTBOX_MIN_SCALE, view.scale * factor));
    const ratio = next / view.scale;
    const cx = px - window.innerWidth / 2;
    const cy = py - window.innerHeight / 2;
    view.x = cx - (cx - view.x) * ratio;
    view.y = cy - (cy - view.y) * ratio;
    view.scale = next;
    apply();
  };

  let drag = null;
  const onWheel = (event) => {
    event.preventDefault();   // ページのスクロール・Ctrl＋ホイールのページズームは、図の拡大に使う
    const unit = event.deltaMode === 1 ? 16 : 1;
    zoomAt(Math.exp(-event.deltaY * unit * 0.0015), event.clientX, event.clientY);
  };
  const onPointerDown = (event) => {
    if (event.button !== 0) return;
    // ポインターキャプチャを使うと、clickの対象が、常にオーバーレイになる。背景か図かは、押した時点の対象で決める
    drag = { x: event.clientX, y: event.clientY, startX: view.x, startY: view.y, moved: false, onBackground: event.target === overlay };
    overlay.setPointerCapture(event.pointerId);
    overlay.classList.add('dragging');
  };
  const onPointerMove = (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    view.x = drag.startX + dx;
    view.y = drag.startY + dy;
    apply();
  };
  const onPointerUp = () => { overlay.classList.remove('dragging'); };
  // ドラッグの後のクリックでは、閉じない。背景（図の外）のクリックだけ、閉じる
  const onClick = () => {
    const closing = drag !== null && !drag.moved && drag.onBackground;
    drag = null;
    if (closing) close();
  };
  const onKeyDown = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    else if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomAt(1.25); }
    else if (event.key === '-') { event.preventDefault(); zoomAt(0.8); }
    else if (event.key === '0') { event.preventDefault(); fit(); }
  };
  function close() {
    overlay.removeEventListener('wheel', onWheel);
    window.removeEventListener('keydown', onKeyDown, true);
    window.removeEventListener('resize', fit);
    overlay.remove();
    lightbox = null;
  }

  overlay.addEventListener('wheel', onWheel, { passive: false });
  overlay.addEventListener('pointerdown', onPointerDown);
  overlay.addEventListener('pointermove', onPointerMove);
  overlay.addEventListener('pointerup', onPointerUp);
  overlay.addEventListener('pointercancel', onPointerUp);
  overlay.addEventListener('click', onClick);
  overlay.addEventListener('dblclick', fit);
  window.addEventListener('keydown', onKeyDown, true);
  window.addEventListener('resize', fit);
  image.addEventListener('load', fit);
  image.src = source.currentSrc || source.src;
  fit();
  lightbox = { close, overlay, view };
}

window.addEventListener('click', (event) => {
  if (event.button !== 0 || event.ctrlKey || event.shiftKey || event.altKey || event.metaKey || !(event.target instanceof Element)) return;
  if (event.target.closest('.tc-lightbox') || event.target.closest('a[href]')) return;
  const image = event.target.closest('.diagram img');
  if (image) openLightbox(image);
}, true);
window.addEventListener('DOMContentLoaded', ensureLightboxStyle);
