'use strict';
// ツールバー・エラーの帯・診断の一覧（#190）。文書そのものは、別のビュー（メインプロセスが管理）に表示する。
// 表示する文字は、すべてtextContentで入れる（原稿やエラーの内容を、HTMLとして解釈しない）。
const api = window.viewer;
const $ = (id) => document.getElementById(id);
let detailsOpen = false;
let lastState = null;

$('open').addEventListener('click', () => api.openDialog());
$('reload').addEventListener('click', () => api.reload());
$('zoom-in').addEventListener('click', () => api.zoomIn());
$('zoom-out').addEventListener('click', () => api.zoomOut());
$('zoom').addEventListener('click', () => api.zoomReset());
$('auto-reload').addEventListener('click', () => api.setAutoReload($('auto-reload').getAttribute('aria-checked') !== 'true'));
$('settings-button').addEventListener('click', () => api.toggleSettings());
// 設定の変更は、ラジオボタンを選んだ時点で、すぐに反映する（保存も、メインプロセスが行う）
$('settings').addEventListener('change', (event) => {
  if (event.target.matches('input[type="radio"]')) api.setSetting(event.target.name, event.target.value);
});
$('banner').addEventListener('click', () => { detailsOpen = !detailsOpen; render(lastState); });

// ドラッグ＆ドロップ。ファイルへ、ページが遷移してしまわないように、既定の動作を止める。
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('drop', (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) api.openPath(api.pathForFile(file));
});

function render(state) {
  if (!state) return;
  const previousErrors = lastState?.diagnostics.hasError;
  lastState = state;
  const d = state.diagnostics;
  document.body.classList.toggle('fullscreen', state.fullScreen);
  document.body.classList.toggle('toolbar-bottom', state.settings.toolbarPosition === 'bottom');
  $('settings').hidden = !state.settingsOpen;
  $('settings-button').setAttribute('aria-pressed', String(state.settingsOpen));
  for (const [name, value] of Object.entries(state.settings)) {
    for (const radio of document.querySelectorAll(`#settings input[name="${name}"]`)) radio.checked = radio.value === value;
  }

  // ファイル名を主にして、フォルダは、控えめに添える。全体は、ホバーで表示する
  const split = state.file ? Math.max(state.file.lastIndexOf('\\'), state.file.lastIndexOf('/')) : -1;
  $('file-name').textContent = state.file ? state.file.slice(split + 1) : '';
  $('file-dir').textContent = split > 0 ? state.file.slice(0, split) : '';
  $('file').title = state.file ?? '';
  $('zoom').textContent = `${state.zoomPercent}%`;
  $('auto-reload').setAttribute('aria-checked', String(state.autoReload));
  $('auto-reload').title = `保存したら自動で更新する（${state.autoReload ? 'オン' : 'オフ'}）`;
  $('reload').disabled = !state.file || state.busy;
  // 文書が無いときは、拡大縮小の対象が無い
  for (const id of ['zoom-in', 'zoom-out', 'zoom']) $(id).disabled = !state.hasDocument;
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
