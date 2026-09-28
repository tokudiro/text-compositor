'use strict';
const assert = require('node:assert/strict');
const { describe, test } = require('node:test');

const { buildMatcher, findMatches } = require('../src/search-match');

describe('buildMatcher', () => {
  test('empty query means no search', () => {
    assert.deepEqual(buildMatcher(''), { ok: true, regex: null });
  });

  test('plain text search escapes regex special characters', () => {
    const { ok, regex } = buildMatcher('a.b*c', { regex: false });
    assert.equal(ok, true);
    assert.deepEqual(findMatches('x a.b*c y aXbYc', regex), [{ start: 2, end: 7 }]);
  });

  test('plain text search is case-insensitive by default', () => {
    const { regex } = buildMatcher('abc');
    assert.deepEqual(findMatches('xxABCxx', regex), [{ start: 2, end: 5 }]);
  });

  test('caseSensitive option makes plain text search case-sensitive', () => {
    const { regex } = buildMatcher('abc', { caseSensitive: true });
    assert.deepEqual(findMatches('xxABCxxabcxx', regex), [{ start: 7, end: 10 }]);
  });

  test('regex mode interprets the query as a regular expression', () => {
    const { ok, regex } = buildMatcher('a.c', { regex: true });
    assert.equal(ok, true);
    assert.deepEqual(findMatches('abc axc a.c', regex), [{ start: 0, end: 3 }, { start: 4, end: 7 }, { start: 8, end: 11 }]);
  });

  test('regex mode respects caseSensitive too', () => {
    const { regex } = buildMatcher('A.C', { regex: true, caseSensitive: true });
    assert.deepEqual(findMatches('abc ABC', regex), [{ start: 4, end: 7 }]);
  });

  test('invalid regex reports the error instead of throwing', () => {
    const result = buildMatcher('a(b', { regex: true });
    assert.equal(result.ok, false);
    assert.equal(typeof result.error, 'string');
  });
});

describe('findMatches', () => {
  test('no matcher or empty text means no matches', () => {
    assert.deepEqual(findMatches('abc', null), []);
    assert.deepEqual(findMatches('', /a/g), []);
  });

  test('zero-length matches do not loop forever and each position counts once', () => {
    const { regex } = buildMatcher('a*', { regex: true });
    const matches = findMatches('baab', regex);
    assert.deepEqual(matches, [{ start: 1, end: 3 }]);
  });

  test('overlapping-looking adjacent matches are all found', () => {
    const { regex } = buildMatcher('aa', { regex: false });
    assert.deepEqual(findMatches('aaaa', regex), [{ start: 0, end: 2 }, { start: 2, end: 4 }]);
  });
});
