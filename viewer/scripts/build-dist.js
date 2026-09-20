'use strict';
// Windows向けの配布物（ZIP）を作る（#168）。
//   node scripts/build-dist.js
//
// 作るもの: dist/Obunzu-<バージョン>-win-x64.zip（Pythonのインストールが要らない、展開して使うポータブル版）。
// 中身: Electronのアプリ（obunzu.exe）と、その隣の python-embed/（組込版Python + 必要最小限のパッケージ +
//       text_compositor）と、licenses/（サードパーティのライセンス表記）。
//
// 手順:
//   1. @electron/packagerで、Electronのアプリを作る（アイコン・バージョン情報・asar）。
//   2. python.orgの組込版Pythonを取得して（SHA256を確認）、python-embed/に展開する。
//   3. dist-requirements.txtのパッケージを、ビルド用のPythonのpipで、組込版のsite-packagesへ入れる
//      （--platform win_amd64・cp314・wheelのみ。ビルドするPythonの版に、依存しない）。
//   4. text_compositorのパッケージを、site-packagesへ写す。バイトコードを作る（起動を速くするため）。
//   5. ライセンス表記（licenses/）を作る。
//   6. ZIPにして、同梱物ごとのサイズを表示する。
//
// ビルド用のPython: 環境変数 PYTHON_FOR_BUILD、なければ TEXT_COMPOSITOR_PYTHON、なければ PATHの python。
// 取得したファイルは dist/.cache/ に置き、2回目以降は再利用する。

const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');
const path = require('node:path');

const viewerDir = path.resolve(__dirname, '..');
const repoDir = path.resolve(viewerDir, '..');
const pkg = require(path.join(viewerDir, 'package.json'));

// 組込版Python。版は固定し、SHA256を確認する（python.orgのftpには、SHA256の一覧がないため、初回に取得して、記録した値）。
const PYTHON = {
  version: '3.14.7',
  url: 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip',
  sha256: 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15',
  tag: '314',
};

// Apache-2.0の全文。組込版Pythonに含まれるOpenSSL（libcrypto・libssl）のライセンスが、Apache-2.0のため、同梱する。
const APACHE = {
  url: 'https://www.apache.org/licenses/LICENSE-2.0.txt',
  sha256: 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
};

const dist = path.join(viewerDir, 'dist');
const cache = path.join(dist, '.cache');
const stage = path.join(dist, 'stage');
const releaseName = `Obunzu-${pkg.version}-win-x64`;

function log(message) { console.log(`\n== ${message}`); }

// zipの展開・作成に使うtar。Windows標準のbsdtar（System32のtar.exe）を、明示して使う。PATHの先頭に、Gitに付属の
// GNU tarがあると（GitHub ActionsのWindowsのランナーなど）、zipを扱えず、`C:`をホスト名と解釈して失敗するため（#172）。
const TAR = process.platform === 'win32' && process.env.SystemRoot
  ? path.join(process.env.SystemRoot, 'System32', 'tar.exe')
  : 'tar';

function run(file, args, options = {}) {
  return execFileSync(file, args, { stdio: 'inherit', ...options });
}

function download(url, file, attempts = 3) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      https.get(url, (response) => {
        if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
          response.resume();
          return download(response.headers.location, file, attempts).then(resolve, reject);
        }
        if (response.statusCode !== 200) {
          response.resume();
          return n < attempts ? setTimeout(() => attempt(n + 1), 1000 * n) : reject(new Error(`HTTP ${response.statusCode}: ${url}`));
        }
        const out = fs.createWriteStream(`${file}.part`);
        response.pipe(out);
        out.on('finish', () => out.close(() => { fs.renameSync(`${file}.part`, file); resolve(); }));
        out.on('error', reject);
      }).on('error', (error) => (n < attempts ? setTimeout(() => attempt(n + 1), 1000 * n) : reject(error)));
    };
    attempt(1);
  });
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function sizeOf(target) {
  const stat = fs.statSync(target);
  if (!stat.isDirectory()) return stat.size;
  return fs.readdirSync(target).reduce((sum, name) => sum + sizeOf(path.join(target, name)), 0);
}

const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;

/** 取得して、SHA256を確認する。取得済み（キャッシュ）なら、再取得しない。 */
async function fetchVerified(item, label) {
  fs.mkdirSync(cache, { recursive: true });
  const file = path.join(cache, item.file || path.basename(item.url));
  if (!fs.existsSync(file)) {
    console.log(`取得: ${item.url}`);
    await download(item.url, file);
  }
  const actual = sha256(file);
  if (actual !== item.sha256) {
    fs.rmSync(file, { force: true });
    throw new Error(`${label}のSHA256が一致しません: 期待 ${item.sha256}、実際 ${actual}`);
  }
  return file;
}

function buildPythonEnvironment(appDir, embedZip) {
  const embed = path.join(appDir, 'python-embed');
  fs.mkdirSync(embed, { recursive: true });
  run(TAR, ['-xf', embedZip, '-C', embed]);

  // sys.pathは、._pthで決まる（PYTHONPATHなどの環境変数は、無視される）。site-packagesを加える。
  const sitePackages = path.join(embed, 'Lib', 'site-packages');
  fs.mkdirSync(sitePackages, { recursive: true });
  fs.writeFileSync(path.join(embed, `python${PYTHON.tag}._pth`),
    [`python${PYTHON.tag}.zip`, '.', 'Lib\\site-packages', ''].join('\r\n'));

  const hostPython = process.env.PYTHON_FOR_BUILD || process.env.TEXT_COMPOSITOR_PYTHON || 'python';
  run(hostPython, ['-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--no-compile',
    '--target', sitePackages, '--only-binary=:all:', '--platform', 'win_amd64',
    '--python-version', `${PYTHON.version.split('.').slice(0, 2).join('.')}`, '--implementation', 'cp',
    '--abi', `cp${PYTHON.tag}`, '-r', path.join(viewerDir, 'dist-requirements.txt')]);

  // pipが作る、コマンドの起動用exe（markdown-it.exeなど）は、Viewerが使わないため、外す
  fs.rmSync(path.join(sitePackages, 'bin'), { recursive: true, force: true });

  // text_compositor本体（PDF用のTypstのテンプレートも含める。0.1 MB程度）
  fs.cpSync(path.join(repoDir, 'text_compositor'), path.join(sitePackages, 'text_compositor'), {
    recursive: true,
    filter: (source) => !source.includes('__pycache__'),
  });

  // 起動を速くするため、バイトコードを作る（組込版のPython自身で）
  run(path.join(embed, 'python.exe'), ['-m', 'compileall', '-q', sitePackages]);
  return { embed, sitePackages };
}

/** パッケージのMETADATAから、名前・版・ライセンスを読む。 */
function readMetadata(distInfo) {
  const text = fs.readFileSync(path.join(distInfo, 'METADATA'), 'utf8');
  const field = (name) => (text.match(new RegExp(`^${name}: (.+)$`, 'm')) || [])[1]?.trim() ?? '';
  return {
    name: field('Name'),
    version: field('Version'),
    license: field('License-Expression') || field('License') || (text.match(/^Classifier: License :: (?:OSI Approved :: )?(.+)$/m) || [])[1] || '',
    url: (text.match(/^Project-URL: (?:Homepage|Source|Repository), (.+)$/mi) || [])[1] || field('Home-page'),
  };
}

function writeLicenses(appDir, embed, sitePackages, apacheText) {
  const dir = path.join(appDir, 'licenses');
  fs.mkdirSync(dir, { recursive: true });
  const rows = [];

  fs.copyFileSync(path.join(embed, 'LICENSE.txt'), path.join(dir, 'Python-LICENSE.txt'));
  rows.push({ name: 'Python (embeddable package)', version: PYTHON.version, license: 'PSF-2.0', url: 'https://www.python.org/', file: 'Python-LICENSE.txt' });

  // 組込版Pythonに含まれる、第三者のライブラリ。HTTPS（図のツールの取得）に使うOpenSSLは、Apache-2.0の全文を付ける。
  fs.copyFileSync(apacheText, path.join(dir, 'Apache-2.0.txt'));
  rows.push({ name: 'OpenSSL (libcrypto, libssl; in the Python package)', version: '3.x', license: 'Apache-2.0', url: 'https://www.openssl.org/', file: 'Apache-2.0.txt' });
  rows.push({ name: 'libffi, expat, SQLite, LibTomMath, Zstandard bindings, Microsoft Visual C++ runtime (in the Python package)', version: '(as shipped by python.org)', license: 'MIT / MIT / public domain / public domain / BSD-3-Clause / Microsoft redistributable terms', url: `https://docs.python.org/${PYTHON.version.split('.').slice(0, 2).join('.')}/license.html`, file: '(see the link; see also Python-LICENSE.txt)' });

  for (const entry of fs.readdirSync(sitePackages).filter((name) => name.endsWith('.dist-info'))) {
    const info = path.join(sitePackages, entry);
    const meta = readMetadata(info);
    const files = [];
    for (const candidate of [info, path.join(info, 'licenses')]) {
      if (!fs.existsSync(candidate)) continue;
      for (const name of fs.readdirSync(candidate)) {
        if (/^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)/i.test(name) && fs.statSync(path.join(candidate, name)).isFile()) {
          const target = `${meta.name}-${name}`;
          fs.copyFileSync(path.join(candidate, name), path.join(dir, target));
          files.push(target);
        }
      }
    }
    rows.push({ ...meta, file: files.join(', ') || '（ライセンス全文は、パッケージのメタデータの表記のみ）' });
  }

  fs.copyFileSync(path.join(repoDir, 'LICENSE'), path.join(dir, 'Obunzu-text-compositor-LICENSE.txt'));
  rows.unshift({ name: 'Obunzu / text-compositor', version: pkg.version, license: 'MIT', url: 'https://github.com/tokudiro/text-compositor', file: 'Obunzu-text-compositor-LICENSE.txt' });

  const lines = [
    '# Third-party notices',
    '',
    `Obunzu ${pkg.version} bundles the components below. Electron and Chromium license texts are in the`,
    'application folder (`LICENSE` and `LICENSES.chromium.html`).',
    '',
    '| Component | Version | License | Source | License text (in this folder) |',
    '| --- | --- | --- | --- | --- |',
    ...rows.map((r) => `| ${r.name} | ${r.version} | ${r.license} | ${r.url} | ${r.file} |`),
    '| Electron | (see the app) | MIT | https://www.electronjs.org/ | ../LICENSE |',
    '| Chromium and its components | (bundled with Electron) | various | https://www.chromium.org/ | ../LICENSES.chromium.html |',
    '',
    '## Downloaded on first use (not bundled)',
    '',
    'These files are not part of this archive. They are fetched when a document needs them (pinned by version and SHA256),',
    'and cached per user. They are listed here for transparency.',
    '',
    '| Component | License | Source |',
    '| --- | --- | --- |',
    '| Mermaid (`mermaid.min.js`) | MIT | https://github.com/mermaid-js/mermaid |',
    '| Viz.js (`viz-global.js`; Graphviz compiled to WebAssembly) | MIT | https://github.com/mdaines/viz-js |',
    '| Graphviz (inside Viz.js) | EPL-2.0 | https://graphviz.org/ |',
    '| Expat (inside Viz.js) | MIT | https://libexpat.github.io/ |',
    '',
  ];
  fs.writeFileSync(path.join(dir, 'THIRD-PARTY-NOTICES.md'), lines.join('\n'));
  return rows;
}

function report(appDir, embed, sitePackages, zip) {
  const rows = [];
  const total = sizeOf(appDir);
  const python = sizeOf(embed);
  const packages = sizeOf(sitePackages);
  rows.push(['Electron本体（exe・DLL・言語パックなど）', total - python - sizeOf(path.join(appDir, 'resources')) - sizeOf(path.join(appDir, 'licenses'))]);
  rows.push(['アプリ（resources/）', sizeOf(path.join(appDir, 'resources'))]);
  rows.push(['組込版Python本体', python - packages]);
  rows.push(['Pythonのパッケージ（site-packages）', packages]);
  rows.push(['ライセンス表記（licenses/）', sizeOf(path.join(appDir, 'licenses'))]);
  console.log('\n同梱物のサイズ（展開後）');
  for (const [name, bytes] of rows) console.log(`  ${name.padEnd(40)} ${mb(bytes).padStart(10)}`);
  console.log(`  ${'合計'.padEnd(40)} ${mb(total).padStart(10)}`);
  console.log(`\nZIP: ${zip}  ${mb(fs.statSync(zip).size)}`);
  const perPackage = fs.readdirSync(sitePackages, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.endsWith('.dist-info') && entry.name !== '__pycache__')
    .map((entry) => [entry.name, sizeOf(path.join(sitePackages, entry.name))]);
  console.log('\nsite-packagesの内訳');
  for (const [name, bytes] of perPackage) console.log(`  ${name.padEnd(24)} ${mb(bytes).padStart(10)}`);
}

async function main() {
  if (process.platform !== 'win32') throw new Error('この配布物は、Windows向けです（tarとPowerShell前提のZIP作成のため）。');
  fs.rmSync(stage, { recursive: true, force: true });
  fs.mkdirSync(stage, { recursive: true });

  log('1/6 Electronのアプリを作る');
  const { packager } = require('@electron/packager');
  const [built] = await packager({
    dir: viewerDir,
    out: stage,
    name: 'Obunzu',
    executableName: 'obunzu',
    platform: 'win32',
    arch: 'x64',
    icon: path.join(viewerDir, 'assets', 'icon.ico'),
    overwrite: true,
    asar: true,
    prune: true,
    quiet: true,
    win32metadata: {
      CompanyName: 'tokudiro',
      FileDescription: 'Obunzu - Markdown viewer for Docs, Diagrams and Design as Code',
      ProductName: 'Obunzu',
      OriginalFilename: 'obunzu.exe',
    },
    // 配布物に要らないもの（テスト・スクリプト・文書・ビルドの成果物）を、アプリから外す
    ignore: [/^\/test($|\/)/, /^\/scripts($|\/)/, /^\/dist($|\/)/, /^\/dist-requirements\.txt$/, /^\/README.*\.md$/],
  });
  const appDir = path.join(stage, releaseName);
  fs.renameSync(built, appDir);

  log('2〜4/6 組込版Pythonと、パッケージを同梱する');
  const embedZip = await fetchVerified(PYTHON, '組込版Python');
  const apacheText = await fetchVerified({ ...APACHE, file: 'Apache-2.0.txt' }, 'Apache-2.0の全文');
  const { embed, sitePackages } = buildPythonEnvironment(appDir, embedZip);

  log('5/6 ライセンス表記を作る');
  writeLicenses(appDir, embed, sitePackages, apacheText);

  log('6/6 ZIPにする');
  const zip = path.join(dist, `${releaseName}.zip`);
  fs.rmSync(zip, { force: true });
  run(TAR, ['-a', '-c', '-f', zip, '-C', stage, releaseName]);
  report(appDir, embed, sitePackages, zip);
  console.log(`\n展開済み: ${appDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
