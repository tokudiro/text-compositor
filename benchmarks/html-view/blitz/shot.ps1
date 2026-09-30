# 試作アプリを起動して、ウィンドウのスクリーンショットを撮る。使い方: pwsh -File shot.ps1 <html> <png>
param([string]$Html, [string]$Png, [int]$PageDowns = 0)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class W2 { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 public struct RECT { public int L, T, R, B; } }
'@
$exe = Join-Path $PSScriptRoot 'target\release\native-blitz.exe'
$p = Start-Process $exe -ArgumentList "`"$Html`"" -PassThru
for ($i = 0; $i -lt 100 -and $p.MainWindowHandle -eq 0; $i++) { Start-Sleep -Milliseconds 100; $p.Refresh() }
Start-Sleep 5; $p.Refresh()
[W2]::SetForegroundWindow($p.MainWindowHandle) | Out-Null; Start-Sleep 1
for ($k = 0; $k -lt $PageDowns; $k++) { [System.Windows.Forms.SendKeys]::SendWait("{PGDN}"); Start-Sleep -Milliseconds 400 }
Start-Sleep 1
$r = New-Object W2+RECT; [W2]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save($Png)
Stop-Process $p -Force
