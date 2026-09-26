'use strict';
// Windows向けの配布物（ZIP）を作る（#168）。
//   node scripts/build-dist.js
//
// 作るもの: dist/Obunzu-<バージョン>-win-x64.zip（Pythonのインストールが要らない、展開して使うポータブル版）。
// 中身: Electronのアプリ（obunzu.exe）と、その隣の python-embed/（組込版Python + 必要最小限のパッケージ +
//       typst + text_compositor）と、fonts/（Noto Sans JP）と、typst-packages/（Typstのパッケージ。#263）と、
//       jre/・plantuml/・d2/・structurizr-cli/・mermaid/（Mermaid・PlantUML・D2・Structurizrの図が、そのまま
//       GUIから、追加のダウンロードなしで使えるようにする。#290・#310）と、licenses/（サードパーティのライセンス表記）。
//
// 手順:
//   1. @electron/packagerで、Electronのアプリを作る（アイコン・バージョン情報・asar）。
//   2. python.orgの組込版Pythonを取得して（SHA256を確認）、python-embed/に展開する。
//   3. dist-requirements.txtのパッケージを、ビルド用のPythonのpipで、組込版のsite-packagesへ入れる
//      （--platform win_amd64・cp314・wheelのみ。ビルドするPythonの版に、依存しない）。
//   4. text_compositorのパッケージを、site-packagesへ写す。バイトコードを作る（起動を速くするため）。
//   4b. フォント（fonts/）と、Typstのパッケージ（typst-packages/）を、取得して（SHA256を確認）、同梱する。
//   4c. Java・plantuml.jar・D2・structurizr-cli（絞り込み版）・mermaid.min.jsを、取得して（SHA256を確認）、
//       同梱する（#290・#310）。
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
// 実際に使う版だけ入れる（text_compositor/templates/_common.typの`@preview/...`と、kip（Pikchr。#213）・cetz・fletcher（#236）はtext_compositor/の
// pikchr_render.py・cetz_render.pyの版の定数と、同じ版）。fletcher 0.5.8は、cetz 0.3.4とoxifmtに依存する（cetz 0.5.2は、cetz自身がoxifmtに依存する）。
// 推移的な依存も、オフラインで動くように、すべて入れる。CeTZ（LGPL-3.0以降）の扱いは、下の`LGPL_NOTICE`。
const TYPST_PACKAGES = [
  { name: 'cetz', version: '0.3.4', license: 'LGPL-3.0-or-later', sha256: '4f4b5a8d311d519e749940a766fe50521e40c041129e1c91af0c42e61f307514' },
  { name: 'cetz', version: '0.5.2', license: 'LGPL-3.0-or-later', sha256: '77cf8490114ae04c6e665a11efa691d284a0cadb9719771b5708c1197292f23f' },
  { name: 'diagraph', version: '0.3.7', license: 'MIT', sha256: '08b9927b047e95c661c1d7ae28806b8cbefa25a07f8ae2d4a47911028875abc6' },
  { name: 'fletcher', version: '0.5.8', license: 'MIT', sha256: 'a61883a4af4ca923a37c597900e674f40dad3f7bde3f2a3d8fe8042e6ca8a66b' },
  { name: 'kip', version: '0.1.0', license: 'MIT', sha256: '4b90dc0e3e0bcc2f273940a15a3c8855f9aa65bd972791f49018154017cb90d0' },
  { name: 'note-me', version: '0.6.0', license: 'MIT', sha256: '94273b3c9a7ddc3960ad86dfc02b8f864eebd918699a1a32310a6cf40aee67a6' },
  { name: 'oxifmt', version: '0.2.1', license: 'MIT-0', sha256: '16fac2923032c59727de01e84d42cac45e8790da28df56effca49f4de41b09d9' },
  { name: 'oxifmt', version: '1.0.0', license: 'MIT OR Apache-2.0', sha256: '7d17a1fc8ad01740ec3cb2b03c7360a4225ff9318e5710765fa98ea6fd59594f' },
];

// CeTZ（LGPL-3.0以降）を同梱する条件（#236）。Typstのパッケージは、ソースそのものなので、ソースの提供は、この配布物が満たす。
// 利用者が差し替えられるよう、改造せず、別のフォルダ（typst-packages/preview/cetz/<版>/）のまま入れる。LGPLの全文と著作権表示は、
// そのフォルダの`LICENSE`。ソースの入手先は、Typst Universe・GitHub。
const LGPL_NOTICE = [
  '## CeTZ (LGPL-3.0-or-later)',
  '',
  'The Typst package CeTZ (`typst-packages/preview/cetz/`, two versions) is licensed under the GNU LGPL, version 3 or later.',
  'It is included unmodified, as separate source files, so that you can replace it with another version:',
  'put the package into the same folder layout (`typst-packages/preview/cetz/<version>/`). The license text (with the',
  'copyright notice) is `LICENSE` in each of those folders. The source is available at https://typst.app/universe/package/cetz',
  'and https://github.com/cetz-package/cetz. CeTZ is used only through Typst; the generated PDF/HTML files and your documents',
  'are not covered by the LGPL.',
  '',
];

// Java（Structurizr・PlantUMLが使う。#290）。ローカルにJava 11+が見つからない場合と同じ取得元（text_compositor/deps.pyの
// TEMURIN_JRE_ASSETS、win32/x86_64の1件のみ。build-dist.js自体がWindows向けのため）。
const JRE = {
  version: '21.0.12.1+1',
  file: 'OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip',
  url: 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip',
  sha256: 'd35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636',
  topDir: 'jdk-21.0.12.1+1-jre',
};

// PlantUML本体（deps.pyのPLANTUML_JAR_URL/SHA256と同じ、MIT版）。jarの中にライセンス全文は無いため、
// GitHub上の対応するライセンスファイル（同じ版のタグ）を、Apache-2.0の全文と同じ手順で別途取得・固定する。
const PLANTUML = {
  url: 'https://github.com/plantuml/plantuml/releases/download/v1.2026.8/plantuml-mit-1.2026.8.jar',
  sha256: '3629c9cd017c7f73e6450396eea0040216c7e1eef8473ce33cc1aad469dab2f9',
};
const PLANTUML_LICENSE = {
  url: 'https://raw.githubusercontent.com/plantuml/plantuml/v1.2026.8/plantuml-mit/mit-license.txt',
  sha256: '0aadc58e7c3e1eee5914418ff63ffbd19b79747075190b5f9f69017ab58966df',
};

// Mermaid公式配布の単一バンドルJS（deps.pyのMERMAID_JS_URL/SHA256と同じ）。#310。ライセンス全文は、jsの中に
// 無いため、PlantUMLと同じ手順で、GitHub上のLICENSE（現在のmasterの内容）を別途取得・固定する。
const MERMAID_JS = {
  version: '11.16.1',
  file: 'mermaid.min.js',
  url: 'https://cdn.jsdelivr.net/npm/mermaid@11.16.1/dist/mermaid.min.js',
  sha256: '18327bef70d96fb505fe7287d9f6a7362ebf07ff6576ddfaffb1a06f3e1a2954',
};
const MERMAID_LICENSE = {
  url: 'https://raw.githubusercontent.com/mermaid-js/mermaid/master/LICENSE',
  sha256: 'ec9fb67dcb25eccc416ed56e1aab819222c805a2a4bfe4cb19e7556bf2ffde80',
};

// D2公式CLIバイナリ（deps.pyのD2_ASSETSと同じ、win32/x86_64の1件）。アーカイブ自身にLICENSE.txtが入っている。
const D2 = {
  version: 'v0.9.0',
  file: 'd2-v0.9.0-windows-amd64.tar.gz',
  url: 'https://github.com/d2lang/d2/releases/download/v0.9.0/d2-v0.9.0-windows-amd64.tar.gz',
  sha256: '5f63b643de8f5a6dfb922d172e1b5496e4caf47497c33c4427cf1127f28c340f',
  topDir: 'd2-v0.9.0',
};

// Structurizr CLI（deps.pyのSTRUCTURIZR_CLI_URL/SHA256と同じ、公式zipそのまま）。
const STRUCTURIZR_CLI = {
  release: 'v2025.11.09',
  url: 'https://github.com/structurizr/cli/releases/download/v2025.11.09/structurizr-cli.zip',
  sha256: 'f5365a463fc44d539ed19bec00c48ba1e1ecda0ccfd1ba40d2e7472d264eb79a',
};
// structurizr-cliのlib/（展開すると約99MB・54個）のうち、Kotlin/JRuby/Groovyのスクリプト形式ワークスペース定義
// （.kts/.rb/.groovy）向けと、ソースコードからのコンポーネント自動検出（javaparser経由）向けのjarを除く。
// 本ツールはDSL（`workspace { ... }`テキスト）の`include *`/`autoLayout`等のみ使い、どちらも使わない。除いても
// `export -format plantuml`の出力が変わらないことを、手元でフルセットとの出力比較で確認済み（36個・約14MBまで縮む）。
const STRUCTURIZR_CLI_KEEP_JARS = [
  'annotations-13.0.jar', 'checker-qual-3.51.1.jar', 'commons-cli-1.10.0.jar', 'commons-io-2.20.0.jar',
  'commons-lang3-3.19.0.jar', 'commons-logging-1.3.5.jar', 'error_prone_annotations-2.41.0.jar',
  'failureaccess-1.0.3.jar', 'guava-33.5.0-jre.jar', 'httpclient5-5.5.1.jar', 'httpcore5-5.3.6.jar',
  'httpcore5-h2-5.3.6.jar', 'j2objc-annotations-3.1.jar', 'jackson-annotations-2.20.jar',
  'jackson-core-2.20.0.jar', 'jackson-databind-2.20.0.jar', 'javax.activation-api-1.2.0.jar',
  'jaxb-api-2.4.0-b180830.0359.jar', 'jspecify-1.0.0.jar', 'jsr305-3.0.2.jar',
  'listenablefuture-9999.0-empty-to-avoid-conflict-with-guava.jar', 'log4j-api-2.25.2.jar',
  'log4j-core-2.25.2.jar', 'log4j-jcl-2.25.2.jar', 'log4j-slf4j-impl-2.25.2.jar', 'slf4j-api-1.7.36.jar',
  'structurizr-autolayout-5.0.2.jar', 'structurizr-cli.jar', 'structurizr-client-5.0.2.jar',
  'structurizr-component-5.0.2.jar', 'structurizr-core-5.0.2.jar', 'structurizr-dsl-5.0.2.jar',
  'structurizr-export-5.0.2.jar', 'structurizr-import-5.0.2.jar', 'structurizr-inspection-5.0.2.jar',
  'trove4j-1.0.20200330.jar',
];

// trove4j（LGPL-2.1以降）を同梱する条件。CeTZと同じ考え方（改造せず、差し替え可能な、別ファイルのまま同梱）だが、
// Typstのパッケージ（ソース）と異なり、jarというビルド済みバイナリのため、差し替えは「同じファイル名のjarを、
// structurizr-cli/lib/に置き換える」ことで行える（javaのクラスパス読み込みのため、静的リンクではない）。
const TROVE4J_NOTICE = [
  '## trove4j (LGPL-2.1-or-later)',
  '',
  'The library trove4j (`structurizr-cli/lib/trove4j-1.0.20200330.jar`, a dependency of the bundled Structurizr CLI)',
  'is licensed under the GNU LGPL, version 2.1 or later. It is included unmodified, as a separate jar file (loaded via',
  "Java's classpath, not statically linked), so you can replace it with another (compatible) build: put the replacement",
  'at the same path with the same file name. The jar carries no license file of its own; the license text is at',
  'https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html, and the source is available at',
  'https://github.com/JetBrains/intellij-deps-trove4j (this build, `org.jetbrains.intellij.deps:trove4j:1.0.20200330`,',
  'is a fork maintained for the IntelliJ Platform). trove4j is used only inside structurizr-cli; the diagrams and',
  'documents you produce are not covered by the LGPL.',
  '',
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
  // kipのWASMに含まれる、Pikchr本体（#213）。kipのREADMEは「BSD-style」と記す。正確なライセンスの識別子は、未確認
  rows.push({ name: 'Pikchr (compiled into the WASM of the Typst package kip)', version: '(as built by kip)', license: 'BSD-style (see the link)',
    url: 'https://pikchr.org/', file: '(see the link; the kip package licenses are in ../typst-packages/preview/kip/)' });
  return rows;
}

/**
 * Java（JRE）・plantuml.jar・D2・structurizr-cli（絞り込み版）・mermaid.min.jsを、取得して、同梱する（#290・#310）。
 * 実行時は、Electronが、環境変数（TEXT_COMPOSITOR_JAVA_BIN等）で、ワーカーに教える（初回起動から、
 * 追加のダウンロードなしで、Mermaid・PlantUML・D2・Structurizrの図が使えるようにするため）。
 * @returns ライセンス表記の行
 */
async function bundleDiagramTools(appDir) {
  const rows = [];

  // Java（jre/bin/java.exe）。zipはjdk-<版>-jre/配下に展開されるため、その中身をjre/へ移す（フォルダ名から版を外し、
  // python.jsの決め打ちのパス`jre/bin/java.exe`に合わせる）。
  const jreZip = await fetchVerified(JRE, 'Eclipse Temurin JRE');
  const jreTmp = path.join(appDir, '_jre-tmp');
  fs.rmSync(jreTmp, { recursive: true, force: true });
  fs.mkdirSync(jreTmp, { recursive: true });
  run(TAR, ['-xf', jreZip, '-C', jreTmp]);
  const jreDir = path.join(appDir, 'jre');
  fs.rmSync(jreDir, { recursive: true, force: true });
  // renameSyncは、直後にEPERM（操作が許可されていません）で失敗することがある（展開直後のフォルダを、
  // ウイルス対策ソフト等が、まだ開いているため。推測）。cpSync + rmSyncは、この問題を避けられる。
  fs.cpSync(path.join(jreTmp, JRE.topDir), jreDir, { recursive: true });
  fs.rmSync(jreTmp, { recursive: true, force: true });
  if (!fs.existsSync(path.join(jreDir, 'bin', 'java.exe'))) throw new Error('Eclipse Temurin JREの展開結果に、jre/bin/java.exeがありません');
  // ライセンス全文は、JRE自身が同梱するもの（legal/java.base/）をそのまま使う（GPLv2 + Classpath Exception）
  rows.push({ name: 'Eclipse Temurin JRE (jre/)', version: JRE.version, license: 'GPL-2.0-with-classpath-exception',
    url: 'https://adoptium.net/', file: '../jre/legal/java.base/LICENSE, ../jre/legal/java.base/ASSEMBLY_EXCEPTION' });

  // plantuml.jar（plantuml/plantuml.jar。固定名にする。python.jsの決め打ちのパスに合わせる）
  const plantumlJar = await fetchVerified(PLANTUML, 'plantuml.jar');
  const plantumlDir = path.join(appDir, 'plantuml');
  fs.mkdirSync(plantumlDir, { recursive: true });
  fs.copyFileSync(plantumlJar, path.join(plantumlDir, 'plantuml.jar'));
  const plantumlLicense = await fetchVerified({ ...PLANTUML_LICENSE, file: 'PlantUML-LICENSE.txt' }, 'PlantUMLのMITライセンス全文');
  fs.mkdirSync(path.join(appDir, 'licenses'), { recursive: true });
  fs.copyFileSync(plantumlLicense, path.join(appDir, 'licenses', 'PlantUML-LICENSE.txt'));
  rows.push({ name: 'PlantUML (mit build; plantuml/plantuml.jar)', version: path.basename(PLANTUML.url), license: 'MIT',
    url: 'https://plantuml.com/', file: 'PlantUML-LICENSE.txt' });

  // D2（d2/d2.exe。固定名にする）。アーカイブ自身のLICENSE.txtを、そのまま同梱する
  const d2Archive = await fetchVerified(D2, 'D2 CLI');
  const d2Tmp = path.join(appDir, '_d2-tmp');
  fs.rmSync(d2Tmp, { recursive: true, force: true });
  fs.mkdirSync(d2Tmp, { recursive: true });
  run(TAR, ['-xzf', d2Archive, '-C', d2Tmp]);
  const d2Dir = path.join(appDir, 'd2');
  fs.mkdirSync(d2Dir, { recursive: true });
  fs.copyFileSync(path.join(d2Tmp, D2.topDir, 'bin', 'd2.exe'), path.join(d2Dir, 'd2.exe'));
  fs.copyFileSync(path.join(d2Tmp, D2.topDir, 'LICENSE.txt'), path.join(appDir, 'licenses', 'D2-LICENSE.txt'));
  fs.rmSync(d2Tmp, { recursive: true, force: true });
  rows.push({ name: `D2 (${D2.version}; d2/d2.exe)`, version: D2.version, license: 'MPL-2.0',
    url: 'https://github.com/d2lang/d2', file: 'D2-LICENSE.txt' });

  // structurizr-cli（structurizr-cli/lib/）。公式zipを一時フォルダへ全展開し、STRUCTURIZR_CLI_KEEP_JARSの
  // jarだけをstructurizr-cli/lib/へ写す（一時フォルダごと、後で消す）
  const structurizrZip = await fetchVerified(STRUCTURIZR_CLI, 'structurizr-cli');
  const structurizrTmp = path.join(appDir, '_structurizr-tmp');
  fs.rmSync(structurizrTmp, { recursive: true, force: true });
  fs.mkdirSync(structurizrTmp, { recursive: true });
  run(TAR, ['-xf', structurizrZip, '-C', structurizrTmp]);
  const structurizrLibDir = path.join(appDir, 'structurizr-cli', 'lib');
  fs.rmSync(path.join(appDir, 'structurizr-cli'), { recursive: true, force: true });
  fs.mkdirSync(structurizrLibDir, { recursive: true });
  const keep = new Set(STRUCTURIZR_CLI_KEEP_JARS);
  const available = new Set(fs.readdirSync(path.join(structurizrTmp, 'lib')));
  for (const name of STRUCTURIZR_CLI_KEEP_JARS) {
    if (!available.has(name)) throw new Error(`structurizr-cliのlib/に、想定していたjarがありません: ${name}`);
  }
  for (const name of available) {
    if (keep.has(name)) fs.copyFileSync(path.join(structurizrTmp, 'lib', name), path.join(structurizrLibDir, name));
  }
  fs.rmSync(structurizrTmp, { recursive: true, force: true });
  rows.push({ name: `Structurizr CLI (${STRUCTURIZR_CLI.release}, trimmed to ${STRUCTURIZR_CLI_KEEP_JARS.length} jars; structurizr-cli/lib/)`,
    version: STRUCTURIZR_CLI.release, license: 'Apache-2.0', url: 'https://github.com/structurizr/cli', file: 'Apache-2.0.txt' });

  // mermaid.min.js（mermaid/mermaid.min.js。固定名にする）。#310。これで、Obunzuの初回起動時の追加取得は、
  // Structurizrを有効化しない限りではなく、常にゼロになる（Structurizrも同梱済みのため）。
  const mermaidJs = await fetchVerified(MERMAID_JS, 'mermaid.min.js');
  const mermaidDir = path.join(appDir, 'mermaid');
  fs.mkdirSync(mermaidDir, { recursive: true });
  fs.copyFileSync(mermaidJs, path.join(mermaidDir, 'mermaid.min.js'));
  const mermaidLicense = await fetchVerified({ ...MERMAID_LICENSE, file: 'Mermaid-LICENSE.txt' }, 'MermaidのMITライセンス全文');
  fs.copyFileSync(mermaidLicense, path.join(appDir, 'licenses', 'Mermaid-LICENSE.txt'));
  rows.push({ name: `Mermaid (${MERMAID_JS.version}; mermaid/mermaid.min.js)`, version: MERMAID_JS.version, license: 'MIT',
    url: 'https://github.com/mermaid-js/mermaid', file: 'Mermaid-LICENSE.txt' });

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
    ...LGPL_NOTICE,
    ...TROVE4J_NOTICE,
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
  const jre = sizeOf(path.join(appDir, 'jre'));
  const plantuml = sizeOf(path.join(appDir, 'plantuml'));
  const d2 = sizeOf(path.join(appDir, 'd2'));
  const structurizrCli = sizeOf(path.join(appDir, 'structurizr-cli'));
  const mermaid = sizeOf(path.join(appDir, 'mermaid'));
  rows.push(['Electron本体（exe・DLL・言語パックなど）', total - python - fonts - typstPackages - jre - plantuml - d2 - structurizrCli - mermaid
    - sizeOf(path.join(appDir, 'resources')) - sizeOf(path.join(appDir, 'licenses'))]);
  rows.push(['アプリ（resources/）', sizeOf(path.join(appDir, 'resources'))]);
  rows.push(['組込版Python本体', python - packages]);
  rows.push(['Pythonのパッケージ（site-packages。typstを含む）', packages]);
  rows.push(['フォント（fonts/）', fonts]);
  rows.push(['Typstのパッケージ（typst-packages/）', typstPackages]);
  rows.push(['Java（jre/）', jre]);
  rows.push(['PlantUML（plantuml/）', plantuml]);
  rows.push(['D2（d2/）', d2]);
  rows.push(['Structurizr CLI（structurizr-cli/、絞り込み版）', structurizrCli]);
  rows.push(['Mermaid（mermaid/）', mermaid]);
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

  log('4b/6 Typstを通す処理のための、フォントとパッケージを同梱する');
  const assetRows = await bundleTypstAssets(appDir);

  log('4c/6 Java・plantuml.jar・D2・structurizr-cli・mermaid.min.jsを同梱する');
  const diagramToolRows = await bundleDiagramTools(appDir);

  log('5/6 ライセンス表記を作る');
  writeLicenses(appDir, embed, sitePackages, apacheText, [...assetRows, ...diagramToolRows]);

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
