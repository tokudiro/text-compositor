'use strict';
// 確認スクリプトの待ちを、固定の時間ではなく、条件にする（#557）。
// 条件が真（または、値が返る）になるまで、間隔をあけて呼ぶ。時間切れになったら、例外を投げる（条件の見落としで、無限に待たないため）。

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(condition, { timeout = 30000, interval = 100, label = '条件' } = {}) {
  const start = Date.now();
  let lastError = null;
  for (;;) {
    try {
      const value = await condition();
      if (value) return value;
      lastError = null;
    } catch (error) {
      lastError = error;   // 起動の途中は、接続や評価が失敗する。時間切れまで、やり直す
    }
    if (Date.now() - start > timeout) {
      throw new Error(`${label}が、${timeout}ms以内に満たされませんでした${lastError ? `（${lastError.message}）` : ''}`);
    }
    await sleep(interval);
  }
}

module.exports = { waitFor, sleep };
