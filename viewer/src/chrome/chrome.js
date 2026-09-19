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
$('auto-reload').addEventListener('change', (event) => api.setAutoReload(event.target.checked));
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

  $('file').textContent = state.file ? state.file : '';
  $('file').title = state.file ?? '';
  $('zoom').textContent = `${state.zoomPercent}%`;
  $('auto-reload').checked = state.autoReload;
  $('reload').disabled = !state.file || state.busy;
  $('busy').hidden = !state.busy;
  $('status').textContent = state.busy ? '' : state.status;
  // 案内は、何も開いていないときだけ。ファイルを開いている最中に、「開いてください」と出さない
  $('empty').hidden = state.hasDocument || state.busy;

  const showBanner = d.hasError || d.warnings > 0;
  $('banner').hidden = !showBanner;
  $('banner').classList.toggle('warning', !d.hasError);
  $('banner-text').textContent = d.hasError ? `変換エラー: ${d.banner}` : `警告 ${d.warnings} 件`;
  // エラーが新しく出たときは、詳細を、自動で開く
  if (d.hasError && !previousErrors) detailsOpen = true;
  if (!showBanner) detailsOpen = false;

  const details = $('details');
  details.hidden = !(showBanner && detailsOpen);
  details.replaceChildren(...d.items.map(itemElement));
  requestAnimationFrame(reportHeight);
}

function itemElement(item) {
  const root = document.createElement('div');
  root.className = 'item';
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
  if (height !== reportedHeight) { reportedHeight = height; api.setChromeHeight(height); }
}

api.onState(render);
new ResizeObserver(reportHeight).observe($('top'));
api.ready();
