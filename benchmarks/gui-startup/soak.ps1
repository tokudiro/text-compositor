param([string]$Exe, [string]$Pdf, [int]$N = 1500, [string]$Label = "")
# アプリに、PDFのページをN回描き直させ（環境変数SOAK）、その間のメモリ（ワーキングセットと専用メモリ）を、
# 0.5秒ごとに記録する。終了の様子（正常終了か、クラッシュか）も記録する。
$env:SOAK = "$N"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Exe; $psi.Arguments = "`"$Pdf`""; $psi.WorkingDirectory = Split-Path $Exe
$psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$p = [System.Diagnostics.Process]::Start($psi)
$samples = New-Object System.Collections.ArrayList
$started = $false; $ended = $false; $lastSample = -1.0
$task = $p.StandardOutput.ReadLineAsync()
function Drain {
    while ($task.IsCompleted) {
        $line = $task.Result
        if ($null -eq $line) { $script:task = $null; return }
        if ($line -eq "soak_start") { $script:started = $true; $script:sw.Restart(); $script:lastSample = -1.0 }
        if ($line -eq "soak_end") { $script:ended = $true }
        $script:task = $p.StandardOutput.ReadLineAsync()
    }
}
while (-not $p.HasExited) {
    if ($null -ne $task) { Drain }
    if ($started -and ($sw.Elapsed.TotalSeconds - $lastSample) -ge 0.5) {
        $p.Refresh()
        [void]$samples.Add([pscustomobject]@{ t = [math]::Round($sw.Elapsed.TotalSeconds, 1); ws = $p.WorkingSet64 * 1e-6; priv = $p.PrivateMemorySize64 * 1e-6 })
        $lastSample = $sw.Elapsed.TotalSeconds
    }
    Start-Sleep -Milliseconds 50
}
$p.WaitForExit()
if ($null -ne $task) { Start-Sleep -Milliseconds 200; Drain }
Remove-Item Env:SOAK -ErrorAction SilentlyContinue
"== $Label  N=$N  exit=$($p.ExitCode)  completed=$ended  duration=$([math]::Round($sw.Elapsed.TotalSeconds,1))s  samples=$($samples.Count)"
if ($samples.Count -ge 4) {
    $q = [math]::Floor($samples.Count / 4)
    foreach ($i in 0, $q, (2 * $q), (3 * $q), ($samples.Count - 1)) {
        $s = $samples[$i]; "  t={0,5}s  working set={1,7:N0} MB  private={2,7:N0} MB" -f $s.t, $s.ws, $s.priv
    }
    $first = ($samples | Select-Object -First 3 | Measure-Object ws -Average).Average
    $last = ($samples | Select-Object -Last 3 | Measure-Object ws -Average).Average
    $maxws = ($samples | Measure-Object ws -Maximum).Maximum
    "  max working set={0:N0} MB, growth (first 3 samples -> last 3 samples)={1:N0} MB" -f $maxws, ($last - $first)
}
