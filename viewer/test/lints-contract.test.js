'use strict';
// lintの一覧の契約テスト（#271）。設定画面の一覧（`src/settings.js`のLINTS）の、名前と既定値が、text-compositor本体
// （`text_compositor/lints.py`のLINTS）と、そろっていること。ずれると、設定画面の項目を切り替えても、ワーカーが、
// 知らない名前として、断る（または、既定値が食い違う）ため、ここで検出する。
//
// 実行には、text_compositorを読めるPythonが要る。無い環境では、飛ばす。CIでは、環境変数
// REQUIRE_WORKER_INTEGRATION=1 を付けて、飛ばさず、失敗にする（worker-integration.test.jsと同じ）。

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { describe, test } = require('node:test');

const { PYTHONPATH_ENV, PythonNotFoundError, resolveWorkerLaunch } = require('../src/python');
const { LINTS } = require('../src/settings');

const repoDir = path.resolve(__dirname, '..', '..');
const required = process.env.REQUIRE_WORKER_INTEGRATION === '1';

/** Pythonの`LINTS`を、{名前: {default, label}}で読む。読めないときは、その理由を返す。 */
function readPythonLints() {
  let launch;
  try {
    const env = { ...process.env, [PYTHONPATH_ENV]: process.env[PYTHONPATH_ENV] || repoDir };
    launch = resolveWorkerLaunch(path.join(repoDir, 'viewer'), { env });
  } catch (error) {
    if (error instanceof PythonNotFoundError) return { reason: error.message };
    throw error;
  }
  const code = 'import json, sys; sys.stdout.reconfigure(encoding="utf-8"); '
    + 'from text_compositor.lints import LINTS; '
    + 'print(json.dumps({n: {"default": l.default, "label": l.label} for n, l in LINTS.items()}, ensure_ascii=False))';
  const probe = spawnSync(launch.file, ['-c', code], {
    env: { ...process.env, ...launch.env }, encoding: 'utf8', timeout: 60_000,
  });
  if (probe.status !== 0) {
    return { reason: `Pythonで、text_compositor.lintsを読み込めません: ${(probe.stderr || probe.error?.message || '').trim().split('\n').pop()}` };
  }
  return { lints: JSON.parse(probe.stdout) };
}

const python = readPythonLints();
if (python.reason && required) {
  test('text_compositor.lints can be read (REQUIRE_WORKER_INTEGRATION=1)', () => assert.fail(python.reason));
}

describe('lint list: settings screen vs text_compositor (#271)', { skip: python.reason ? `${python.reason}（飛ばします）` : false }, () => {
  test('the names are the same', () => {
    assert.deepEqual(LINTS.map((lint) => lint.name).sort(), Object.keys(python.lints).sort());
  });

  test('the defaults are the same', () => {
    for (const lint of LINTS) assert.equal(lint.default, python.lints[lint.name].default, lint.name);
  });

  test('the screen names are the same words as the Python labels', () => {
    for (const lint of LINTS) assert.equal(lint.label, python.lints[lint.name].label, lint.name);
  });
});
