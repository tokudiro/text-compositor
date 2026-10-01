# 試作アプリを起動して、ウィンドウのスクリーンショットを撮る。使い方: pwsh -File shot.ps1 <html> <png> [-PageDowns N] [-Wheel N] [-Dark]
param([string]$Html, [string]$Png, [int]$PageDowns = 0, [int]$Wheel = 0, [switch]$Dark)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class W2 { [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, int d, UIntPtr e); [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 public struct RECT { public int L, T, R, B; } }
'@
$exe = Join-Path $PSScriptRoot 'target\release\native-blitz.exe'
$argList = @("`"$Html`""); if ($Dark) { $argList = @("--dark") + $argList }
$p = Start-Process $exe -ArgumentList $argList -PassThru
for ($i = 0; $i -lt 100 -and $p.MainWindowHandle -eq 0; $i++) { Start-Sleep -Milliseconds 100; $p.Refresh() }
Start-Sleep 5; $p.Refresh()
# 他のウィンドウが写り込まないよう、最前面に固定する（SWP_NOMOVE | SWP_NOSIZE）
[W2]::SetWindowPos($p.MainWindowHandle, [IntPtr](-1), 0, 0, 0, 0, 3) | Out-Null
[W2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null; Start-Sleep 1
for ($k = 0; $k -lt $PageDowns; $k++) { [System.Windows.Forms.SendKeys]::SendWait("{PGDN}"); Start-Sleep -Milliseconds 400 }
Start-Sleep 1
if ($Wheel -ne 0) {
  $r0 = New-Object W2+RECT; [W2]::GetWindowRect($p.MainWindowHandle, [ref]$r0) | Out-Null
  [W2]::SetCursorPos([int](($r0.L + $r0.R) / 2), [int](($r0.T + $r0.B) / 2)) | Out-Null
  for ($k = 0; $k -lt [math]::Abs($Wheel); $k++) { [W2]::mouse_event(0x0800, 0, 0, [math]::Sign(-$Wheel) * 120, [UIntPtr]::Zero); Start-Sleep -Milliseconds 150 }
  Start-Sleep 1
}
$r = New-Object W2+RECT; [W2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save($Png)
Stop-Process $p -Force
