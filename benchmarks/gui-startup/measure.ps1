param(
    [string]$Exe,
    [string]$Pdf,
    [int]$Runs = 10,
    [string]$Label = ""
)
# アプリを起動し、標準出力の"first_frame"までの時間、PDF描画の時間、ピークのワーキングセットを測る。
$results = @()
for ($i = 0; $i -lt $Runs; $i++) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = "`"$Pdf`""
    $psi.WorkingDirectory = Split-Path $Exe
    $psi.RedirectStandardOutput = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $p = [System.Diagnostics.Process]::Start($psi)
    $first = $null; $vals = @{}; $peak = 0
    while (-not $p.StandardOutput.EndOfStream) {
        $line = $p.StandardOutput.ReadLine()
        if ($line -eq "first_frame" -and $null -eq $first) { $first = $sw.Elapsed.TotalMilliseconds }
        elseif ($line -match "^(\w+)=([\d.]+)$") { $vals[$matches[1]] = [double]$matches[2] }
        try { $p.Refresh(); if ($p.PeakWorkingSet64 -gt $peak) { $peak = $p.PeakWorkingSet64 } } catch {}
    }
    $p.WaitForExit()
    $total = $sw.Elapsed.TotalMilliseconds
    $results += [pscustomobject]@{
        first_frame_ms = $first; pdf_ms = $vals["pdf_ms"]; pdf96 = $vals["pdf_warm_96dpi_ms"]
        pdf200 = $vals["pdf_warm_200dpi_ms"]; peak_mb = $peak / 1MB; total_ms = $total
    }
}
function Stat($name) {
    $v = @($results | ForEach-Object { $_.$name })
    $first = $v[0]; $rest = $v[1..($v.Count - 1)]
    $avg = ($rest | Measure-Object -Average).Average
    "{0,-16} 1回目={1,8:N1} 2回目以降 mean={2,8:N1} min={3,8:N1} max={4,8:N1}" -f $name, $first, $avg, ($rest | Measure-Object -Minimum).Minimum, ($rest | Measure-Object -Maximum).Maximum
}
"== $Label ($Exe)"
foreach ($n in "first_frame_ms", "pdf_ms", "pdf96", "pdf200", "peak_mb", "total_ms") { Stat $n }
