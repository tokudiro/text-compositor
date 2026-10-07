'use strict';
// ツールバー・エラーの帯・診断の一覧（#190）。文書そのものは、別のビュー（メインプロセスが管理）に表示する。
// 表示する文字は、すべてtextContentで入れる（原稿やエラーの内容を、HTMLとして解釈しない）。
const api = window.viewer;
const $ = (id) => document.getElementById(id);
let detailsOpen = false;
let lastState = null;

/** 文字が変わったときだけ、書き換える。同じ文字で、要素の中身を置き換えると、ライブ領域（role=alert・status）が、同じ内容を、読み直すことがある（#340）。 */
function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

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
$('sidebar-button').addEventListener('click', () => api.toggleSidebar());
$('open-folder').addEventListener('click', () => api.openFolder());
// ファイルツリー（#339）。クリックしたファイルは、いまのタブで開く（tree.jsが、読み込みと操作を持つ）
const fileTree = createFileTree({
  container: $('tree'),
  listDirectory: (directory) => api.listDirectory(directory),
  openFile: (file) => api.openFromSidebar(file),   // 設定ファイルでも、モードを変えず、ただのファイルとして開く（#373）
  autoExpand: () => lastTreeKind === 'project',     // 章の一覧は、見出しを開いた状態で出す
});
let lastTreeKind = null;
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
$('speech-test').addEventListener('click', () => api.speechTest());
$('speech-voice').addEventListener('change', (event) => api.setSetting('speechVoice', event.target.value));
$('tab-new').addEventListener('click', () => api.newTab());
$('tab-close').addEventListener('click', () => { const active = lastState?.tabs?.find((t) => t.active); if (active) api.closeTab(active.id); });
$('banner').addEventListener('click', () => { detailsOpen = !detailsOpen; render(lastState); });

// ドラッグ＆ドロップ。ファイルへ、ページが遷移してしまわないように、既定の動作を止める。
window.addEventListener('dragover', (event) => { event.preventDefault(); document.body.classList.add('dragging'); });
window.addEventListener('dragleave', (event) => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
window.addEventListener('drop', (event) => {
  event.preventDefault();
  document.body.classList.remove('dragging');
  const file = event.dataTransfer?.files?.[0];
  if (file) api.openPath(api.pathForFile(file), event.ctrlKey);
});

/**
 * タブ列（#332）。設定「複数のタブ」がオンで、タブが2つ以上あるときだけ出す。
 * 名前は、textContentで入れる（ファイル名を、HTMLとして解釈しない）。タブが変わらない間は、作り直さない
 * （作り直すと、押している最中のボタンのフォーカスが、外れる）。
 */
let renderedTabs = '';
function renderTabs(state) {
  const visible = Boolean(state.settings.enableTabs) && state.tabs.length > 1;
  $('tabs-bar').hidden = !visible;
  const active = state.tabs.find((t) => t.active);
  $('tab-close').setAttribute('aria-label', active ? `「${active.title}」を閉じる` : '見ているタブを閉じる');
  const signature = JSON.stringify(state.tabs.map((t) => [t.id, t.title, t.active, t.busy, t.hasError]));
  if (signature === renderedTabs) return;
  renderedTabs = signature;
  const container = $('tabs');
  container.textContent = '';
  for (const t of state.tabs) {
    const item = document.createElement('div');
    item.className = `tab-item${t.active ? ' active' : ''}`;
    item.setAttribute('role', 'presentation');
    const tab = document.createElement('button');
    tab.className = `tab${t.hasError ? ' error' : ''}${t.busy ? ' busy' : ''}`;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', String(t.active));
    tab.title = t.file ?? t.title;
    tab.textContent = t.title;
    tab.addEventListener('click', () => api.activateTab(t.id));
    // 中ボタン（ホイールのクリック）で、そのタブを閉じる
    tab.addEventListener('auxclick', (event) => { if (event.button === 1) api.closeTab(t.id); });
    item.append(tab);
    container.append(item);
  }
}

/**
 * サイドバー（#339）。開閉は、state.sidebarOpen（覚えない。#373）。設定画面は全面を覆うため、開いている間は隠す（開閉の状態は、変えない）。
 * 文書の無い案内（#empty）も、サイドバーの右に寄せる（--sidebar-inset）。
 */
function renderSidebar(state) {
  // 設定「ファイルツリー」が「出さない」のときは、ボタンも出さず、開いていても、閉じたものとして扱う
  const enabled = Boolean(state.settings.showFileTree);
  const open = enabled && Boolean(state.sidebarOpen);
  $('sidebar-button').hidden = !enabled;
  $('sidebar').hidden = !open || state.settingsOpen;
  $('sidebar-button').setAttribute('aria-pressed', String(open));
  const root = document.documentElement.style;
  root.setProperty('--sidebar-width', `${state.sidebarWidth}px`);
  root.setProperty('--sidebar-inset', open ? `${state.sidebarWidth}px` : '0px');
  // ファイルツリー。フォルダを開くまでは、案内だけ（単一のファイルを開いただけのときは、ツリーを出さない）
  const treeRoot = state.tree.root;
  lastTreeKind = state.tree.kind;
  $('tree').setAttribute('aria-label', state.tree.kind === 'project' ? '章の一覧' : 'ファイルツリー');
  void fileTree.setRoot(treeRoot, state.tree.version ?? 0);
  fileTree.setCurrent(state.file);
  $('tree-hint').hidden = treeRoot !== null;
  const split = treeRoot ? Math.max(treeRoot.lastIndexOf('\\'), treeRoot.lastIndexOf('/')) : -1;
  setText($('tree-root-name'), treeRoot ? (treeRoot.slice(split + 1) || treeRoot) : '');
  $('tree-root-name').title = treeRoot ?? '';
}

/** 「表示する機能」の行を、機能の一覧（state.features。settings.jsのFEATURES）から作る（#326）。一覧が変わらない間は、作り直さない。 */
let renderedFeatures = '';
/** 読み上げの設定（#430）。声の一覧が変わったときだけ、選択肢を作り直す（選んでいる最中の操作を、壊さないため）。 */
function renderSpeech(state) {
  const supported = state.speech?.supported === true;
  $('speech-voice-row').hidden = !supported;
  $('speech-rate-row').hidden = !supported;
  if (!supported) return;
  const voices = state.speech.voices;
  const select = $('speech-voice');
  const key = JSON.stringify(voices);
  if (select.dataset.voices !== key) {
    select.dataset.voices = key;
    select.replaceChildren(...[['', '自動（日本語の声の先頭）'], ...voices.map((name) => [name, name])].map(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      return option;
    }));
  }
  // OSから消えた声は、自動と同じに扱う（設定の値は、そのまま残す）
  select.value = voices.includes(state.settings.speechVoice) ? state.settings.speechVoice : '';
}

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
  const previousSettingsOpen = Boolean(lastState?.settingsOpen);
  lastState = state;
  const d = state.diagnostics;
  document.body.classList.toggle('toolbar-bottom', state.settings.toolbarPosition === 'bottom');
  renderSearch(state.search, searchWasOpen);
  $('settings').hidden = !state.settingsOpen;
  renderSidebar(state);
  moveFocusForSettings(state, previousSettingsOpen);
  renderFeatures(state.features ?? []);
  renderTabs(state);
  $('settings-button').setAttribute('aria-pressed', String(state.settingsOpen));
  for (const [name, value] of Object.entries(state.settings)) {
    for (const radio of document.querySelectorAll(`#settings input[name="${name}"]`)) radio.checked = radio.value === String(value);
  }
  renderSpeech(state);
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
  setText($('zoom'), `${state.zoomPercent}%`);
  // 文字が「100%」だけだと、ボタンの名前が、操作（実寸に戻す）だけになり、今の倍率が伝わらない（#340）
  $('zoom').setAttribute('aria-label', `実寸に戻す（現在 ${state.zoomPercent}%）`);
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
  // スクリプトリーダーへの通知は、1か所に集める（変換中 → 更新の完了）。画面の表示（#busy・#status）は、読ませない
  setText($('live'), state.busy ? '変換中' : state.file ? `${state.status}` : '');
  // 案内は、何も開いていないときだけ。ファイルを開いている最中に、「開いてください」と出さない
  $('empty').hidden = state.hasDocument || state.busy || state.settingsOpen;

  const showBanner = d.hasError || d.warnings > 0;
  $('banner').hidden = !showBanner;
  $('banner').classList.toggle('warning', !d.hasError);
  // エラーは、すぐ読み上げる（alert）。警告は、今の読み上げを、遮らない（status）（#340）
  $('banner').setAttribute('role', d.hasError ? 'alert' : 'status');
  // エラーが新しく出たときは、詳細を、自動で開く
  if (d.hasError && !previousErrors) detailsOpen = true;
  if (!showBanner) detailsOpen = false;

  // 帯は、要約だけ。詳細を開いているときは、一覧が同じ内容を出すため、帯は、件数の見出しにする（同じ文を2回出さない）
  const counts = `${d.hasError ? `変換エラー ${d.errors} 件` : ''}${d.hasError && d.warnings > 0 ? '・' : ''}${d.warnings > 0 ? `警告 ${d.warnings} 件` : ''}`;
  const summary = d.hasError ? `変換エラー: ${d.banner}${d.errors > 1 ? `（ほか ${d.errors - 1} 件）` : ''}` : `警告 ${d.warnings} 件: ${d.warningBanner}`;
  setText($('banner-text'), detailsOpen ? counts : summary);
  $('banner-text').title = detailsOpen ? '' : summary;
  setText($('banner-toggle'), detailsOpen ? '閉じる' : '詳細');
  $('banner-toggle').setAttribute('aria-expanded', String(detailsOpen));

  const details = $('details');
  details.hidden = !(showBanner && detailsOpen);
  details.replaceChildren(...d.items.map(itemElement));
  requestAnimationFrame(reportHeight);
}

/**
 * 設定画面を開いたとき、見出しへ、フォーカスを移す（スクリーンリーダーが「設定」と読み、Tabで、最初の項目へ進める）。
 * 閉じたとき、文書が無ければ、歯車のボタンへ戻す（文書があるときは、メインプロセスが、文書へ戻す）。（#340）
 */
function moveFocusForSettings(state, wasOpen) {
  if (state.settingsOpen && !wasOpen) $('settings-title').focus();
  else if (!state.settingsOpen && wasOpen && !state.hasDocument) $('settings-button').focus();
}

/** 検索欄（#325）。入力欄の値は、状態から書き戻さない（入力中に、キー操作と競合させないため）。開いた瞬間だけ、そろえる。 */
let lastQueryRevision;
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
  // 右クリックの「選択範囲で検索」（#429）で、メイン側が検索語を入れたときは、開いたままでも、入力欄をそろえる
  const revised = search.queryRevision !== undefined && search.queryRevision !== lastQueryRevision;
  lastQueryRevision = search.queryRevision;
  if (search.open && revised && wasOpen) input.value = search.query;
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
