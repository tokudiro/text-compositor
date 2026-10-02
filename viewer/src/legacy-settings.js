'use strict';
// 改名（Obunzu → Obunzu Markdown Viewer、#394）の前の設定を、新しい置き場所へ引き継ぐ。
//
// Electronのユーザーデータ（settings.jsonの置き場所）は、アプリ名（package.jsonのproductName）で決まる。
// 名前を変えると、置き場所も変わり、利用者の設定（ウィンドウの位置・テーマなど）が、初期値に戻ってしまう。
// そのため、新しい置き場所に設定がなく、旧名の置き場所にあるときだけ、settings.jsonを、1回だけ写す。
// 旧名の置き場所は、消さない（旧版へ戻したときも、設定が残るように）。ChromiumのキャッシュやCookieは、引き継がない。

const fs = require('node:fs');
const path = require('node:path');

const LEGACY_APP_NAME = 'Obunzu';
const SETTINGS_FILE = 'settings.json';

/**
 * @param {{userData: string, appData: string, legacyName?: string, fsApi?: typeof fs}} options
 * @returns {boolean} 写したときは、true
 */
function migrateLegacySettings({ userData, appData, legacyName = LEGACY_APP_NAME, fsApi = fs }) {
  const target = path.join(userData, SETTINGS_FILE);
  const source = path.join(appData, legacyName, SETTINGS_FILE);
  // 旧名と新名が、同じ置き場所のときは、何もしない
  if (path.resolve(path.dirname(source)) === path.resolve(userData)) return false;
  try {
    if (fsApi.existsSync(target) || !fsApi.existsSync(source)) return false;
    fsApi.mkdirSync(userData, { recursive: true });
    fsApi.copyFileSync(source, target);
    return true;
  } catch {
    return false;   // 引き継げなくても、起動は妨げない（設定は、初期値になる）
  }
}

module.exports = { migrateLegacySettings, LEGACY_APP_NAME };
