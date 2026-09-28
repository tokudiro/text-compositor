'use strict';
// 文書内検索（#325）の、DOMに依存しない部分。文字列検索・正規表現検索の両方を、同じ形（RegExp）にそろえる。

/**
 * 検索語から、検索に使うRegExpを作る。空の検索語は、検索なし（null）として扱う。
 * 通常の文字列検索も、正規表現の特殊文字を無効化したうえで、内部ではRegExpにそろえる
 * （ハイライトの実装を、1本にするため。issue #325の「実装上の注意」）。
 * @returns {{ ok: true, regex: RegExp|null } | { ok: false, error: string }}
 */
function buildMatcher(query, { regex = false, caseSensitive = false } = {}) {
  if (!query) return { ok: true, regex: null };
  const source = regex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  try {
    return { ok: true, regex: new RegExp(source, caseSensitive ? 'g' : 'gi') };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

/**
 * 1つの文字列の中から、一致する範囲（{start, end}）をすべて探す。
 * 空文字列に一致する正規表現（`a*`など）は、無限ループになるため、1文字分進めて続ける。
 * 病的な正規表現（破滅的バックトラッキング等）そのものへの対策ではないが、1つのテキストノード
 * （文書中の1つの地の文・1行程度）の範囲に限られるため、影響は小さい。件数にも、上限を設ける。
 */
function findMatches(text, matcherRegex) {
  if (!matcherRegex || !text) return [];
  const matches = [];
  matcherRegex.lastIndex = 0;
  let match;
  while ((match = matcherRegex.exec(text))) {
    if (match[0].length === 0) {
      matcherRegex.lastIndex += 1;
      if (matcherRegex.lastIndex > text.length) break;
      continue;
    }
    matches.push({ start: match.index, end: match.index + match[0].length });
    if (matches.length >= 5000) break;
  }
  return matches;
}

module.exports = { buildMatcher, findMatches };
