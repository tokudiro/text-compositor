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

module.exports = { resolveWorkerLaunch, PythonNotFoundError, PYTHON_ENV, PYTHONPATH_ENV };
