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
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const USER32 = `
Add-Type -Namespace W -Name U -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool MoveWindow(System.IntPtr h, int x, int y, int w, int hh, bool r);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsZoomed(System.IntPtr h);
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
'@
$p = Get-Process electron | Where-Object MainWindowTitle | Select-Object -First 1
$h = $p.MainWindowHandle
`;

function powershell(body) {
  return execFileSync('powershell', ['-NoProfile', '-Command', USER32 + body], { encoding: 'utf8' }).trim();
}

/** ウィンドウの外枠（x, y, 幅, 高さ）と、最大化かどうか。 */
function windowState() {
  const out = powershell('$r = New-Object W.U+RECT; [W.U]::GetWindowRect($h, [ref]$r) | Out-Null; '
    + '"$($r.L) $($r.T) $($r.R - $r.L) $($r.B - $r.T) $([W.U]::IsZoomed($h))"');
  const [x, y, width, height, zoomed] = out.split(' ');
  return { x: Number(x), y: Number(y), width: Number(width), height: Number(height), maximized: zoomed === 'True' };
}

const move = (x, y, width, height) => powershell(`[W.U]::MoveWindow($h, ${x}, ${y}, ${width}, ${height}, $true) | Out-Null`);
const showMaximized = () => powershell('[W.U]::ShowWindow($h, 3) | Out-Null');
const restore = () => powershell('[W.U]::ShowWindow($h, 9) | Out-Null');

function launch(userData) {
  return spawn(electron, [`--user-data-dir=${userData}`, viewerDir, sample], { env: { ...process.env }, stdio: 'ignore' });
}

async function stop(proc) {
  spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
  await sleep(1500);
}

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
    await sleep(5000);
    move(140, 90, 900, 650);
    await sleep(1500);   // 保存は、変更が落ち着いてから（400 ms後）
    const moved = windowState();
    await stop(proc);
    proc = launch(userData);
    await sleep(5000);
    const reopened = windowState();
    check('動かした位置と大きさで、再起動後も開く', same(moved, reopened), `${JSON.stringify(moved)} → ${JSON.stringify(reopened)}`);

    // 2. 最大化したまま終了 → 再起動後も最大化。戻すと、最大化前の大きさ
    showMaximized();
    await sleep(1500);
    await stop(proc);
    proc = launch(userData);
    await sleep(5000);
    check('最大化のまま終了すると、再起動後も最大化で開く', windowState().maximized);
    restore();
    await sleep(800);
    check('最大化を戻すと、最大化する前の大きさになる', same(windowState(), moved), JSON.stringify(windowState()));
    await stop(proc);

    // 3. 保存された位置が、どの画面にも収まらない
    const saved = JSON.parse(fs.readFileSync(settingsFile, 'utf8'));
    saved.window = { x: 15000, y: 15000, width: 800, height: 600, maximized: false };
    fs.writeFileSync(settingsFile, JSON.stringify(saved));
    proc = launch(userData);
    await sleep(5000);
    const offscreen = windowState();
    check('画面の外の位置は使わず、大きさだけ戻す', offscreen.x < 15000 && near(offscreen.width, 800) && near(offscreen.height, 600), JSON.stringify(offscreen));
    await stop(proc);

    // 4. 壊れた設定ファイル
    fs.writeFileSync(settingsFile, '{ broken');
    proc = launch(userData);
    await sleep(5000);
    const fallback = windowState();
    check('壊れた設定でも、既定の大きさ（1000×800）で開く', near(fallback.width, 1000) && near(fallback.height, 800), JSON.stringify(fallback));
  } finally {
    if (proc) await stop(proc);
    try { fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch { /* 一時ファイルが残るだけ */ }
  }
  console.log(failures === 0 ? '\nすべて成功' : `\n失敗 ${failures} 件`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
