'use strict';
// ウィンドウの大きさ・位置が、再起動後も戻ることを確認する（手動。Windowsのみ。#192）。
//   TEXT_COMPOSITOR_PYTHON=<python> TEXT_COMPOSITOR_PYTHONPATH=<repo> node scripts/check-window-state.js
//
// 確認すること:
//   - 動かした・大きさを変えたウィンドウが、再起動後に、同じ位置・大きさで開く。
//   - 最大化したまま終了すると、再起動後も最大化で開き、戻すと、最大化する前の大きさになる。
//   - 保存された位置が、今のどの画面にも収まらないときは、大きさだけ戻り、画面の外に開かない。
//   - 壊れた設定ファイルでも、既定の大きさで開く。
// ウィンドウの操作は、PowerShell（user32）で行う。実行中は、ほかのウィンドウを操作しないこと。

const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

if (process.platform !== 'win32') {
  console.log('このスクリプトは、Windowsでだけ動きます。');
  process.exit(0);
}

const viewerDir = path.resolve(__dirname, '..');
const electron = require('electron');
const sample = path.join(viewerDir, '..', 'benchmarks', 'html-view', 'fixture', 'fixture.md');
const { waitFor, waitExit } = require('./wait-for');

const user32 = (pid) => `
Add-Type -Namespace W -Name U -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool MoveWindow(System.IntPtr h, int x, int y, int w, int hh, bool r);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsZoomed(System.IntPtr h);
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
'@
$p = Get-Process -Id ${pid}
$h = $p.MainWindowHandle
`;

function powershell(proc, body) {
  return execFileSync('powershell', ['-NoProfile', '-Command', user32(proc.pid) + body], { encoding: 'utf8' }).trim();
}

/** ウィンドウの外枠（x, y, 幅, 高さ）と、最大化かどうか。 */
function windowState(proc) {
  const out = powershell(proc, '$r = New-Object W.U+RECT; [W.U]::GetWindowRect($h, [ref]$r) | Out-Null; '
    + '"$($r.L) $($r.T) $($r.R - $r.L) $($r.B - $r.T) $([W.U]::IsZoomed($h))"');
  const [x, y, width, height, zoomed] = out.split(' ');
  return { x: Number(x), y: Number(y), width: Number(width), height: Number(height), maximized: zoomed === 'True' };
}

const move = (proc, x, y, width, height) => powershell(proc, `[W.U]::MoveWindow($h, ${x}, ${y}, ${width}, ${height}, $true) | Out-Null`);
const showMaximized = (proc) => powershell(proc, '[W.U]::ShowWindow($h, 3) | Out-Null');
const restore = (proc) => powershell(proc, '[W.U]::ShowWindow($h, 9) | Out-Null');

function launch(userData) {
  return spawn(electron, [`--user-data-dir=${userData}`, viewerDir, sample], { env: { ...process.env }, stdio: 'ignore' });
}

async function stop(proc) {
  spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
  await waitExit(proc);
}

/** ウィンドウが出て、大きさが落ち着く（続けて2回、同じ）まで待つ。固定の時間の代わり。 */
async function waitWindow(proc) {
  let last = null;
  await waitFor(() => {
    const state = windowState(proc);
    const settled = state.width > 0 && last && JSON.stringify(state) === JSON.stringify(last);
    last = state;
    return settled;
  }, { timeout: 30000, interval: 200, label: 'ウィンドウの表示' });
}

/** 設定ファイルに保存されたウィンドウの状態が、条件を満たすまで待つ（保存は、変更が落ち着いてから）。 */
const waitSaved = (settingsFile, predicate) => waitFor(() => {
  try { return predicate(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).window ?? {}); } catch { return false; }
}, { timeout: 5000, label: '設定の保存' }).catch(() => {});

async function main() {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'obunzu-window-state-'));
  const settingsFile = path.join(userData, 'settings.json');
  let failures = 0;
  const check = (name, ok, detail = '') => {
    if (!ok) failures += 1;
    console.log(`${ok ? 'OK  ' : 'NG  '} ${name}${detail ? `  ${detail}` : ''}`);
  };
  const near = (a, b) => Math.abs(a - b) <= 2;
  const same = (a, b) => near(a.x, b.x) && near(a.y, b.y) && near(a.width, b.width) && near(a.height, b.height);
  let proc = null;
  try {
    // 1. 動かして、大きさを変える → 再起動
    proc = launch(userData);
    await waitWindow(proc);
    move(proc, 140, 90, 900, 650);
    await waitSaved(settingsFile, (w) => w.width > 0 && w.maximized === false && near(w.width, 900));
    const moved = windowState(proc);
    await stop(proc);
    proc = launch(userData);
    await waitWindow(proc);
    const reopened = windowState(proc);
    check('動かした位置と大きさで、再起動後も開く', same(moved, reopened), `${JSON.stringify(moved)} → ${JSON.stringify(reopened)}`);

    // 2. 最大化したまま終了 → 再起動後も最大化。戻すと、最大化前の大きさ
    showMaximized(proc);
    await waitSaved(settingsFile, (w) => w.maximized === true);
    await stop(proc);
    proc = launch(userData);
    await waitWindow(proc);
    check('最大化のまま終了すると、再起動後も最大化で開く', windowState(proc).maximized);
    restore(proc);
    await waitFor(() => !windowState(proc).maximized, { timeout: 5000, interval: 200, label: '最大化の解除' }).catch(() => {});
    check('最大化を戻すと、最大化する前の大きさになる', same(windowState(proc), moved), JSON.stringify(windowState(proc)));
    await stop(proc);

    // 3. 保存された位置が、どの画面にも収まらない
    const saved = JSON.parse(fs.readFileSync(settingsFile, 'utf8'));
    saved.window = { x: 15000, y: 15000, width: 800, height: 600, maximized: false };
    fs.writeFileSync(settingsFile, JSON.stringify(saved));
    proc = launch(userData);
    await waitWindow(proc);
    const offscreen = windowState(proc);
    check('画面の外の位置は使わず、大きさだけ戻す', offscreen.x < 15000 && near(offscreen.width, 800) && near(offscreen.height, 600), JSON.stringify(offscreen));
    await stop(proc);

    // 4. 壊れた設定ファイル
    fs.writeFileSync(settingsFile, '{ broken');
    proc = launch(userData);
    await waitWindow(proc);
    const fallback = windowState(proc);
    check('壊れた設定でも、既定の大きさ（1000×800）で開く', near(fallback.width, 1000) && near(fallback.height, 800), JSON.stringify(fallback));
  } finally {
    if (proc) await stop(proc);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
