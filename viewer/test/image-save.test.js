'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const {
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
} = require('../src/image-save');

describe('isSvgUrl', () => {
  test('detects .svg in file and web URLs', () => {
    assert.equal(isSvgUrl('file:///path/to/diagram.svg'), true);
    assert.equal(isSvgUrl('https://example.com/icon.svg?v=1'), true);
    assert.equal(isSvgUrl('obunzu://doc/cache/hash.svg#id'), true);
  });

  test('detects data:image/svg+xml URLs', () => {
    assert.equal(isSvgUrl('data:image/svg+xml;utf8,<svg></svg>'), true);
    assert.equal(isSvgUrl('data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='), true);
  });

  test('returns false for non-svg URLs', () => {
    assert.equal(isSvgUrl('file:///path/to/photo.png'), false);
    assert.equal(isSvgUrl('https://example.com/logo.jpg'), false);
    assert.equal(isSvgUrl('data:image/png;base64,...'), false);
    assert.equal(isSvgUrl(''), false);
    assert.equal(isSvgUrl(null), false);
  });
});

describe('sanitizeFilename', () => {
  test('replaces invalid characters with hyphens and trims', () => {
    assert.equal(sanitizeFilename('my <diagram>: "v1" / test?'), 'my-diagram-v1-test');
    assert.equal(sanitizeFilename('  ---leading-and-trailing---  '), 'leading-and-trailing');
    assert.equal(sanitizeFilename('multiple    spaces   and---dashes'), 'multiple-spaces-and-dashes');
    assert.equal(sanitizeFilename(''), '');
    assert.equal(sanitizeFilename(null), '');
  });
});

describe('isDiagramCacheBasename', () => {
  test('identifies hex hashes and generator cache prefixes', () => {
    assert.equal(isDiagramCacheBasename('00e3e88678293481.svg'), true);
    assert.equal(isDiagramCacheBasename('c7f938d2a1b4c6e8.svg'), true);
    assert.equal(isDiagramCacheBasename('mermaid_00e3e88678293481.svg'), true);
    assert.equal(isDiagramCacheBasename('plantuml_12345678.svg'), true);
    assert.equal(isDiagramCacheBasename('d2_abcdef01.svg'), true);
    assert.equal(isDiagramCacheBasename('timeliney_abcdef01.svg'), true);
    assert.equal(isDiagramCacheBasename('finite_abcdef01.svg'), true);
  });

  test('does not match descriptive human filenames', () => {
    assert.equal(isDiagramCacheBasename('architecture-diagram.svg'), false);
    assert.equal(isDiagramCacheBasename('system-overview.png'), false);
    assert.equal(isDiagramCacheBasename('icon.svg'), false);
  });
});

describe('suggestedImageFilename', () => {
  test('preserves human-readable filename from URL', () => {
    const filename = suggestedImageFilename({
      srcURL: 'file:///docs/architecture-overview.svg',
      altText: 'architecture',
      documentFile: '/work/spec.md',
      format: 'svg',
    });
    assert.equal(filename, 'architecture-overview.svg');
  });

  test('changes extension when format is different', () => {
    const filename = suggestedImageFilename({
      srcURL: 'file:///docs/architecture-overview.svg',
      altText: 'architecture',
      documentFile: '/work/spec.md',
      format: 'png',
    });
    assert.equal(filename, 'architecture-overview.png');
  });

  test('falls back to altText when URL is a diagram cache hash', () => {
    const filename = suggestedImageFilename({
      srcURL: 'file:///cache/mermaid_00e3e88678293481.svg',
      altText: 'mermaid diagram',
      documentFile: '/work/spec.md',
      format: 'svg',
    });
    assert.equal(filename, 'mermaid-diagram.svg');
  });

  test('falls back to document name when altText is empty', () => {
    const filename = suggestedImageFilename({
      srcURL: 'file:///cache/00e3e88678293481.svg',
      altText: '',
      documentFile: '/work/database-spec.md',
      format: 'png',
    });
    assert.equal(filename, 'database-spec-diagram.png');
  });

  test('falls back to diagram.<format> when no context is available', () => {
    const filename = suggestedImageFilename({
      srcURL: 'file:///cache/00e3e88678293481.svg',
      altText: '',
      documentFile: null,
      format: 'svg',
    });
    assert.equal(filename, 'diagram.svg');
  });

  test('data: URL ignores base64 payload and falls back to altText or document name', () => {
    const base64 = Buffer.from('<svg></svg>').toString('base64');
    const filename = suggestedImageFilename({
      srcURL: `data:image/svg+xml;base64,${base64}`,
      altText: 'mermaid diagram',
      documentFile: '/work/spec.md',
      format: 'png',
    });
    assert.equal(filename, 'mermaid-diagram.png');
  });
});

describe('imageSaveDirectory', () => {
  const statOf = (dirs) => (p) => ({ isDirectory: () => dirs.includes(p) });
  const docFile = path.resolve(path.sep, 'work', 'docs', 'readme.md');
  const docDir = path.dirname(docFile);
  const lastDir = path.resolve(path.sep, 'saved', 'pics');
  const downloads = path.resolve(path.sep, 'users', 'me', 'Downloads');

  test('document directory is preferred if document is open', () => {
    const statSync = statOf([lastDir, docDir, downloads]);
    const dir = imageSaveDirectory({ lastDirectory: lastDir, documentFile: docFile, defaultFallback: downloads, statSync });
    assert.equal(dir, docDir);
  });

  test('lastDirectory is used when no document file is open', () => {
    const statSync = statOf([lastDir, downloads]);
    const dir = imageSaveDirectory({ lastDirectory: lastDir, documentFile: null, defaultFallback: downloads, statSync });
    assert.equal(dir, lastDir);
  });

  test('fallback is used when neither document nor lastDirectory exists', () => {
    const statSync = statOf([downloads]);
    const dir = imageSaveDirectory({ lastDirectory: null, documentFile: null, defaultFallback: downloads, statSync });
    assert.equal(dir, downloads);
  });
});

describe('imageSaveFilters', () => {
  test('svg format includes only SVG and all files', () => {
    const filters = imageSaveFilters('svg');
    assert.equal(filters.length, 2);
    assert.equal(filters[0].extensions[0], 'svg');
    assert.equal(filters[1].extensions[0], '*');
  });

  test('png format includes only PNG and all files', () => {
    const filters = imageSaveFilters('png');
    assert.equal(filters.length, 2);
    assert.equal(filters[0].extensions[0], 'png');
    assert.equal(filters[1].extensions[0], '*');
  });

  test('other formats include format and all files', () => {
    const filters = imageSaveFilters('jpg');
    assert.equal(filters[0].extensions[0], 'jpg');
    assert.equal(filters.at(-1).extensions[0], '*');
  });
});

describe('parseSvgDimensions', () => {
  test('extracts width and height from viewBox', () => {
    const svg = '<svg viewBox="0 0 1200 800" xmlns="http://www.w3.org/2000/svg"></svg>';
    assert.deepEqual(parseSvgDimensions(svg), { width: 1200, height: 800 });
  });

  test('handles fractional viewBox coordinates', () => {
    const svg = '<svg viewBox="0 0 269.65 342.1" width="100%"></svg>';
    assert.deepEqual(parseSvgDimensions(svg), { width: 270, height: 342 });
  });

  test('extracts width and height attributes when no viewBox', () => {
    const svg = '<svg width="640px" height="480px"></svg>';
    assert.deepEqual(parseSvgDimensions(svg), { width: 640, height: 480 });
  });

  test('falls back to default 800x600 for missing or invalid dimensions', () => {
    assert.deepEqual(parseSvgDimensions('<svg></svg>'), { width: 800, height: 600 });
    assert.deepEqual(parseSvgDimensions(''), { width: 800, height: 600 });
    assert.deepEqual(parseSvgDimensions(null), { width: 800, height: 600 });
  });
});

describe('calculateRasterDimensions', () => {
  test('applies 2x scaling by default', () => {
    assert.deepEqual(calculateRasterDimensions({ width: 300, height: 200 }), { width: 600, height: 400 });
  });

  test('caps raster dimensions at maxDimension preserving aspect ratio', () => {
    const dims = calculateRasterDimensions({ width: 3000, height: 2000 }, { maxDimension: 4000, scale: 2 });
    // 3000*2 = 6000 > 4000 -> scale down by 4000/6000 = 2/3 -> 4000 x 2667
    assert.equal(dims.width, 4000);
    assert.equal(dims.height, 2667);
  });
});

describe('fetchImageData', () => {
  test('reads local files via readFile', async () => {
    const mockFile = path.resolve(path.sep, 'test', 'image.svg');
    const mockUrl = require('node:url').pathToFileURL(mockFile).toString();
    const readFile = async (p) => Buffer.from(`read: ${p}`);
    const data = await fetchImageData(mockUrl, { readFile });
    assert.equal(data.toString(), `read: ${mockFile}`);
  });

  test('decodes base64 data URLs', async () => {
    const base64 = Buffer.from('<svg></svg>').toString('base64');
    const data = await fetchImageData(`data:image/svg+xml;base64,${base64}`);
    assert.equal(data.toString(), '<svg></svg>');
  });

  test('decodes URI-encoded data URLs', async () => {
    const data = await fetchImageData('data:image/svg+xml;utf8,%3Csvg%3E%3C/svg%3E');
    assert.equal(data.toString(), '<svg></svg>');
  });

  test('handles non-base64 data URLs with unescaped % without throwing', async () => {
    const data = await fetchImageData('data:image/svg+xml,<svg><text>50%</text></svg>');
    assert.equal(data.toString(), '<svg><text>50%</text></svg>');
  });

  test('fetches from custom protocol (#260) or http via netFetch', async () => {
    const mockFetch = async (url) => ({
      ok: true,
      status: 200,
      async arrayBuffer() {
        return new TextEncoder().encode(`fetched: ${url}`).buffer;
      },
    });
    const data = await fetchImageData('obunzu://doc/cache/hash.svg', { netFetch: mockFetch });
    assert.equal(data.toString(), 'fetched: obunzu://doc/cache/hash.svg');
  });

  test('throws on fetch failure', async () => {
    const mockFetch = async () => ({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    });
    await assert.rejects(
      () => fetchImageData('obunzu://doc/missing.svg', { netFetch: mockFetch }),
      /404 Not Found/
    );
  });
});

describe('rasterizeSvg', () => {
  test('creates hidden window with CSP and captures page', async () => {
    let capturedOptions = null;
    let windowCreated = false;
    let destroyed = false;
    let loadedUrl = null;

    const fakeWindow = {
      destroyed: false,
      async loadURL(u) { loadedUrl = u; },
      isDestroyed() { return destroyed; },
      destroy() { destroyed = true; },
      webContents: {
        async executeJavaScript() {},
        async capturePage(opts) {
          capturedOptions = opts;
          return { toPNG: () => Buffer.from('FAKE_PNG') };
        },
      },
    };

    const createWindow = (opts) => {
      windowCreated = true;
      assert.equal(opts.show, false);
      assert.equal(opts.transparent, true);
      return fakeWindow;
    };

    const png = await rasterizeSvg('<svg viewBox="0 0 400 300"></svg>', {
      createWindow,
      scale: 2,
    });

    assert.equal(windowCreated, true);
    assert.equal(destroyed, true);
    assert.match(loadedUrl, /^data:text\/html/);
    const decodedHtml = decodeURIComponent(loadedUrl.replace('data:text/html;charset=utf-8,', ''));
    assert.match(decodedHtml, /Content-Security-Policy/);
    assert.match(decodedHtml, /<img src="data:image\/svg\+xml;base64,/);
    assert.deepEqual(capturedOptions, { x: 0, y: 0, width: 800, height: 600 });
    assert.equal(png.toString(), 'FAKE_PNG');
  });
});

describe('buildImageContextMenuTemplate', () => {
  test('returns SVG and PNG save options for SVG image', () => {
    const calls = [];
    const onSave = (p, fmt) => calls.push(fmt);
    const template = buildImageContextMenuTemplate({ srcURL: 'file:///cache/diagram.svg', mediaType: 'image' }, { onSave });
    assert.equal(template.length, 2);
    assert.equal(template[0].label, '画像（SVG）を保存…');
    assert.equal(template[1].label, '画像（PNG）を保存…');

    template[0].click();
    template[1].click();
    assert.deepEqual(calls, ['svg', 'png']);
  });

  test('returns single save option for non-SVG image', () => {
    const calls = [];
    const onSave = (p, fmt) => calls.push(fmt);
    const template = buildImageContextMenuTemplate({ srcURL: 'file:///images/photo.png', mediaType: 'image' }, { onSave });
    assert.equal(template.length, 1);
    assert.equal(template[0].label, '画像を保存…');

    template[0].click();
    assert.deepEqual(calls, ['auto']);
  });
});

describe('executeSaveImage', () => {
  const dummySvg = '<svg viewBox="0 0 100 100"></svg>';
  const validFileUrl = require('node:url').pathToFileURL(path.resolve('test.svg')).toString();

  test('returns canceled when user cancels save dialog', async () => {
    const showSaveDialog = async () => ({ canceled: true, filePath: null });
    const result = await executeSaveImage({ srcURL: validFileUrl }, 'svg', { showSaveDialog });
    assert.deepEqual(result, { saved: false, canceled: true });
  });

  test('saves SVG file when format is svg', async () => {
    const written = [];
    const showSaveDialog = async () => ({ canceled: false, filePath: path.resolve('/saved/my-diagram.svg') });
    const readFile = async () => Buffer.from(dummySvg);
    const writeFile = async (p, d) => written.push({ path: p, data: d.toString() });

    const result = await executeSaveImage({ srcURL: validFileUrl, altText: 'my-diagram' }, 'svg', {
      showSaveDialog,
      readFile,
      writeFile,
    });

    assert.equal(result.saved, true);
    assert.equal(written.length, 1);
    assert.equal(written[0].path, path.resolve('/saved/my-diagram.svg'));
    assert.equal(written[0].data, dummySvg);
  });

  test('rasterizes SVG to PNG when format is png', async () => {
    const written = [];
    const showSaveDialog = async () => ({ canceled: false, filePath: path.resolve('/saved/my-diagram.png') });
    const readFile = async () => Buffer.from(dummySvg);
    const writeFile = async (p, d) => written.push({ path: p, data: d });

    const fakeWindow = {
      destroyed: false,
      async loadURL() {},
      isDestroyed() { return false; },
      destroy() {},
      webContents: {
        async capturePage() {
          return { toPNG: () => Buffer.from('RASTERIZED_PNG_DATA') };
        },
      },
    };
    const createWindow = () => fakeWindow;

    const result = await executeSaveImage({ srcURL: validFileUrl, altText: 'my-diagram' }, 'png', {
      showSaveDialog,
      readFile,
      writeFile,
      createWindow,
    });

    assert.equal(result.saved, true);
    assert.equal(written.length, 1);
    assert.equal(written[0].path, path.resolve('/saved/my-diagram.png'));
    assert.equal(written[0].data.toString(), 'RASTERIZED_PNG_DATA');
  });
});

