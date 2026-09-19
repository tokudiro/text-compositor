param(
    [Parameter(Mandatory)]
    [ValidateSet('wv2', 'wv2-tuned', 'wv2-defer', 'wry', 'wry-tuned', 'wry-defer', 'electron', 'electron-tuned', 'electron-defer', 'arto', 'shiba', 'mdhero', 'marktext', 'ghostwriter', 'mo')]
    [string]$Tool,
    [int]$Runs = 10,
    [string]$ToolsDir = "",
    [string]$OutFile = "",
    # 再読み込みのちらつきも測る（1回の起動につき、3回の再読み込み）
    [switch]$Flicker,
    # 最初の起動で、再読み込み中の画面を、PNGで保存する先
    [string]$SaveFrames = ""
)
# 全候補を、同じ方法（画面のキャプチャ）で、表示までの時間を測る（#180）。測る項目（起動からの経過時間）:
#   window_ms       ウィンドウが表示される
#   first_paint_ms  ウィンドウの内容が、最初に変わる（文書が描かれ始める）
#   settle_ms       画面が落ち着く（最後に画面が変わった時刻。以降の900 msは変化なし）
# 自作の候補（wv2・electron）は固定のHTML（fixture/index.html）を、既存のツールは標準GFMの原稿
# （fixture/fixture-gfm.md）を開く。moは、ブラウザ（Edge）の新しいタブで開く。
# ウィンドウは、最前面の 40,40 に 1000x800 で置く。測っている間は、他の画面操作をしないこと。
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Here "bench-lib.ps1")
. (Join-Path $Here "bench-visual.ps1")
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$Temp = Join-Path $RepoRoot "temp"
if (-not $ToolsDir) { $ToolsDir = Join-Path $Temp "html-view-tools" }
$Html = Join-Path $Here "fixture\index.html"
$Md = Join-Path $Here "fixture\fixture-gfm.md"
$Dotnet = if ($env:DOTNET_ROOT) { Join-Path $env:DOTNET_ROOT "dotnet.exe" } else { "dotnet" }
$Wv2Dll = Join-Path $Here "wv2\bin\Release\net10.0-windows\Wv2Bench.dll"
$ElectronExe = Join-Path $ToolsDir "electron\electron.exe"
$ElectronApp = Join-Path $Here "electron"
$WryExe = Join-Path $Here "wry\target\release\wry-bench.exe"
$EdgeExe = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$MoPort = 6299
$CdpPort = 9334
$Tuned = "--disable-gpu --in-process-gpu"

function Get-Launch([string]$Tool) {
    switch ($Tool) {
        'wv2'            { return @($Dotnet, "`"$Wv2Dll`" `"$Html`" --udf `"$(Join-Path $Temp 'wv2-udf-bench')`"") }
        'wv2-tuned'      { return @($Dotnet, "`"$Wv2Dll`" `"$Html`" --udf `"$(Join-Path $Temp 'wv2-udf-bench')`" --args `"$Tuned`"") }
        'wv2-defer'      { return @($Dotnet, "`"$Wv2Dll`" `"$Html`" --udf `"$(Join-Path $Temp 'wv2-udf-bench')`" --args `"$Tuned`" --defer-show") }
        'wry'            { return @($WryExe, "`"$Html`" --user-data `"$(Join-Path $Temp 'wry-udf-bench')`"") }
        'wry-tuned'      { return @($WryExe, "`"$Html`" --user-data `"$(Join-Path $Temp 'wry-udf-bench')`" --args `"$Tuned`"") }
        'wry-defer'      { return @($WryExe, "`"$Html`" --user-data `"$(Join-Path $Temp 'wry-udf-bench')`" --args `"$Tuned`" --defer-show") }
        'electron-defer' { return @($ElectronExe, "`"$ElectronApp`" `"$Html`" --user-data `"$(Join-Path $Temp 'electron-userdata-bench')`" $Tuned --defer-show") }
        'electron'       { return @($ElectronExe, "`"$ElectronApp`" `"$Html`" --user-data `"$(Join-Path $Temp 'electron-userdata-bench')`"") }
        'electron-tuned' { return @($ElectronExe, "`"$ElectronApp`" `"$Html`" --user-data `"$(Join-Path $Temp 'electron-userdata-bench')`" $Tuned") }
        'arto'           { return @((Join-Path $ToolsDir "arto-windows-x86_64.exe"), "`"$Md`"") }
        'shiba'          { return @((Join-Path $ToolsDir "shiba\shiba.exe"), "--no-restore `"$Md`"") }
        'mdhero'         { return @((Join-Path $ToolsDir "mdhero\PFiles\MDHero\mdhero.exe"), "`"$Md`"") }
        'marktext'       { return @((Join-Path $ToolsDir "marktext\marktext.exe"), "`"$Md`"") }
        'ghostwriter'    { return @((Join-Path $ToolsDir "ghostwriter\ghostwriter.exe"), "`"$Md`"") }
    }
}

function Get-TouchPath() { if ($Tool -in 'wv2', 'wv2-tuned', 'wv2-defer', 'wry', 'wry-tuned', 'wry-defer', 'electron', 'electron-tuned', 'electron-defer') { return $Html } else { return $Md } }

function Invoke-AppRun([int]$Index) {
    $launch = Get-Launch $Tool
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $launch[0] -ArgumentList $launch[1] -PassThru
    try {
        while ($sw.Elapsed.TotalSeconds -lt 30) {
            $p.Refresh()
            if ($p.MainWindowHandle -ne [IntPtr]::Zero) { break }
            Start-Sleep -Milliseconds 20
        }
        if ($p.MainWindowHandle -eq [IntPtr]::Zero) { throw "no window" }
        $windowMs = $sw.Elapsed.TotalMilliseconds
        $startSave = if ($SaveFrames -and $Index -eq 1) { $SaveFrames } else { "" }
        $v = Wait-VisualSettle $p.MainWindowHandle $sw 25000 900 $startSave
        $row = [ordered]@{ window_ms = $windowMs; first_paint_ms = $v.first_paint_ms; content_ms = $v.content_ms; blank_ms = ($v.content_ms - $windowMs); settle_ms = $v.settle_ms; start_changes = $v.changes }
        if ($Flicker) {
            Start-Sleep -Milliseconds 500
            $frames = 0; $dist = 0.0; $maxd = 0.0; $n = 0
            for ($i = 0; $i -lt 3; $i++) {
                $save = if ($SaveFrames -and $Index -eq 1 -and $i -eq 0) { $SaveFrames } else { "" }
                $f = Measure-Flicker (Get-TouchPath) $save
                $frames += $f.disturbed_frames; $dist += $f.disturb_ms; if ($f.max_diff -gt $maxd) { $maxd = $f.max_diff }; $n++
                Start-Sleep -Milliseconds 300
            }
            $row.disturbed_frames = $frames / $n; $row.disturb_ms = $dist / $n; $row.max_diff_pct = $maxd * 100
        }
        return [pscustomobject]$row
    }
    finally {
        Stop-Tree @($p.Id)
        Start-Sleep -Milliseconds 800
    }
}

function Invoke-MoRun() {
    $profile = Join-Path $Temp "edge-profile-external"
    Remove-Dir $profile
    $mo = Join-Path $ToolsDir "mo\mo.exe"
    $edge = $null; $moPid = $null
    try {
        $edge = Start-Process -FilePath $EdgeExe -PassThru -ArgumentList @(
            "--user-data-dir=`"$profile`"", "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--remote-debugging-port=$CdpPort", "about:blank")
        for ($i = 0; $i -lt 100; $i++) {
            try { Invoke-RestMethod "http://127.0.0.1:$CdpPort/json/version" | Out-Null; break } catch { Start-Sleep -Milliseconds 100 }
        }
        $edge.Refresh()
        for ($i = 0; $i -lt 100 -and $edge.MainWindowHandle -eq [IntPtr]::Zero; $i++) { Start-Sleep -Milliseconds 50; $edge.Refresh() }
        [BenchCap]::Place($edge.MainWindowHandle)
        Start-Sleep -Seconds 2
        & $mo $Md --port $MoPort --no-open | Out-Null
        for ($i = 0; $i -lt 200 -and -not $moPid; $i++) {
            $c = Get-NetTCPConnection -LocalPort $MoPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($c) { $moPid = [int]$c.OwningProcess } else { Start-Sleep -Milliseconds 50 }
        }
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:$CdpPort/json/new?http://127.0.0.1:$MoPort/" | Out-Null
        $v = Wait-VisualSettle $edge.MainWindowHandle $sw
        return [pscustomobject]@{ window_ms = 0; first_paint_ms = $v.first_paint_ms; settle_ms = $v.settle_ms }
    }
    finally {
        if ($moPid) { try { Stop-Process -Id $moPid -Force } catch {} }
        if ($edge) { Stop-Tree @($edge.Id) }
        Start-Sleep -Milliseconds 800
        Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
            Where-Object { $_.CommandLine -like "*edge-profile-external*" } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
    }
}

$rows = @()
for ($n = 1; $n -le $Runs; $n++) {
    $row = if ($Tool -eq 'mo') { Invoke-MoRun } else { Invoke-AppRun $n }
    $rows += $row
    Write-Host ("  run {0}: window={1:N0}  content={2:N0}  blank={7:N0}  settle={3:N0} ms  flicker frames={4:N1} ({5:N0} ms, max {6:N0}%)" -f $n, $row.window_ms, $row.content_ms, $row.settle_ms, $row.disturbed_frames, $row.disturb_ms, $row.max_diff_pct, $row.blank_ms)
}
"== $Tool (runs=$Runs)"
foreach ($name in "window_ms", "first_paint_ms", "content_ms", "blank_ms", "settle_ms", "start_changes", "disturbed_frames", "disturb_ms", "max_diff_pct") { Write-Stat $rows $name }
if ($OutFile) { $rows | ConvertTo-Json | Set-Content -Path $OutFile -Encoding UTF8 }
