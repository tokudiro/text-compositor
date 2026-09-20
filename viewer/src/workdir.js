'use strict';
// 変換したファイル（HTMLと、図のSVGのキャッシュ）の置き場所（#258）。
//
// Viewerは閲覧専用のため、既定では、原稿のフォルダに何も書かず、アプリの領域（ユーザーのキャッシュ領域）に置く。
// 設定で「原稿の隣」を選ぶと、従来どおり、原稿の隣の`.text-compositor/`に置く（ワーカーの既定の動作）。
//
// アプリの領域は、Pythonの`platformdirs`が使うキャッシュ領域（text_compositor/deps.pyの_user_cache_dir。フォントや
// 図のツールの取得先）の下の`viewer/`にする。設定画面の「キャッシュを削除」は、この`viewer/`の中の`html/`と`cache/`だけを
// 消す（フォント・JRE・図のツールなど、時間のかかる取得物は、消さない）。

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HTML_DIR = 'html';     // 変換したHTML（原稿1つにつき1ファイル）
const CACHE_DIR = 'cache';   // 図のSVG（内容のハッシュがキー。原稿をまたいで共有する）
const MANAGED = Object.freeze([HTML_DIR, CACHE_DIR]);

/** アプリの領域。Pythonのキャッシュ領域（platformdirsの`user_cache_dir("text-compositor")`）と同じ親の下の`viewer/`。 */
function cacheRoot({ platform = process.platform, env = process.env, home = os.homedir() } = {}) {
  let base;
  if (platform === 'win32') base = path.win32.join(env.LOCALAPPDATA || path.win32.join(home, 'AppData', 'Local'), 'text-compositor', 'Cache');
  else if (platform === 'darwin') base = path.posix.join(home, 'Library', 'Caches', 'text-compositor');
  else base = path.posix.join(env.XDG_CACHE_HOME || path.posix.join(home, '.cache'), 'text-compositor');
  const join = platform === 'win32' ? path.win32.join : path.posix.join;
  return join(base, 'viewer');
}

/** 原稿のパスから決まる、HTMLのファイル名。別のフォルダの同名の原稿が、衝突しないように、パスのハッシュにする。 */
function htmlFileName(file, platform = process.platform) {
  // Windowsは、パスの大文字・小文字を区別しない（同じファイルが、別のファイルにならないようにする）
  const key = platform === 'win32' ? file.toLowerCase() : file;
  return `${crypto.createHash('sha256').update(key).digest('hex').slice(0, 16)}.html`;
}

/** 原稿の隣の`.text-compositor/`に、書き込めるか（作れるか）。ワーカーは、ここに書くため、先に確かめる。 */
function isWritableBeside(file, fsApi = fs) {
  const directory = path.join(path.dirname(file), '.text-compositor');
  try {
    fsApi.mkdirSync(directory, { recursive: true });
    fsApi.accessSync(directory, fs.constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * ワーカー（render_html）に渡す、置き場所の引数を決める。
 * - 'app'（既定）: HTMLと図のキャッシュを、アプリの領域に置く。原稿のフォルダには、何も書かない。
 * - 'beside': 引数なし（ワーカーの既定の、原稿の隣の`.text-compositor/`）。書き込めない場所の原稿は、
 *   開けないより、開けるほうがよいため、アプリの領域に切り替える（fellBack: true）。
 * @returns {{params: {output?: string, cache_dir?: string}, fellBack: boolean}}
 */
function workLocation(mode, file, { root = cacheRoot(), fsApi = fs, platform = process.platform } = {}) {
  const inApp = () => {
    const join = platform === 'win32' ? path.win32.join : path.posix.join;
    return { output: join(root, HTML_DIR, htmlFileName(file, platform)), cache_dir: join(root, CACHE_DIR) };
  };
  if (mode === 'beside') {
    return isWritableBeside(file, fsApi) ? { params: {}, fellBack: false } : { params: inApp(), fellBack: true };
  }
  return { params: inApp(), fellBack: false };
}

async function directorySize(directory) {
  let bytes = 0;
  let files = 0;
  let entries;
  try {
    entries = await fs.promises.readdir(directory, { withFileTypes: true });
  } catch {
    return { bytes, files };   // まだ無い（何も作っていない）
  }
  for (const entry of entries) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      const inner = await directorySize(full);
      bytes += inner.bytes;
      files += inner.files;
    } else if (entry.isFile()) {
      try {
        bytes += (await fs.promises.stat(full)).size;
        files += 1;
      } catch { /* 数えている間に消えたファイルは、無視する */ }
    }
  }
  return { bytes, files };
}

/** アプリの領域の、使用量（バイト数・ファイル数）。 */
async function cacheUsage(root = cacheRoot()) {
  let bytes = 0;
  let files = 0;
  for (const name of MANAGED) {
    const usage = await directorySize(path.join(root, name));
    bytes += usage.bytes;
    files += usage.files;
  }
  return { bytes, files };
}

/**
 * アプリの領域の、HTMLと図のキャッシュを削除する。消すのは、`html/`と`cache/`だけ（誤って、別のフォルダを消さないように、
 * 名前が`viewer`のフォルダだけを対象にする）。原稿の隣にできた`.text-compositor/`は、利用者のフォルダのため、消さない。
 * @returns {Promise<{bytes: number, files: number}>} 消した量
 */
async function clearCache(root = cacheRoot()) {
  if (path.basename(root) !== 'viewer') throw new Error(`Refusing to clear an unexpected folder: ${root}`);
  const before = await cacheUsage(root);
  for (const name of MANAGED) await fs.promises.rm(path.join(root, name), { recursive: true, force: true });
  return before;
}

module.exports = { CACHE_DIR, HTML_DIR, cacheRoot, cacheUsage, clearCache, htmlFileName, isWritableBeside, workLocation };
