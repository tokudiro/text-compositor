'use strict';
// アプリケーションのアイコン（#193）を、元のSVG（assets/icon.svg）から書き出す。
//   npm run build-icons        （中身は `electron scripts/build-icons.js`）
//
// 作るもの: assets/icon.ico（16〜256 px）と assets/icon.png（256 px。ウィンドウ・Linux用）。
// SVGの描画に、すでに依存しているElectron（Chromium）を使う。画像処理の依存パッケージを、増やさないため。
// 表示の倍率を1に固定するのは、高DPIの画面で、指定より大きい画像が撮れるのを防ぐため。

const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow } = require('electron');

app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.commandLine.appendSwitch('high-dpi-support', '1');

const ASSETS = path.join(__dirname, '..', 'assets');
const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256];
const PNG_SIZE = 256;

/** 最大サイズのウィンドウを1つだけ作り、SVGの表示サイズを変えながら、左上の正方形を撮る。 */
async function createCanvas(svg) {
  const maxSize = Math.max(...ICO_SIZES, PNG_SIZE);
  const win = new BrowserWindow({
    show: false,
    width: maxSize,
    height: maxSize,
    useContentSize: true,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
  });
  const html = `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:transparent;overflow:hidden}
    svg{display:block}</style>${svg}`;
  await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  return win;
}

async function render(win, size) {
  await win.webContents.executeJavaScript(
    `(() => { const s = document.querySelector('svg'); s.style.width = '${size}px'; s.style.height = '${size}px'; })()`);
  await new Promise((resolve) => setTimeout(resolve, 100));
  const image = await win.webContents.capturePage({ x: 0, y: 0, width: size, height: size });
  const got = image.getSize();
  if (got.width !== size || got.height !== size) {
    throw new Error(`${size}px の画像が、${got.width}x${got.height} で撮れた`);
  }
  return image.toPNG();
}

/** PNGを埋め込んだICOを組み立てる（Windows Vista以降が読める形式）。 */
function buildIco(images) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  const directory = Buffer.alloc(16 * images.length);
  let offset = header.length + directory.length;
  images.forEach(({ size, png }, i) => {
    const at = i * 16;
    directory.writeUInt8(size >= 256 ? 0 : size, at);       // 幅（256は0で表す）
    directory.writeUInt8(size >= 256 ? 0 : size, at + 1);   // 高さ
    directory.writeUInt8(0, at + 2);                        // パレットの色数
    directory.writeUInt8(0, at + 3);
    directory.writeUInt16LE(1, at + 4);                     // プレーン数
    directory.writeUInt16LE(32, at + 6);                    // ビット数
    directory.writeUInt32LE(png.length, at + 8);
    directory.writeUInt32LE(offset, at + 12);
    offset += png.length;
  });
  return Buffer.concat([header, directory, ...images.map((image) => image.png)]);
}

async function main() {
  const svg = fs.readFileSync(path.join(ASSETS, 'icon.svg'), 'utf8').replace(/^<\?xml[^>]*>\s*/, '');
  const win = await createCanvas(svg);
  const images = [];
  for (const size of ICO_SIZES) images.push({ size, png: await render(win, size) });
  win.destroy();

  fs.writeFileSync(path.join(ASSETS, 'icon.ico'), buildIco(images));
  fs.writeFileSync(path.join(ASSETS, 'icon.png'), images.find((image) => image.size === PNG_SIZE).png);
  console.log(`assets/icon.ico（${ICO_SIZES.join('・')} px）と assets/icon.png（${PNG_SIZE} px）を書き出した`);
}

app.whenReady().then(main).then(() => app.quit(), (error) => {
  console.error(error);
  app.exit(1);
});
