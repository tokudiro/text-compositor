'use strict';
// Windows向けの配布物（ZIP）を作る（#168）。
//   node scripts/build-dist.js
//
// 作るもの: dist/Obunzu-<バージョン>-win-x64.zip（Pythonのインストールが要らない、展開して使うポータブル版）。
// 中身: Electronのアプリ（obunzu.exe）と、その隣の python-embed/（組込版Python + 必要最小限のパッケージ +
//       typst + text_compositor）と、fonts/（Noto Sans JP）と、typst-packages/（Typstのパッケージ。#263）と、
//       licenses/（サードパーティのライセンス表記）。
//
// 手順:
//   1. @electron/packagerで、Electronのアプリを作る（アイコン・バージョン情報・asar）。
//   2. python.orgの組込版Pythonを取得して（SHA256を確認）、python-embed/に展開する。
//   3. dist-requirements.txtのパッケージを、ビルド用のPythonのpipで、組込版のsite-packagesへ入れる
//      （--platform win_amd64・cp314・wheelのみ。ビルドするPythonの版に、依存しない）。
//   4. text_compositorのパッケージを、site-packagesへ写す。バイトコードを作る（起動を速くするため）。
//   4b. フォント（fonts/）と、Typstのパッケージ（typst-packages/）を、取得して（SHA256を確認）、同梱する。
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

// Typstを通す処理のために、フォント（fonts/）と、Typstのパッケージ（typst-packages/）も、ZIPに同梱する（#263。#237で決めた）。
// ネットワークなしで動くようにするため（ツール群の方針3）。取得元・SHA256は固定し、text_compositor/deps.pyと同じフォントを使う
// （CLIのPDFと同じ見た目にするため。tests/test_bundled_typst_assets.pyが、deps.pyとテンプレートとの一致を確認する）。
const FONTS = {
  version: '2.004',
  url: 'https://github.com/notofonts/noto-cjk/releases/download/Sans2.004/16_NotoSansJP.zip',
  sha256: '2bbdd2c20f30670b39ca735c96d75f1fdabdb348103e43b820cf17701fd22b18',   // zip全体
  files: {   // zipから取り出すフォント。ファイルごとのSHA256（deps.pyのNOTO_SANS_JP_FILESと同じ）
    'NotoSansJP-Regular.otf': 'dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073',
    'NotoSansJP-Bold.otf': '1b0edfb500b73a4fa8a4fcaae1bbbd403994e08e73e3e0da37e70d3853f42c5f',
  },
};
// 実際に使う版だけ入れる（text_compositor/templates/_common.typの`@preview/...`と同じ版）。CeTZ（LGPL）などは、使う機能を作るときに加える。
const TYPST_PACKAGES = [
  { name: 'diagraph', version: '0.3.7', license: 'MIT', sha256: '08b9927b047e95c661c1d7ae28806b8cbefa25a07f8ae2d4a47911028875abc6' },
  { name: 'note-me', version: '0.6.0', license: 'MIT', sha256: '94273b3c9a7ddc3960ad86dfc02b8f864eebd918699a1a32310a6cf40aee67a6' },
];

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
  writeDistInfo(sitePackages);

  // 起動を速くするため、バイトコードを作る（組込版のPython自身で）
  run(path.join(embed, 'python.exe'), ['-m', 'compileall', '-q', sitePackages]);
  return { embed, sitePackages };
}

/**
 * 同梱した`text_compositor`に、最小の`dist-info`（パッケージのメタデータ）を作る（#235）。`text_compositor.__version__`は、
 * `importlib.metadata.version("text-compositor")`で読むため、メタデータがないと、ワーカーが版を`0+unknown`と報告する。
 * 版は、`pyproject.toml`から読む（`viewer/package.json`と同じ値にそろえる決まり。`tests/test_viewer_version.py`）。
 * pipでリポジトリを入れる方法は、ビルド用のパッケージの取得に依存し、不要なファイルも入るため、採らない。
 */
function writeDistInfo(sitePackages) {
  const pyproject = fs.readFileSync(path.join(repoDir, 'pyproject.toml'), 'utf8');
  const version = (pyproject.match(/^version\s*=\s*"([^"]+)"/m) || [])[1];
  if (!version) throw new Error('pyproject.tomlから、versionを読めませんでした。');
  const info = path.join(sitePackages, `text_compositor-${version}.dist-info`);
  fs.rmSync(info, { recursive: true, force: true });
  fs.mkdirSync(info, { recursive: true });
  fs.writeFileSync(path.join(info, 'METADATA'), `Metadata-Version: 2.1\nName: text-compositor\nVersion: ${version}\n`);
  return info;
}

/**
 * フォント（fonts/）と、Typstのパッケージ（typst-packages/preview/<名前>/<版>/）を、取得して、同梱する（#263）。
 * 実行時は、Electronが、環境変数（TEXT_COMPOSITOR_FONT_DIR・TEXT_COMPOSITOR_TYPST_PACKAGES）で、ワーカーに教える。
 * @returns ライセンス表記の行
 */
async function bundleTypstAssets(appDir) {
  const rows = [];

  const fontZip = await fetchVerified({ url: FONTS.url, sha256: FONTS.sha256 }, 'Noto Sans JP');
  const fontsDir = path.join(appDir, 'fonts');
  fs.mkdirSync(fontsDir, { recursive: true });
  // zipには、使わない太さ（Thin・Blackなど）も入っている。使う2つと、ライセンスだけを取り出す
  run(TAR, ['-xf', fontZip, '-C', fontsDir, ...Object.keys(FONTS.files), 'LICENSE']);
  for (const [name, expected] of Object.entries(FONTS.files)) {
    const actual = sha256(path.join(fontsDir, name));
    if (actual !== expected) throw new Error(`${name}のSHA256が一致しません: 期待 ${expected}、実際 ${actual}`);
  }
  rows.push({ name: 'Noto Sans JP (fonts/)', version: FONTS.version, license: 'OFL-1.1', url: 'https://github.com/notofonts/noto-cjk', file: '../fonts/LICENSE' });

  for (const p of TYPST_PACKAGES) {
    const url = `https://packages.typst.org/preview/${p.name}-${p.version}.tar.gz`;
    const archive = await fetchVerified({ url, sha256: p.sha256 }, `Typstのパッケージ ${p.name}`);
    const target = path.join(appDir, 'typst-packages', 'preview', p.name, p.version);
    fs.mkdirSync(target, { recursive: true });
    run(TAR, ['-xzf', archive, '-C', target]);
    for (const required of ['typst.toml', 'LICENSE']) {
      if (!fs.existsSync(path.join(target, required))) throw new Error(`Typstのパッケージ ${p.name} ${p.version} に、${required}がありません`);
    }
    rows.push({ name: `Typst package ${p.name} (typst-packages/)`, version: p.version, license: p.license,
      url: `https://typst.app/universe/package/${p.name}`, file: `../typst-packages/preview/${p.name}/${p.version}/LICENSE` });
  }
  return rows;
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

function writeLicenses(appDir, embed, sitePackages, apacheText, extraRows = []) {
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
    // 自分自身（writeDistInfoが作った、最小のメタデータ）は、下の`Obunzu / text-compositor`の行と、二重にしない（#235）
    if (meta.name === 'text-compositor') continue;
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

  rows.push(...extraRows);   // 同梱のフォント・Typstのパッケージ（ライセンス全文は、それぞれのフォルダの中）

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
  const fonts = sizeOf(path.join(appDir, 'fonts'));
  const typstPackages = sizeOf(path.join(appDir, 'typst-packages'));
  rows.push(['Electron本体（exe・DLL・言語パックなど）', total - python - fonts - typstPackages - sizeOf(path.join(appDir, 'resources')) - sizeOf(path.join(appDir, 'licenses'))]);
  rows.push(['アプリ（resources/）', sizeOf(path.join(appDir, 'resources'))]);
  rows.push(['組込版Python本体', python - packages]);
  rows.push(['Pythonのパッケージ（site-packages。typstを含む）', packages]);
  rows.push(['フォント（fonts/）', fonts]);
  rows.push(['Typstのパッケージ（typst-packages/）', typstPackages]);
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

  log('4/6 Typstを通す処理のための、フォントとパッケージを同梱する');
  const assetRows = await bundleTypstAssets(appDir);

  log('5/6 ライセンス表記を作る');
  writeLicenses(appDir, embed, sitePackages, apacheText, assetRows);

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
