# 計測スクリプトの共通の部品（#180）。`. .\bench-lib.ps1`で読み込む。

function Get-Tree([int[]]$Roots) {
    $all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId
    $found = New-Object System.Collections.Generic.HashSet[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    foreach ($r in $Roots) { if ($found.Add($r)) { $queue.Enqueue($r) } }
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $cur }) {
            if ($found.Add([int]$c.ProcessId)) { $queue.Enqueue([int]$c.ProcessId) }
        }
    }
    return @($found)
}

function Get-Cpu([int[]]$Pids) {
    $sum = 0.0
    foreach ($id in $Pids) { try { $sum += (Get-Process -Id $id -ErrorAction Stop).TotalProcessorTime.TotalSeconds } catch {} }
    return $sum
}

# プロセスツリーの、プロセス数・ワーキングセット・プライベートなワーキングセット（MB）。
function Measure-Tree([int[]]$Roots) {
    $pids = Get-Tree $Roots
    $perf = @(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | Where-Object { $pids -contains [int]$_.IDProcess })
    $ws = 0.0
    foreach ($id in $pids) { try { $ws += (Get-Process -Id $id -ErrorAction Stop).WorkingSet64 } catch {} }
    return [pscustomobject]@{
        Pids = $pids
        Procs = $pids.Count
        WsMb = $ws / 1MB
        PwsMb = ($perf | Measure-Object -Property WorkingSetPrivate -Sum).Sum / 1MB
    }
}

function Stop-Tree([int[]]$Roots) {
    foreach ($id in (Get-Tree $Roots)) { try { Stop-Process -Id $id -Force -ErrorAction Stop } catch {} }
}

function Remove-Dir([string]$Path) {
    if (Test-Path $Path) { try { [System.IO.Directory]::Delete($Path, $true) } catch {} }
}

# 待機中のCPU使用率（1コアに対する％）。
function Measure-IdleCpu([int[]]$Roots, [int]$Seconds = 5) {
    $cpu0 = Get-Cpu (Get-Tree $Roots)
    $t0 = [DateTime]::UtcNow
    Start-Sleep -Seconds $Seconds
    $cpu1 = Get-Cpu (Get-Tree $Roots)
    return (($cpu1 - $cpu0) / ([DateTime]::UtcNow - $t0).TotalSeconds) * 100
}

# CPUの落ち着きを、「読み込みが終わった」の目安にする。ツリー全体のCPU時間が、200 msあたり0.02秒未満
# （1コアの10%未満）の状態が、3回続いたら、落ち着いたとみなす。アプリが、完了を知らせない場合の代用である。
# 戻り値は、Stopwatchの経過ミリ秒。
function Wait-CpuQuiet([int[]]$Roots, $Stopwatch, [int]$TimeoutMs = 30000) {
    $quiet = 0
    $prev = Get-Cpu (Get-Tree $Roots)
    while ($Stopwatch.Elapsed.TotalMilliseconds -lt $TimeoutMs) {
        Start-Sleep -Milliseconds 200
        $cur = Get-Cpu (Get-Tree $Roots)
        if (($cur - $prev) -lt 0.02) { $quiet++ } else { $quiet = 0 }
        $prev = $cur
        if ($quiet -ge 3) { return $Stopwatch.Elapsed.TotalMilliseconds - 600 }
    }
    return $null
}

# ウィンドウを最前面に出して、その内容を保存する（表示の確認用）。
function Save-WindowShot([int]$ProcessId, [string]$Path) {
    Add-Type -AssemblyName System.Drawing
    if (-not ('BenchWin' -as [type])) {
        Add-Type @"
using System; using System.Runtime.InteropServices;
public class BenchWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int attr, out RECT r, int size);
}
"@
    }
    [BenchWin]::SetProcessDPIAware() | Out-Null
    $p = Get-Process -Id $ProcessId
    $h = $p.MainWindowHandle
    if ($h -eq [IntPtr]::Zero) { return $false }
    [BenchWin]::SetWindowPos($h, [IntPtr](-1), 40, 40, 0, 0, 0x41) | Out-Null
    [BenchWin]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 800
    $r = New-Object BenchWin+RECT
    [BenchWin]::DwmGetWindowAttribute($h, 9, [ref]$r, [System.Runtime.InteropServices.Marshal]::SizeOf($r)) | Out-Null
    $w = ($r.R - $r.L) - 8; $ht = ($r.B - $r.T) - 7
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.L + 4, $r.T + 3, 0, 0, (New-Object System.Drawing.Size $w, $ht))
    $g.Dispose(); $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    return $true
}

function Write-Stat($Rows, [string]$Name) {
    $v = @($Rows | Where-Object { $null -ne $_.$Name } | ForEach-Object { [double]$_.$Name })
    if ($v.Count -eq 0) { return }
    $rest = if ($v.Count -gt 1) { $v[1..($v.Count - 1)] } else { $v }
    $m = $rest | Measure-Object -Average -Minimum -Maximum
    "{0,-20} 1回目={1,9:N1}  2回目以降 mean={2,9:N1} min={3,9:N1} max={4,9:N1}" -f $Name, $v[0], $m.Average, $m.Minimum, $m.Maximum
}
