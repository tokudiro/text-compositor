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
 * 複数行のメッセージは、1行目を要約（message）、残りを詳細（detail）にする（#202）。
 * 帯には要約だけを出し、長い原文は、詳細の一覧にだけ出す。同じ文が、2か所に出ないようにするため。
 */
function splitMessage(message, detail) {
  const [head, ...rest] = String(message ?? '').split('\n');
  const extra = rest.join('\n').trim();
  return { message: head.trim(), detail: [extra, detail].filter(Boolean).join('\n') || null };
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
      ...splitMessage(d.message, d.detail),
      location: formatLocation(d.file, d.line),
    }));
}

/** 「要約（位置）」。位置が分からなければ、要約だけ。 */
function withLocation(item) {
  return item.location ? `${item.message}（${item.location}）` : item.message;
}

/**
 * 画面に渡す、診断の要約。
 * banner: 最初のエラーの要約と位置（エラーが無ければ、空文字列）。
 * warningBanner: 最初の警告の要約と位置。errors・warnings: それぞれの数。
 */
function summarize(diagnostics) {
  const items = visibleDiagnostics(diagnostics);
  const firstError = items.find((d) => d.severity === 'error');
  const firstWarning = items.find((d) => d.severity === 'warning');
  return {
    items,
    banner: firstError ? withLocation(firstError) : '',
    warningBanner: firstWarning ? withLocation(firstWarning) : '',
    hasError: Boolean(firstError),
    errors: items.filter((d) => d.severity === 'error').length,
    warnings: items.filter((d) => d.severity === 'warning').length,
  };
}

module.exports = { formatLocation, splitMessage, visibleDiagnostics, summarize };
