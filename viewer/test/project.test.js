'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, test } = require('node:test');

const { AGGREGATE_HINT, AGGREGATE_SUFFIX, buildProject, isInsideProject, isProjectConfigFile, projectEntries } = require('../src/project');

const config = path.resolve('work', 'text-compositor.config.yaml');
const chapter = (name) => ({ kind: 'file', name, path: path.resolve('work', 'inputs', name) });

describe('isProjectConfigFile (#373)', () => {
  test('only the names the CLI looks for are project configs', () => {
    assert.equal(isProjectConfigFile(config), true);
    assert.equal(isProjectConfigFile(path.resolve('w', 'text-compositor.config.json')), true);
    assert.equal(isProjectConfigFile(path.resolve('w', 'TEXT-COMPOSITOR.CONFIG.YAML')), true);
  });

  test('other names (even other yaml files) are plain files', () => {
    for (const name of ['config.yaml', 'settings.yml', 'text-compositor.config.yaml.bak', 'a.md']) assert.equal(isProjectConfigFile(path.resolve('w', name)), false, name);
    for (const bad of [null, undefined, 3, '']) assert.equal(isProjectConfigFile(bad), false);
  });
});

describe('buildProject / projectEntries', () => {
  test('the root lists the chapters in order; sections hold their chapters', () => {
    const project = buildProject(config, [chapter('b.md'), { kind: 'section', name: '編', children: [chapter('a.md'), chapter('c.csv')] }, chapter('d.md')]);
    assert.deepEqual(projectEntries(project, config).entries.map((e) => [e.name, e.type]), [['b.md', 'file'], ['編', 'directory'], ['d.md', 'file']]);
    const key = projectEntries(project, config).entries[1].path;
    assert.deepEqual(projectEntries(project, key).entries.map((e) => e.name), ['a.md', 'c.csv']);
  });

  test('files the viewer cannot open are left out, and so are sections that become empty', () => {
    const project = buildProject(config, [chapter('a.md'), chapter('x.docx'), { kind: 'section', name: '空', children: [chapter('y.xlsx')] }]);
    assert.deepEqual(projectEntries(project, config).entries.map((e) => e.name), ['a.md']);
  });

  test('diagram files and images are chapters when the viewer can open them', () => {
    const project = buildProject(config, [chapter('g.dot'), chapter('m.mmd'), chapter('p.png')]);
    assert.deepEqual(projectEntries(project, config).entries.map((e) => e.name), ['g.dot', 'm.mmd', 'p.png']);
  });

  test('an unknown key is a failure, not an exception', () => {
    const project = buildProject(config, [chapter('a.md')]);
    assert.equal(projectEntries(project, 'section:99').ok, false);
    assert.equal(projectEntries(null, config).ok, false);
  });

  test('a chapter that turns a folder into a table is listed as a note that cannot be opened (#478)', () => {
    const folder = path.resolve('work', 'inputs', 'testcases');
    const project = buildProject(config, [chapter('a.md'), { kind: 'aggregate', name: 'テストケース一覧', path: folder }, chapter('b.md')]);
    const entries = projectEntries(project, config).entries;
    assert.deepEqual(entries.map((e) => [e.name, e.type]), [['a.md', 'file'], ['テストケース一覧（表）', 'note'], ['b.md', 'file']]);
    assert.equal(entries[1].path, folder);
    assert.equal(entries[1].hint, AGGREGATE_HINT);
    assert.match(entries[1].hint, /PDF/);
    assert.equal(entries[1].name.endsWith(AGGREGATE_SUFFIX), true);
  });

  test('a section that holds only a table chapter is still listed (#478)', () => {
    const project = buildProject(config, [{ kind: 'section', name: '試験', children: [{ kind: 'aggregate', name: 'tc', path: path.resolve('work', 'tc') }] }]);
    const root = projectEntries(project, config).entries;
    assert.deepEqual(root.map((e) => [e.name, e.type]), [['試験', 'directory']]);
    assert.deepEqual(projectEntries(project, root[0].path).entries.map((e) => [e.name, e.type]), [['tc（表）', 'note']]);
  });

  test('a table chapter is not a file of the project: opening its folder leaves the chapter list (#478)', () => {
    const folder = path.resolve('work', 'inputs', 'testcases');
    const project = buildProject(config, [chapter('a.md'), { kind: 'aggregate', name: 'tc', path: folder }]);
    assert.equal(isInsideProject(project, folder), false);
    assert.equal(isInsideProject(project, path.join(folder, 'TC-001.yaml')), false);
  });

  test('a table chapter without a name is ignored, and a missing path does not break it (#478)', () => {
    const project = buildProject(config, [{ kind: 'aggregate' }, { kind: 'aggregate', name: '' }, { kind: 'aggregate', name: 'x' }, chapter('ok.md')]);
    const entries = projectEntries(project, config).entries;
    assert.deepEqual(entries.map((e) => e.name), ['x（表）', 'ok.md']);
    assert.equal(entries[0].path, '');
  });

  test('malformed items are ignored', () => {
    const project = buildProject(config, [{ kind: 'file', name: 'a.md' }, { kind: 'section', name: 's' }, { kind: 'other' }, chapter('ok.md')]);
    assert.deepEqual(projectEntries(project, config).entries.map((e) => e.name), ['ok.md']);
  });
});

describe('isInsideProject', () => {
  const project = buildProject(config, [chapter('a.md'), { kind: 'section', name: 's', children: [chapter('b.md')] }]);

  test('the chapters and the config file itself are inside', () => {
    assert.equal(isInsideProject(project, path.resolve('work', 'inputs', 'a.md')), true);
    assert.equal(isInsideProject(project, path.resolve('work', 'inputs', 'b.md')), true);
    assert.equal(isInsideProject(project, config), true);
  });

  test('other files are outside, even in the same folder', () => {
    assert.equal(isInsideProject(project, path.resolve('work', 'inputs', 'other.md')), false);
    assert.equal(isInsideProject(project, path.resolve('elsewhere', 'a.md')), false);
    assert.equal(isInsideProject(null, config), false);
    assert.equal(isInsideProject(project, 'a.md'), false);
  });

  test('the comparison ignores case on Windows only', () => {
    const upper = path.resolve('work', 'inputs', 'A.MD');
    assert.equal(isInsideProject(project, upper), process.platform === 'win32');
  });
});
