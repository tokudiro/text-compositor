'use strict';
// ワーカーが返す診断（{severity, message, file, line, detail}）を、画面に出す形にする（#190）。

const path = require('node:path');

const ORDER = { error: 0, warning: 1, hint: 2, info: 3 };

/** 「ファイル名:行」。分からなければ、空文字列。 */
function formatLocation(file, line) {
  if (!file) return '';
  const name = path.basename(file);
  return line ? `${name}:${line}` : name;
}

/**
 * 画面に出す診断だけを、重大度の順（エラー、警告、ヒント）に並べる。
 * `info`は、内部の動作の記録（ブラウザの再利用等）のため、画面には出さない。
 */
function visibleDiagnostics(diagnostics) {
  return diagnostics
    .filter((d) => d.severity !== 'info')
    .map((d, index) => ({ d, index }))
    .sort((a, b) => (ORDER[a.d.severity] ?? 9) - (ORDER[b.d.severity] ?? 9) || a.index - b.index)
    .map(({ d }) => ({
      severity: d.severity,
      message: d.message,
      location: formatLocation(d.file, d.line),
      detail: d.detail ?? null,
    }));
}

/**
 * 画面に渡す、診断の要約。
 * banner: 最初のエラーの内容と位置（エラーが無ければ、空文字列）。warnings: 警告の数。
 */
function summarize(diagnostics) {
  const items = visibleDiagnostics(diagnostics);
  const firstError = items.find((d) => d.severity === 'error');
  return {
    items,
    banner: firstError ? (firstError.location ? `${firstError.message}（${firstError.location}）` : firstError.message) : '',
    hasError: Boolean(firstError),
    warnings: items.filter((d) => d.severity === 'warning').length,
  };
}

module.exports = { formatLocation, visibleDiagnostics, summarize };
