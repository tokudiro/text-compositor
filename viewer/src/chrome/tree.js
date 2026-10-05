'use strict';
// サイドバーのファイルツリー（#339）。WAI-ARIAのツリー（role=tree・treeitem・group）として作り、矢印キーで操作できる。
// 項目の名前は、すべてtextContent・aria-labelで入れる（ファイル名を、HTMLとして解釈しない）。
// フォルダの一覧は、開いたときに、そのフォルダの直下だけを読む（再帰しない）。読み込みは、メインプロセスが非同期で行う。

/**
 * @param {{container: HTMLElement, listDirectory: (path: string) => Promise<{ok: boolean, entries?: {name: string, path: string, type: string}[], message?: string}>, openFile: (path: string) => void}} options
 */
function createFileTree({ container, listDirectory, openFile, autoExpand = () => false }) {
  let root = null;
  let rootVersion = 0;      // 同じルートでも、版が変われば、読み直す（設定ファイルを開き直したとき。#373）
  let current = null;      // 今開いているファイル（ハイライトする）
  let generation = 0;       // フォルダを替えたら進める。古い読み込みの結果が、新しいツリーへ入らないようにする

  // WindowsのパスはOSが大文字小文字を区別しないため、ドライブ文字つきのパスだけ、区別せずに比べる
  const normalize = (p) => (/^[a-z]:[\\/]/i.test(p) ? p.replace(/\//g, '\\').toLowerCase() : p);
  const sameFile = (a, b) => Boolean(a) && Boolean(b) && normalize(a) === normalize(b);

  const visibleItems = () => [...container.querySelectorAll('[role="treeitem"]')].filter((item) => {
    for (let node = item.parentElement; node && node !== container; node = node.parentElement) {
      if (node.getAttribute('role') === 'treeitem' && node.getAttribute('aria-expanded') !== 'true') return false;
    }
    return true;
  });

  function focusItem(item) {
    for (const each of container.querySelectorAll('[role="treeitem"][tabindex="0"]')) each.tabIndex = -1;
    item.tabIndex = 0;
    item.focus();
  }

  function messageItem(text, level) {
    const item = document.createElement('li');
    item.className = 'tree-message';
    item.setAttribute('role', 'treeitem');
    item.setAttribute('aria-disabled', 'true');
    item.setAttribute('aria-level', String(level));
    item.setAttribute('aria-label', text);
    item.textContent = text;
    return item;
  }

  function entryItem(entry, level) {
    const item = document.createElement('li');
    item.setAttribute('role', 'treeitem');
    item.setAttribute('aria-level', String(level));
    item.setAttribute('aria-label', entry.name);
    item.tabIndex = -1;
    item.dataset.path = entry.path;
    item.dataset.type = entry.type;
    const row = document.createElement('div');
    row.className = 'tree-row';
    row.style.paddingLeft = `${(level - 1) * 14 + 4}px`;
    const mark = document.createElement('span');
    mark.className = 'tree-mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = entry.type === 'directory' ? '▸' : '';
    const label = document.createElement('span');
    label.className = 'tree-name';
    label.textContent = entry.name;
    label.title = entry.path;
    row.append(mark, label);
    item.append(row);
    if (entry.type === 'directory') item.setAttribute('aria-expanded', 'false');
    else if (sameFile(entry.path, current)) markCurrent(item, true);
    return item;
  }

  function markCurrent(item, on) {
    item.classList.toggle('current', on);
    if (on) item.setAttribute('aria-current', 'true'); else item.removeAttribute('aria-current');
  }

  /** フォルダの直下を、1回だけ読み、`parent`（ツリーの入れ物、または、フォルダの項目）に並べる。 */
  async function load(directory, parent, level) {
    const mine = generation;
    const group = parent === container ? container : document.createElement('ul');
    if (parent !== container) group.setAttribute('role', 'group');
    let result;
    try {
      result = await listDirectory(directory);
    } catch {
      result = { ok: false, message: 'フォルダを読めません' };
    }
    if (mine !== generation) return null;   // 読んでいる間に、別のフォルダへ替わった
    const items = !result.ok ? [messageItem(result.message ?? 'フォルダを読めません', level)]
      : result.entries.length === 0 ? [messageItem('（開けるファイルがありません）', level)]
      : result.entries.map((entry) => entryItem(entry, level));
    group.append(...items);
    if (parent !== container) parent.append(group);
    // 章の一覧（#373）は、見出しを、最初から開いておく（フォルダのように、1つずつ開かせない）
    if (autoExpand()) for (const item of items) if (item.dataset?.type === 'directory') void expand(item);
    return group;
  }

  async function expand(item) {
    if (item.dataset.type !== 'directory' || item.getAttribute('aria-expanded') === 'true') return;
    item.setAttribute('aria-expanded', 'true');
    item.firstElementChild.firstElementChild.textContent = '▾';
    if (item.dataset.loaded === 'true' || item.dataset.loading === 'true') return;
    item.dataset.loading = 'true';
    item.setAttribute('aria-busy', 'true');
    const group = await load(item.dataset.path, item, Number(item.getAttribute('aria-level')) + 1);
    item.removeAttribute('aria-busy');
    delete item.dataset.loading;
    if (group) item.dataset.loaded = 'true';
  }

  function collapse(item) {
    if (item.getAttribute('aria-expanded') !== 'true') return;
    item.setAttribute('aria-expanded', 'false');
    item.firstElementChild.firstElementChild.textContent = '▸';
  }

  function activate(item) {
    if (item.getAttribute('aria-disabled') === 'true') return;
    if (item.dataset.type === 'directory') {
      if (item.getAttribute('aria-expanded') === 'true') collapse(item); else void expand(item);
    } else {
      openFile(item.dataset.path);
    }
  }

  const itemOf = (target) => target.closest?.('[role="treeitem"]');

  container.addEventListener('click', (event) => {
    const item = itemOf(event.target);
    // 入れ子の項目は、親のliの中にあるため、いちばん内側（クリックした行）の項目だけを扱う
    if (!item || !event.target.closest('.tree-row') || event.target.closest('.tree-row').parentElement !== item) return;
    focusItem(item);
    activate(item);
  });

  container.addEventListener('keydown', (event) => {
    const item = itemOf(event.target);
    if (!item || event.altKey || event.ctrlKey || event.metaKey) return;
    const items = visibleItems();
    const index = items.indexOf(item);
    const isDirectory = item.dataset.type === 'directory';
    let handled = true;
    switch (event.key) {
      case 'ArrowDown': if (index < items.length - 1) focusItem(items[index + 1]); break;
      case 'ArrowUp': if (index > 0) focusItem(items[index - 1]); break;
      case 'Home': focusItem(items[0]); break;
      case 'End': focusItem(items.at(-1)); break;
      case 'ArrowRight':
        if (isDirectory && item.getAttribute('aria-expanded') !== 'true') void expand(item);
        else if (isDirectory && index < items.length - 1) focusItem(items[index + 1]);
        break;
      case 'ArrowLeft': {
        if (isDirectory && item.getAttribute('aria-expanded') === 'true') collapse(item);
        else {
          const parent = item.parentElement?.closest('[role="treeitem"]');
          if (parent) focusItem(parent);
        }
        break;
      }
      case 'Enter': case ' ': activate(item); break;
      default: handled = false;
    }
    if (handled) event.preventDefault();
  });

  /** 今開いているファイルを、ハイライトする（ツリーに無いファイルのときは、どれもハイライトしない）。 */
  function setCurrent(file) {
    current = file ?? null;
    for (const item of container.querySelectorAll('[role="treeitem"][data-type="file"]')) markCurrent(item, sameFile(item.dataset.path, current));
  }

  /** ツリーのルートのフォルダを替える。同じフォルダなら、何もしない（開いたフォルダは、展開の状態を保つ）。 */
  async function setRoot(directory, version = 0) {
    if ((directory ?? null) === root && version === rootVersion) return;
    root = directory ?? null;
    rootVersion = version;
    generation += 1;
    container.textContent = '';
    container.hidden = root === null;
    if (root === null) return;
    const group = await load(root, container, 1);
    const first = group && container.querySelector('[role="treeitem"]');
    if (first) first.tabIndex = 0;   // Tabで、ツリーへ入れるように、先頭の項目を、フォーカスの入口にする
  }

  return { setRoot, setCurrent };
}
