'use strict';
// ツールバー・エラーの帯・診断の一覧（#190）。文書そのものは、別のビュー（メインプロセスが管理）に表示する。
// 表示する文字は、すべてtextContentで入れる（原稿やエラーの内容を、HTMLとして解釈しない）。
const api = window.viewer;
const $ = (id) => document.getElementById(id);
let detailsOpen = false;
let lastState = null;

$('back').addEventListener('click', () => api.goBack());
$('forward').addEventListener('click', () => api.goForward());
$('open').addEventListener('click', () => api.openDialog());
$('reload').addEventListener('click', () => api.reload());
$('zoom-in').addEventListener('click', () => api.zoomIn());
$('zoom-out').addEventListener('click', () => api.zoomOut());
$('zoom').addEventListener('click', () => api.zoomReset());
$('auto-reload').addEventListener('click', () => api.setAutoReload($('auto-reload').getAttribute('aria-checked') !== 'true'));
$('empty-open').addEventListener('click', () => api.openDialog());
$('csv-header').addEventListener('click', () => api.setCsvHeader($('csv-header').getAttribute('aria-checked') !== 'true'));
$('settings-button').addEventListener('click', () => api.toggleSettings());
$('settings-close').addEventListener('click', () => api.toggleSettings());
$('search-button').addEventListener('click', () => api.toggleSearch());
$('search-close').addEventListener('click', () => api.closeSearch());
$('search-prev').addEventListener('click', () => api.moveSearch(-1));
$('search-next').addEventListener('click', () => api.moveSearch(1));
$('search-regex').addEventListener('click', () => sendSearch({ regex: $('search-regex').getAttribute('aria-checked') !== 'true' }));
$('search-case').addEventListener('click', () => sendSearch({ caseSensitive: $('search-case').getAttribute('aria-checked') !== 'true' }));
// 入力は、打つたびに送ると重いことがあるため、少し待ってから送る（変換の自動更新と同じ考え方。#170）
let searchDebounce = null;
$('search-input').addEventListener('input', () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => sendSearch(), 150);
});
$('search-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') { event.preventDefault(); api.moveSearch(event.shiftKey ? -1 : 1); }
  else if (event.key === 'Escape') { event.preventDefault(); api.closeSearch(); }
});
/** 今の入力欄・トグルの状態を、まとめて送る。トグルのクリックは、待たずにすぐ送る。 */
function sendSearch(overrides = {}) {
  clearTimeout(searchDebounce);
  api.setSearch({
    query: $('search-input').value,
    regex: $('search-regex').getAttribute('aria-checked') === 'true',
    caseSensitive: $('search-case').getAttribute('aria-checked') === 'true',
    ...overrides,
  });
}
$('choose-directory').addEventListener('click', () => api.chooseOpenDirectory());
$('clear-cache').addEventListener('click', () => api.clearCache());
// 設定の変更は、ラジオボタンを選んだ時点で、すぐに反映する（保存も、メインプロセスが行う）
$('settings').addEventListener('change', (event) => {
  if (event.target.matches('input[type="radio"]')) {
    // 真偽値の設定（allowExternalImages）は、ラジオの値が"true"/"false"の文字列のため、送る前に戻す
    const value = event.target.value === 'true' ? true : event.target.value === 'false' ? false : event.target.value;
    api.setSetting(event.target.name, value);
  }
});
$('banner').addEventListener('click', () => { detailsOpen = !detailsOpen; render(lastState); });

// ドラッグ＆ドロップ。ファイルへ、ページが遷移してしまわないように、既定の動作を止める。
window.addEventListener('dragover', (event) => { event.preventDefault(); document.body.classList.add('dragging'); });
window.addEventListener('dragleave', (event) => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
window.addEventListener('drop', (event) => {
  event.preventDefault();
  document.body.classList.remove('dragging');
  const file = event.dataTransfer?.files?.[0];
  if (file) api.openPath(api.pathForFile(file));
});

/** 「表示する機能」の行を、機能の一覧（state.features。settings.jsのFEATURES）から作る（#326）。一覧が変わらない間は、作り直さない。 */
let renderedFeatures = '';
function renderFeatures(features) {
  const signature = JSON.stringify(features);
  if (signature === renderedFeatures) return;
  renderedFeatures = signature;
  const container = $('feature-rows');
  container.textContent = '';
  for (const feature of features) {
    const row = document.createElement('div');
    row.className = 'row';
    const text = document.createElement('div');
    text.className = 'text';
    const name = document.createElement('div');
    name.className = 'name';
    name.id = `feature-${feature.key}-name`;
    name.textContent = feature.label;
    const desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = feature.description;
    text.append(name, desc);
    const group = document.createElement('div');
    group.className = 'segmented';
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-labelledby', name.id);
    for (const [value, caption] of [['true', feature.on], ['false', feature.off]]) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = feature.key;
      input.value = value;
      const span = document.createElement('span');
      span.textContent = caption;
      label.append(input, span);
      group.append(label);
    }
    row.append(text, group);
    container.append(row);
  }
}

function render(state) {
  if (!state) return;
  const previousErrors = lastState?.diagnostics.hasError;
  const searchWasOpen = lastState?.search.open;
  lastState = state;
  const d = state.diagnostics;
  document.body.classList.toggle('toolbar-bottom', state.settings.toolbarPosition === 'bottom');
  renderSearch(state.search, searchWasOpen);
  $('settings').hidden = !state.settingsOpen;
  renderFeatures(state.features ?? []);
  $('settings-button').setAttribute('aria-pressed', String(state.settingsOpen));
  for (const [name, value] of Object.entries(state.settings)) {
    for (const radio of document.querySelectorAll(`#settings input[name="${name}"]`)) radio.checked = radio.value === String(value);
  }
  const fixed = state.settings.openDirectoryMode === 'fixed';
  $('fixed-directory-row').hidden = !fixed;
  $('fixed-directory').textContent = state.settings.fixedDirectory ?? '未指定（ドキュメントのフォルダから始まります）';
  $('fixed-directory').title = state.settings.fixedDirectory ?? '';
  // アプリの領域の使用量。数え終わるまでは、空にする。0のときは、削除するものが無い
  $('cache-size').textContent = state.cache.bytes === null ? '' : formatBytes(state.cache.bytes);
  $('clear-cache').disabled = state.cache.clearing || !state.cache.bytes;
  $('clear-cache').textContent = state.cache.clearing ? '削除中…' : '削除';

  // ファイル名を主にして、フォルダは、控えめに添える。全体は、ホバーで表示する
  const split = state.file ? Math.max(state.file.lastIndexOf('\\'), state.file.lastIndexOf('/')) : -1;
  $('file-name').textContent = state.file ? state.file.slice(split + 1) : '';
  $('file-dir').textContent = split > 0 ? state.file.slice(0, split) : '';
  $('file').title = state.file ?? '';
  // 行番号（#328）。マウスを乗せたブロックの行を、ファイル名の右横に出す。乗せていない間も、最後の行を保つ
  const lineRef = $('line-ref');
  lineRef.hidden = !(state.file && state.settings.showLineNumber && state.line);
  lineRef.textContent = `:${state.line}`;
  lineRef.title = `マウスを乗せたブロックの、元のMarkdownの行（内容を右クリックすると、コピーできます）`;
  $('zoom').textContent = `${state.zoomPercent}%`;
  $('auto-reload').setAttribute('aria-checked', String(state.autoReload));
  $('csv-header').hidden = !state.isCsv;
  $('csv-header').setAttribute('aria-checked', String(state.settings.csvHeader));
  $('csv-header').title = `CSV: 1行目を見出しにする（${state.settings.csvHeader ? 'オン' : 'オフ'}）`;
  $('auto-reload').title = `保存したら自動で更新する（${state.autoReload ? 'オン' : 'オフ'}）`;
  $('reload').disabled = !state.file || state.busy;
  $('back').disabled = !state.canGoBack || state.busy;
  $('forward').disabled = !state.canGoForward || state.busy;
  // 文書が無いときは、拡大縮小・検索の対象が無い
  for (const id of ['zoom-in', 'zoom-out', 'zoom', 'search-button']) $(id).disabled = !state.hasDocument;
  $('busy').hidden = !state.busy;
  $('status').textContent = state.busy ? '' : state.status;
  // 案内は、何も開いていないときだけ。ファイルを開いている最中に、「開いてください」と出さない
  $('empty').hidden = state.hasDocument || state.busy || state.settingsOpen;

  const showBanner = d.hasError || d.warnings > 0;
  $('banner').hidden = !showBanner;
  $('banner').classList.toggle('warning', !d.hasError);
  // エラーが新しく出たときは、詳細を、自動で開く
  if (d.hasError && !previousErrors) detailsOpen = true;
  if (!showBanner) detailsOpen = false;

  // 帯は、要約だけ。詳細を開いているときは、一覧が同じ内容を出すため、帯は、件数の見出しにする（同じ文を2回出さない）
  const counts = `${d.hasError ? `変換エラー ${d.errors} 件` : ''}${d.hasError && d.warnings > 0 ? '・' : ''}${d.warnings > 0 ? `警告 ${d.warnings} 件` : ''}`;
  const summary = d.hasError ? `変換エラー: ${d.banner}${d.errors > 1 ? `（ほか ${d.errors - 1} 件）` : ''}` : `警告 ${d.warnings} 件: ${d.warningBanner}`;
  $('banner-text').textContent = detailsOpen ? counts : summary;
  $('banner-text').title = detailsOpen ? '' : summary;
  $('banner-toggle').textContent = detailsOpen ? '閉じる' : '詳細';

  const details = $('details');
  details.hidden = !(showBanner && detailsOpen);
  details.replaceChildren(...d.items.map(itemElement));
  requestAnimationFrame(reportHeight);
}

/** 検索欄（#325）。入力欄の値は、状態から書き戻さない（入力中に、キー操作と競合させないため）。開いた瞬間だけ、そろえる。 */
function renderSearch(search, wasOpen) {
  const input = $('search-input');
  $('search').hidden = !search.open;
  $('search-button').setAttribute('aria-pressed', String(search.open));
  $('search-regex').setAttribute('aria-checked', String(search.regex));
  $('search-case').setAttribute('aria-checked', String(search.caseSensitive));
  $('search-count').textContent = !search.query ? ''
    : search.error ? '正規表現が不正です'
    : search.count ? `${search.current} / ${search.count}`
    : '見つかりません';
  $('search-count').classList.toggle('error', Boolean(search.error));
  $('search-prev').disabled = $('search-next').disabled = !search.count;
  if (search.open && !wasOpen) {
    input.value = search.query;
    input.focus();
    input.select();
  }
}

/** 使用量の表示。1 MB未満はKB、それ以上はMB（小数1桁）。 */
function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function itemElement(item) {
  const root = document.createElement('div');
  root.className = `item ${item.severity}`;
  const head = document.createElement('div');
  head.className = 'head';
  const mark = document.createElement('span');
  mark.className = `mark ${item.severity}`;
  mark.textContent = item.severity === 'error' ? '●' : item.severity === 'warning' ? '▲' : '→';
  const message = document.createElement('span');
  message.textContent = item.message;
  head.append(mark, message);
  if (item.location) {
    const loc = document.createElement('span');
    loc.className = 'loc';
    loc.textContent = item.location;
    head.append(loc);
  }
  root.append(head);
  if (item.detail) {
    const pre = document.createElement('pre');
    pre.textContent = item.detail;
    root.append(pre);
  }
  return root;
}

let reportedHeight = 0;
function reportHeight() {
  const height = Math.ceil($('top').getBoundingClientRect().height);
  // 設定画面を、ツールバー・帯の反対側に、収めるため
  document.documentElement.style.setProperty('--chrome-height', `${height}px`);
  if (height !== reportedHeight) { reportedHeight = height; api.setChromeHeight(height); }
}

api.onState(render);
new ResizeObserver(reportHeight).observe($('top'));
api.ready();
