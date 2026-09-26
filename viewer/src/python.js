'use strict';
// ワーカー（`python -m text_compositor.worker`）を起動するPythonを探す（#190）。
//
// 探す順序:
//   1. 環境変数 TEXT_COMPOSITOR_PYTHON（Python実行ファイルのフルパス）。開発時や、配布物の外のPythonを使う場合。
//   2. アプリの隣の python-embed/（配布物に同梱する組込版Python。#168）
//   3. PATH上の python・python3・py
// 環境変数 TEXT_COMPOSITOR_PYTHONPATH があれば、ワーカーのPYTHONPATHに加える。pipインストールせずに、
// リポジトリを直接使う開発時に、リポジトリのパスを指定する。

const fs = require('node:fs');
const path = require('node:path');

const PYTHON_ENV = 'TEXT_COMPOSITOR_PYTHON';
const PYTHONPATH_ENV = 'TEXT_COMPOSITOR_PYTHONPATH';
// 同梱のフォント・Typstのパッケージのフォルダ（ワーカー側の、text_compositor/deps.pyの`FONT_DIR_ENV`・compiler.pyの`TYPST_PACKAGES_ENV`と同じ名前）
const FONT_DIR_ENV = 'TEXT_COMPOSITOR_FONT_DIR';
const TYPST_PACKAGES_ENV = 'TEXT_COMPOSITOR_TYPST_PACKAGES';
// 同梱のJava・plantuml.jar・D2・structurizr-cliの場所（ワーカー側の、text_compositor/deps.pyの
// 同名の環境変数と同じ名前。#290）。PlantUML・Structurizrは同じJavaを共用する。
const JAVA_BIN_ENV = 'TEXT_COMPOSITOR_JAVA_BIN';
const PLANTUML_JAR_ENV = 'TEXT_COMPOSITOR_PLANTUML_JAR';
const D2_BIN_ENV = 'TEXT_COMPOSITOR_D2_BIN';
const STRUCTURIZR_CLI_LIB_ENV = 'TEXT_COMPOSITOR_STRUCTURIZR_CLI_LIB';
// 同梱のmermaid.min.jsのファイル（ワーカー側の、text_compositor/deps.pyの`MERMAID_JS_ENV`と同じ名前。#310）
const MERMAID_JS_ENV = 'TEXT_COMPOSITOR_MERMAID_JS';

class PythonNotFoundError extends Error {
  constructor(message) {
    super(message);
    this.name = 'PythonNotFoundError';
  }
}

/**
 * @param {string} appDir アプリの場所（python-embed/を探す起点）
 * @param {{env?: Record<string,string|undefined>, exists?: (p: string) => boolean, platform?: string}} [options]
 * @returns {{file: string, args: string[], env: Record<string,string>}}
 */
function resolveWorkerLaunch(appDir, options = {}) {
  const env = options.env ?? process.env;
  const exists = options.exists ?? fs.existsSync;
  const platform = options.platform ?? process.platform;

  const python = findPython(appDir, env, exists, platform);
  if (!python) {
    throw new PythonNotFoundError(
      `Pythonが見つかりません。環境変数 ${PYTHON_ENV} に、Python実行ファイルのパスを指定してください`
      + '（または、PATHにPythonを通してください）。');
  }

  const launchEnv = {};
  const extra = env[PYTHONPATH_ENV];
  if (extra && extra.trim()) {
    const existing = env.PYTHONPATH;
    launchEnv.PYTHONPATH = existing ? `${extra}${path.delimiter}${existing}` : extra;
  }
  // 配布物に同梱した、フォント（fonts/）と、Typstのパッケージ（typst-packages/）があれば、ワーカーに教える。ワーカーは、
  // ダウンロードせずに、これを使う（#263）。利用者が、環境変数で、すでに指定しているときは、それを優先する。
  const javaExe = platform === 'win32' ? 'java.exe' : 'java';
  const d2Exe = platform === 'win32' ? 'd2.exe' : 'd2';
  for (const [name, rel] of [
    [FONT_DIR_ENV, 'fonts'], [TYPST_PACKAGES_ENV, 'typst-packages'],
    // Java・plantuml.jarは、PlantUMLとStructurizrが共用する（#290）。
    [JAVA_BIN_ENV, path.join('jre', 'bin', javaExe)],
    [PLANTUML_JAR_ENV, path.join('plantuml', 'plantuml.jar')],
    [D2_BIN_ENV, path.join('d2', d2Exe)],
    [STRUCTURIZR_CLI_LIB_ENV, path.join('structurizr-cli', 'lib')],
    [MERMAID_JS_ENV, path.join('mermaid', 'mermaid.min.js')],
  ]) {
    const bundled = path.join(appDir, rel);
    if (!env[name] && exists(bundled)) launchEnv[name] = bundled;
  }
  return { file: python, args: ['-m', 'text_compositor.worker'], env: launchEnv };
}

function findPython(appDir, env, exists, platform) {
  const fromEnv = env[PYTHON_ENV];
  if (fromEnv && fromEnv.trim()) {
    if (exists(fromEnv)) return fromEnv;
    throw new PythonNotFoundError(`環境変数 ${PYTHON_ENV} のPythonが見つかりません: ${fromEnv}`);
  }

  for (const name of ['python.exe', path.join('bin', 'python3')]) {
    const embedded = path.join(appDir, 'python-embed', name);
    if (exists(embedded)) return embedded;
  }

  const names = platform === 'win32'
    ? ['python.exe', 'python3.exe', 'py.exe']
    : ['python3', 'python'];
  for (const dir of (env.PATH ?? env.Path ?? '').split(path.delimiter)) {
    if (!dir) continue;
    for (const name of names) {
      const candidate = path.join(dir.replace(/^"|"$/g, ''), name);
      if (exists(candidate)) return candidate;
    }
  }
  return null;
}

module.exports = {
  resolveWorkerLaunch, PythonNotFoundError, PYTHON_ENV, PYTHONPATH_ENV, FONT_DIR_ENV, TYPST_PACKAGES_ENV,
  JAVA_BIN_ENV, PLANTUML_JAR_ENV, D2_BIN_ENV, STRUCTURIZR_CLI_LIB_ENV, MERMAID_JS_ENV,
};
