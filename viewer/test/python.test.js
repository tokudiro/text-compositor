'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const { resolveWorkerLaunch, PythonNotFoundError, PYTHON_ENV, PYTHONPATH_ENV } = require('../src/python');

const APP = path.join(path.sep, 'app');
const existsIn = (...files) => {
  const set = new Set(files);
  return (p) => set.has(p);
};

describe('resolveWorkerLaunch', () => {
  test('the environment variable wins, and the worker is started as a module', () => {
    const python = path.join(path.sep, 'py', 'python');
    const launch = resolveWorkerLaunch(APP, {
      env: { [PYTHON_ENV]: python },
      exists: existsIn(python, path.join(APP, 'python-embed', 'python.exe')),
    });
    assert.equal(launch.file, python);
    assert.deepEqual(launch.args, ['-m', 'text_compositor.worker']);
    assert.deepEqual(launch.env, {});
  });

  test('a missing python from the environment variable is an error, not a fallback', () => {
    assert.throws(
      () => resolveWorkerLaunch(APP, {
        env: { [PYTHON_ENV]: '/nope/python' },
        exists: existsIn(path.join(APP, 'python-embed', 'python.exe')),
      }),
      (error) => error instanceof PythonNotFoundError && error.message.includes(PYTHON_ENV));
  });

  test('the embedded python is preferred over PATH', () => {
    const embedded = path.join(APP, 'python-embed', 'python.exe');
    const onPath = path.join(path.sep, 'bin', 'python.exe');
    const launch = resolveWorkerLaunch(APP, {
      env: { PATH: path.dirname(onPath) }, exists: existsIn(embedded, onPath), platform: 'win32',
    });
    assert.equal(launch.file, embedded);
  });

  test('PATH is searched last', () => {
    const wanted = path.join(path.sep, 'two', 'python3');
    const launch = resolveWorkerLaunch(APP, {
      env: { PATH: [path.join(path.sep, 'one'), path.join(path.sep, 'two')].join(path.delimiter) },
      exists: existsIn(wanted), platform: 'linux',
    });
    assert.equal(launch.file, wanted);
  });

  test('not found explains how to fix it', () => {
    assert.throws(
      () => resolveWorkerLaunch(APP, { env: { PATH: path.join(path.sep, 'bin') }, exists: () => false }),
      (error) => error instanceof PythonNotFoundError && error.message.includes('TEXT_COMPOSITOR_PYTHON'));
  });

  test('the python path variable is prepended to the workers PYTHONPATH', () => {
    const python = path.join(path.sep, 'py', 'python');
    const launch = resolveWorkerLaunch(APP, {
      env: { [PYTHON_ENV]: python, [PYTHONPATH_ENV]: '/repo', PYTHONPATH: '/other' },
      exists: existsIn(python),
    });
    assert.equal(launch.env.PYTHONPATH, `/repo${path.delimiter}/other`);
  });
});
