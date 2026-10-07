'use strict';
// 右クリックのメニューの、ファイル・フォルダ・タブの項目（#428）。サイドバー・タブ・本文のリンクで、同じ項目を共用する。Electronなしで、テストできる。

const REVEAL_LABEL = 'エクスプローラーで表示';

/**
 * サイドバーの、ファイル・フォルダの項目。並びは、パスをコピー・エクスプローラーで表示・新しいタブで開く。
 * 「新しいタブで開く」は、ファイルで、設定「複数のタブ」がオンのときだけ。パスが無い項目（章の一覧の見出し）には、項目を出さない（空の配列）。
 * @param {{filePath?: string|null, isDirectory?: boolean, canOpenInNewTab?: boolean, onCopy?: Function, onReveal?: Function, onOpenInNewTab?: Function}} options
 */
function buildPathContextMenuTemplate({ filePath, isDirectory = false, canOpenInNewTab = false, onCopy, onReveal, onOpenInNewTab } = {}) {
  if (typeof filePath !== 'string' || filePath === '') return [];
  const items = [
    { label: 'パスをコピー', click: () => onCopy?.(filePath) },
    { label: REVEAL_LABEL, click: () => onReveal?.(filePath, isDirectory) },
  ];
  if (!isDirectory && canOpenInNewTab) items.push({ label: '新しいタブで開く', click: () => onOpenInNewTab?.(filePath) });
  return items;
}

/**
 * タブの項目。閉じる・他のタブを閉じる（他にタブがあるときだけ有効）、区切り線、パスをコピー・エクスプローラーで表示（ファイルがあるときだけ）。
 * @param {{file?: string|null, tabCount?: number, onClose?: Function, onCloseOthers?: Function, onCopy?: Function, onReveal?: Function}} options
 */
function buildTabContextMenuTemplate({ file, tabCount = 1, onClose, onCloseOthers, onCopy, onReveal } = {}) {
  const items = [
    { label: '閉じる', click: () => onClose?.() },
    { label: '他のタブを閉じる', enabled: tabCount > 1, click: () => onCloseOthers?.() },
  ];
  if (typeof file === 'string' && file !== '') {
    items.push(
      { type: 'separator' },
      { label: 'パスをコピー', click: () => onCopy?.(file) },
      { label: REVEAL_LABEL, click: () => onReveal?.(file, false) },
    );
  }
  return items;
}

/**
 * サイドバーの項目として、右クリックを受け付けるパスか。画面からの値のため、信用しない。
 * 章の一覧（プロジェクトモード）は、一覧に載っているファイルだけ（見出しの「フォルダ」は、実体がない）。フォルダのツリーは、ルートの中だけ。
 * @param {{filePath: unknown, type: unknown, showFileTree: boolean, tree: {kind: string|null, root: string|null}, projectFiles?: Set<string>|null,
 *          isAbsolute: (p: string) => boolean, isInside: (root: string, p: string) => boolean}} options
 */
function isSidebarPath({ filePath, type, showFileTree, tree, projectFiles, isAbsolute, isInside }) {
  if (typeof filePath !== 'string' || !isAbsolute(filePath) || (type !== 'file' && type !== 'directory')) return false;
  if (!showFileTree) return false;
  if (tree.kind === 'project') return type === 'file' && projectFiles?.has(filePath) === true;
  return tree.kind === 'folder' && isInside(tree.root, filePath);
}

module.exports = { buildPathContextMenuTemplate, buildTabContextMenuTemplate, isSidebarPath, REVEAL_LABEL };
