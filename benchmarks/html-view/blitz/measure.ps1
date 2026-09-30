# Blitz試作の起動時間（#382）。「ウィンドウが出るまで」と「本文の文字が見えるまで」を測る。
# 文字が見える = タイトルバーの下の領域に、暗い画素（本文の文字）が現れた時点。白い画面が見える時間の目安。
# 使い方: pwsh -File measure.ps1 -Html <html> -IdleSeconds 180 -Label idle-3min
param([string]$Html, [int]$IdleSeconds = 0, [string]$Label = '', [int]$Runs = 1)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class W3 { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 public struct RECT { public int L, T, R, B; } }
'@
$exe = Join-Path $PSScriptRoot 'target\release\native-blitz.exe'
$csv = Join-Path $PSScriptRoot 'measure-results.csv'
if (-not (Test-Path $csv)) { 'time,label,idle_s,run,window_ms,text_ms' | Set-Content $csv }

function Test-Text($r) {
  # タイトルバー（約32px）の下の、幅400 x 高さ200の領域を、8px刻みで調べる
  $x0 = $r.L + 30; $y0 = $r.T + 60; $w = 400; $h = 200
  $bmp = New-Object System.Drawing.Bitmap $w, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($x0, $y0, 0, 0, $bmp.Size)
  $found = $false
  for ($y = 0; $y -lt $h -and -not $found; $y += 4) { for ($x = 0; $x -lt $w; $x += 4) { $c = $bmp.GetPixel($x, $y); if (($c.R + $c.G + $c.B) -lt 300) { $found = $true; break } } }
  $g.Dispose(); $bmp.Dispose(); return $found
}

if ($IdleSeconds -gt 0) { Start-Sleep $IdleSeconds }
for ($n = 1; $n -le $Runs; $n++) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process $exe -ArgumentList "`"$Html`"" -PassThru
  $win = $null; $text = $null
  while ($sw.ElapsedMilliseconds -lt 20000 -and $null -eq $text) {
    $p.Refresh()
    if ($p.MainWindowHandle -ne 0) {
      if ($null -eq $win) { $win = $sw.ElapsedMilliseconds }
      $r = New-Object W3+RECT; [W3]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
      if (Test-Text $r) { $text = $sw.ElapsedMilliseconds }
    } else { Start-Sleep -Milliseconds 2 }
  }
  $line = '{0},{1},{2},{3},{4},{5}' -f (Get-Date -Format s), $Label, $IdleSeconds, $n, $win, $text
  Add-Content $csv $line
  Write-Output ("run {0}: window {1} ms, text visible {2} ms" -f $n, $win, $text)
  Stop-Process $p -Force; Start-Sleep 2
}
