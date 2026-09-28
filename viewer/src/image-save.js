'use strict';
// 画像（SVG/PNG）の保存・ダウンロード（#327）。
//
// Obunzuで表示される図（Mermaid・PlantUML・D2・Graphviz等）は、SVGとしてレンダリングされている。
// 右クリックのコンテキストメニューから、ベクターのままのSVG、または高解像度（2倍スケール・最大4096px）に
// ラスタライズしたPNGとして保存できる。
//
// PNG変換には、Electronに同梱のChromiumのオフスクリーン描画（BrowserWindow + capturePage）を利用し、
// 新たな依存ライブラリを追加しない。

const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');

/**
 * URLがSVG画像を指しているか判定する。
 * @param {string} url
 * @returns {boolean}
 */
function isSvgUrl(url) {
  if (typeof url !== 'string' || !url) return false;
  if (/^data:image\/svg\+xml/i.test(url)) return true;
  try {
    const parsed = new URL(url);
    return /\.svg$/i.test(parsed.pathname);
  } catch {
    return /\.svg(\?|#|$)/i.test(url);
  }
}

/**
 * ファイル名として使えない文字（Windows・POSIX共通）を安全なハイフンへ置換する。
 * @param {string} name
 * @returns {string}
 */
function sanitizeFilename(name) {
  if (typeof name !== 'string') return '';
  return name
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
    .trim();
}

/**
 * 文字列が16進数のハッシュ値（キャッシュのファイル名など）か判定する。
 * @param {string} str
 * @returns {boolean}
 */
function isHexHash(str) {
  return /^[0-9a-f]{8,}$/i.test(str);
}

/**
 * 図のキャッシュ名（例: `mermaid_00e3e88678293481.svg`, `c7f938d2a1.svg`）など、
 * 機械的なファイル名か判定する。
 * @param {string} basename
 * @returns {boolean}
 */
function isDiagramCacheBasename(basename) {
  const stem = basename.replace(/\.[^.]+$/, '');
  if (isHexHash(stem)) return true;
  if (/^(mermaid|plantuml|d2|graphviz|pikchr|svg|cetz|fletcher|timeliney)_[0-9a-f]{8,}$/i.test(stem)) return true;
  return false;
}

/**
 * 画像保存ダイアログの既定ファイル名を決める。
 * 1. URLのファイル名が意味のある名前（ハッシュでない）なら、それを優先する。
 * 2. ハッシュや空なら、画像のalt属性（例: "mermaid diagram"）をサニタイズして使う。
 * 3. altも無ければ、開いている文書のファイル名（例: "spec-diagram"）を使う。
 * 4. それも無ければ、"diagram" にフォールバックする。
 *
 * @param {{srcURL: string, altText?: string, documentFile?: string|null, format?: string}} options
 * @returns {string}
 */
function suggestedImageFilename({ srcURL, altText, documentFile, format = 'svg' }) {
  let urlBasename = '';
  try {
    const parsed = new URL(srcURL);
    urlBasename = path.basename(parsed.pathname);
  } catch {
    urlBasename = path.basename(String(srcURL || ''));
  }

  const stemFromUrl = urlBasename ? urlBasename.replace(/\.[^.]+$/, '') : '';
  const isHashOrEmpty = !stemFromUrl || isDiagramCacheBasename(urlBasename);

  let baseName = '';
  if (!isHashOrEmpty) {
    baseName = sanitizeFilename(stemFromUrl);
  }

  if (!baseName && altText) {
    baseName = sanitizeFilename(altText);
  }

  if (!baseName && documentFile) {
    const docStem = path.basename(documentFile).replace(/\.[^.]+$/, '');
    baseName = sanitizeFilename(`${docStem}-diagram`);
  }

  if (!baseName) {
    baseName = 'diagram';
  }

  const ext = format.startsWith('.') ? format.slice(1) : format;
  return `${baseName}.${ext}`;
}

/**
 * フォルダが存在するか確認する。
 */
function isExistingDirectory(dir, statSync) {
  if (typeof dir !== 'string' || !dir) return false;
  try {
    return statSync(dir).isDirectory();
  } catch {
    return false;
  }
}

/**
 * 画像保存ダイアログの初期表示フォルダを決める。
 * 1. 同一セッション内で前回保存したフォルダ
 * 2. 開いている文書のフォルダ
 * 3. フォールバック（DownloadsまたはDocuments）
 *
 * @param {{lastDirectory?: string|null, documentFile?: string|null, defaultFallback?: string, statSync?: Function}} options
 * @returns {string|undefined}
 */
function imageSaveDirectory({ lastDirectory, documentFile, defaultFallback, statSync = fs.statSync } = {}) {
  if (isExistingDirectory(lastDirectory, statSync)) {
    return lastDirectory;
  }
  if (documentFile) {
    const docDir = path.dirname(documentFile);
    if (isExistingDirectory(docDir, statSync)) {
      return docDir;
    }
  }
  if (isExistingDirectory(defaultFallback, statSync)) {
    return defaultFallback;
  }
  return undefined;
}

/**
 * 保存ダイアログのフィルター一覧を返す。
 * @param {'svg'|'png'|string} format
 * @returns {Array<{name: string, extensions: string[]}>}
 */
function imageSaveFilters(format) {
  if (format === 'svg') {
    return [
      { name: 'SVG画像 (*.svg)', extensions: ['svg'] },
      { name: 'PNG画像 (*.png)', extensions: ['png'] },
      { name: 'すべてのファイル (*.*)', extensions: ['*'] },
    ];
  }
  if (format === 'png') {
    return [
      { name: 'PNG画像 (*.png)', extensions: ['png'] },
      { name: 'SVG画像 (*.svg)', extensions: ['svg'] },
      { name: 'すべてのファイル (*.*)', extensions: ['*'] },
    ];
  }
  const ext = format.startsWith('.') ? format.slice(1) : format;
  return [
    { name: '画像', extensions: [ext] },
    { name: 'すべてのファイル (*.*)', extensions: ['*'] },
  ];
}

/**
 * SVGのテキストから、描画サイズ（幅と高さ）を取り出す。
 * 1. viewBox="min-x min-y width height" があれば、その幅・高さを優先する。
 * 2. viewBoxが無ければ、width="..." および height="..." 属性を取り出す。
 * 3. どちらも無ければ、既定値（800x600）を返す。
 *
 * @param {string} svgText
 * @returns {{width: number, height: number}}
 */
function parseSvgDimensions(svgText) {
  if (typeof svgText !== 'string') return { width: 800, height: 600 };
  const vbMatch = svgText.match(/viewBox\s*=\s*["']\s*([-\d.]+)[,\s]+([-\d.]+)[,\s]+([-\d.]+)[,\s]+([-\d.]+)\s*["']/i);
  if (vbMatch) {
    const w = parseFloat(vbMatch[3]);
    const h = parseFloat(vbMatch[4]);
    if (w > 0 && h > 0) return { width: Math.round(w), height: Math.round(h) };
  }
  const wMatch = svgText.match(/width\s*=\s*["']\s*([-\d.]+)(px)?\s*["']/i);
  const hMatch = svgText.match(/height\s*=\s*["']\s*([-\d.]+)(px)?\s*["']/i);
  if (wMatch && hMatch) {
    const w = parseFloat(wMatch[1]);
    const h = parseFloat(hMatch[1]);
    if (w > 0 && h > 0) return { width: Math.round(w), height: Math.round(h) };
  }
  return { width: 800, height: 600 };
}

/**
 * SVGからPNGへラスタライズする際の出力サイズ（px）を計算する。
 * 既定で2倍スケールを適用し、最大サイズ（4096px）を超えないよう抑える。
 *
 * @param {{width: number, height: number}} dimensions
 * @param {{maxDimension?: number, scale?: number}} [options]
 * @returns {{width: number, height: number}}
 */
function calculateRasterDimensions(dimensions, { maxDimension = 4096, scale = 2 } = {}) {
  const w = Math.max(1, dimensions?.width || 800);
  const h = Math.max(1, dimensions?.height || 600);
  let targetW = Math.round(w * scale);
  let targetH = Math.round(h * scale);
  const maxSide = Math.max(targetW, targetH);
  if (maxSide > maxDimension) {
    const ratio = maxDimension / maxSide;
    targetW = Math.max(1, Math.round(targetW * ratio));
    targetH = Math.max(1, Math.round(targetH * ratio));
  }
  return { width: targetW, height: targetH };
}

/**
 * URL（file:, data:, または http:, https:, obunzu:）から画像データを取得する。
 * #260でカスタムプロトコル化された場合も、netFetch経由で同じように取得できる。
 *
 * @param {string} url
 * @param {{readFile?: Function, netFetch?: Function}} [options]
 * @returns {Promise<Buffer>}
 */
async function fetchImageData(url, { readFile = fs.promises.readFile, netFetch = null } = {}) {
  if (url.startsWith('file:')) {
    const filePath = fileURLToPath(url);
    return await readFile(filePath);
  }
  if (url.startsWith('data:')) {
    const commaIndex = url.indexOf(',');
    if (commaIndex === -1) throw new Error('不正なdata URLです');
    const header = url.slice(5, commaIndex);
    const data = url.slice(commaIndex + 1);
    if (header.includes(';base64')) {
      return Buffer.from(data, 'base64');
    }
    return Buffer.from(decodeURIComponent(data), 'utf8');
  }
  const fetcher = netFetch || (typeof fetch === 'function' ? fetch : null);
  if (!fetcher) throw new Error(`URLから画像を取得できません: ${url}`);
  const response = await fetcher(url);
  if (!response.ok) {
    throw new Error(`画像の取得に失敗しました (${response.status} ${response.statusText}): ${url}`);
  }
  const arrayBuffer = await response.arrayBuffer();
  return Buffer.from(arrayBuffer);
}

/**
 * SVGのテキストを、ElectronのChromiumオフスクリーン描画を用いてPNG画像（Buffer）へ変換する。
 *
 * @param {string} svgText
 * @param {{dimensions?: {width: number, height: number}, scale?: number, createWindow: Function, captureDelay?: number}} options
 * @returns {Promise<Buffer>}
 */
async function rasterizeSvg(svgText, { dimensions, scale = 2, createWindow, captureDelay = 60 } = {}) {
  const dims = dimensions || parseSvgDimensions(svgText);
  const { width, height } = calculateRasterDimensions(dims, { scale });
  const win = createWindow({
    show: false,
    width,
    height,
    useContentSize: true,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  try {
    const html = `<!doctype html><html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; overflow: hidden; background: transparent; }
  svg { display: block; width: ${width}px !important; height: ${height}px !important; max-width: none !important; }
</style>
</head><body>${svgText}</body></html>`;

    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
    if (captureDelay > 0) {
      await new Promise((resolve) => setTimeout(resolve, captureDelay));
    }
    const image = await win.webContents.capturePage({ x: 0, y: 0, width, height });
    return image.toPNG();
  } finally {
    if (win && !(typeof win.isDestroyed === 'function' && win.isDestroyed())) {
      win.destroy();
    }
  }
}

/**
 * 画像右クリック時のコンテキストメニューのテンプレートを生成する。
 * @param {{srcURL: string, mediaType: string}} params
 * @param {{onSave?: (params: object, format: string) => void}} handlers
 * @returns {Array<object>}
 */
function buildImageContextMenuTemplate(params, { onSave } = {}) {
  const isSvg = isSvgUrl(params?.srcURL);
  if (isSvg) {
    return [
      {
        label: '画像（SVG）を保存…',
        click: () => onSave?.(params, 'svg'),
      },
      {
        label: '画像（PNG）を保存…',
        click: () => onSave?.(params, 'png'),
      },
    ];
  }
  return [
    {
      label: '画像を保存…',
      click: () => onSave?.(params, 'auto'),
    },
  ];
}

/**
 * 画像の保存処理を実行する。
 *
 * @param {{srcURL: string, altText?: string}} params
 * @param {'svg'|'png'|'auto'} requestedFormat
 * @param {object} context
 * @returns {Promise<{saved: boolean, canceled?: boolean, filePath?: string, directory?: string}>}
 */
async function executeSaveImage(params, requestedFormat, {
  win,
  documentFile = null,
  lastDirectory = null,
  downloadsDirectory = null,
  showSaveDialog,
  readFile = fs.promises.readFile,
  writeFile = fs.promises.writeFile,
  netFetch = null,
  createWindow,
  statSync = fs.statSync,
} = {}) {
  const isSvg = isSvgUrl(params.srcURL);
  let format = requestedFormat;
  if (format === 'auto') {
    try {
      const ext = path.extname(new URL(params.srcURL).pathname).replace(/^\./, '');
      format = ext || 'png';
    } catch {
      format = 'png';
    }
  }

  const defaultFilename = suggestedImageFilename({
    srcURL: params.srcURL,
    altText: params.altText,
    documentFile,
    format,
  });

  const defaultFolder = imageSaveDirectory({
    lastDirectory,
    documentFile,
    defaultFallback: downloadsDirectory,
    statSync,
  });

  const defaultPath = defaultFolder ? path.join(defaultFolder, defaultFilename) : defaultFilename;
  const filters = imageSaveFilters(format);

  const result = await showSaveDialog(win, {
    title: '画像を保存',
    defaultPath,
    filters,
  });

  if (result.canceled || !result.filePath) return { saved: false, canceled: true };

  const chosenExt = path.extname(result.filePath).toLowerCase();
  const shouldSaveAsPng = chosenExt === '.png' || (format === 'png' && chosenExt !== '.svg');

  const rawData = await fetchImageData(params.srcURL, {
    readFile,
    netFetch,
  });

  if (isSvg && shouldSaveAsPng) {
    const svgText = rawData.toString('utf8');
    const pngBuffer = await rasterizeSvg(svgText, {
      createWindow,
      scale: 2,
    });
    await writeFile(result.filePath, pngBuffer);
  } else {
    await writeFile(result.filePath, rawData);
  }

  return {
    saved: true,
    filePath: result.filePath,
    directory: path.dirname(result.filePath),
  };
}

module.exports = {
  isSvgUrl,
  sanitizeFilename,
  isDiagramCacheBasename,
  suggestedImageFilename,
  imageSaveDirectory,
  imageSaveFilters,
  parseSvgDimensions,
  calculateRasterDimensions,
  fetchImageData,
  rasterizeSvg,
  buildImageContextMenuTemplate,
  executeSaveImage,
};
