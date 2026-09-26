'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const {
  resolveWorkerLaunch, PythonNotFoundError, PYTHON_ENV, PYTHONPATH_ENV, FONT_DIR_ENV, TYPST_PACKAGES_ENV,
  JAVA_BIN_ENV, PLANTUML_JAR_ENV, D2_BIN_ENV, STRUCTURIZR_CLI_LIB_ENV, MERMAID_JS_ENV,
} = require('../src/python');

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

  test('the bundled fonts and Typst packages are handed to the worker (#263)', () => {
    const python = path.join(path.sep, 'py', 'python');
    const fonts = path.join(APP, 'fonts');
    const packages = path.join(APP, 'typst-packages');
    const launch = resolveWorkerLaunch(APP, { env: { [PYTHON_ENV]: python }, exists: existsIn(python, fonts, packages) });
    assert.deepEqual(launch.env, { [FONT_DIR_ENV]: fonts, [TYPST_PACKAGES_ENV]: packages });
  });

  test('bundled Java, plantuml.jar, D2 and structurizr-cli are handed to the worker (#290)', () => {
    const python = path.join(path.sep, 'py', 'python');
    const java = path.join(APP, 'jre', 'bin', 'java.exe');
    const plantumlJar = path.join(APP, 'plantuml', 'plantuml.jar');
    const d2 = path.join(APP, 'd2', 'd2.exe');
    const structurizrLib = path.join(APP, 'structurizr-cli', 'lib');
    const launch = resolveWorkerLaunch(APP, {
      env: { [PYTHON_ENV]: python },
      exists: existsIn(python, java, plantumlJar, d2, structurizrLib),
      platform: 'win32',
    });
    assert.deepEqual(launch.env, {
      [JAVA_BIN_ENV]: java, [PLANTUML_JAR_ENV]: plantumlJar, [D2_BIN_ENV]: d2, [STRUCTURIZR_CLI_LIB_ENV]: structurizrLib,
    });
  });

  test('a value already set by the user wins over the bundled diagram tools too', () => {
    const python = path.join(path.sep, 'py', 'python');
    const java = path.join(APP, 'jre', 'bin', 'java.exe');
    const launch = resolveWorkerLaunch(APP, {
      env: { [PYTHON_ENV]: python, [JAVA_BIN_ENV]: '/my/java' },
      exists: existsIn(python, java),
      platform: 'win32',
    });
    assert.equal(launch.env[JAVA_BIN_ENV], undefined);
  });

  test('bundled mermaid.min.js is handed to the worker too (#310)', () => {
    const python = path.join(path.sep, 'py', 'python');
    const mermaidJs = path.join(APP, 'mermaid', 'mermaid.min.js');
    const launch = resolveWorkerLaunch(APP, {
      env: { [PYTHON_ENV]: python },
      exists: existsIn(python, mermaidJs),
    });
    assert.deepEqual(launch.env, { [MERMAID_JS_ENV]: mermaidJs });
  });

  test('only the folders that exist are passed, and a value set by the user wins', () => {
    const python = path.join(path.sep, 'py', 'python');
    const fonts = path.join(APP, 'fonts');
    const onlyFonts = resolveWorkerLaunch(APP, { env: { [PYTHON_ENV]: python }, exists: existsIn(python, fonts) });
    assert.deepEqual(onlyFonts.env, { [FONT_DIR_ENV]: fonts });
    const userSet = resolveWorkerLaunch(APP, { env: { [PYTHON_ENV]: python, [FONT_DIR_ENV]: '/mine' }, exists: existsIn(python, fonts) });
    assert.deepEqual(userSet.env, {});
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
