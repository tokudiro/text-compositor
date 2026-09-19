param(
    [Parameter(Mandatory)]
    [ValidateSet('arto', 'shiba', 'mo', 'marktext', 'ghostwriter', 'mdhero')]
    [string]$Tool,
    [int]$Runs = 5,
    # 各ツールの実行ファイルの置き場所（既定は、リポジトリの temp/html-view-tools/）
    [string]$ToolsDir = "",
    [string]$ShotDir = "",
    [string]$OutFile = ""
)
# 既存のMarkdown Viewer（Arto・Shiba・mo）を、同じ原稿（fixture/fixture-gfm.md）で計測する（#180）。
# これらは、読み込みの完了を知らせないため、次の目安を使う。
#   window_ms  ウィンドウが表示されるまで（moは、ブラウザのタブを開くまで）
#   ready_ms   その後、CPUが落ち着くまで（読み込みと、図の描画が終わった目安）。起動からの経過時間
#   procs / ws_mb / pws_mb / idle_cpu_pct は、measure.ps1と同じ。moは、サーバー＋ブラウザ（タブ1つの増加分は、tab_pws_mb）
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Here "bench-lib.ps1")
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$Temp = Join-Path $RepoRoot "temp"
if (-not $ToolsDir) { $ToolsDir = Join-Path $Temp "html-view-tools" }
$Md = Join-Path $Here "fixture\fixture-gfm.md"
$EdgeExe = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$MoPort = 6299
$CdpPort = 9334

function Invoke-AppRun([string]$Exe, [string]$Arguments, [string]$ShotPath) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    $result = [ordered]@{}
    try {
        while ($sw.Elapsed.TotalSeconds -lt 30) {
            $p.Refresh()
            if ($p.MainWindowHandle -ne [IntPtr]::Zero) { break }
            Start-Sleep -Milliseconds 30
        }
        if ($p.MainWindowHandle -eq [IntPtr]::Zero) { throw "no window" }
        $result.window_ms = $sw.Elapsed.TotalMilliseconds
        $result.ready_ms = Wait-CpuQuiet @($p.Id) $sw
        Start-Sleep -Seconds 3
        $m = Measure-Tree @($p.Id)
        $result.idle_cpu_pct = Measure-IdleCpu @($p.Id)
        $result.procs = $m.Procs; $result.ws_mb = $m.WsMb; $result.pws_mb = $m.PwsMb
        if ($ShotPath) { [void](Save-WindowShot $p.Id $ShotPath) }
    }
    finally {
        Stop-Tree @($p.Id)
        Start-Sleep -Milliseconds 700
    }
    return [pscustomobject]$result
}

function Invoke-MoRun([string]$ShotPath) {
    # moは、サーバーをバックグラウンドで動かし、ブラウザで開く。ここでは、ブラウザを自分で起動して、タブの増加分を測る。
    $profile = Join-Path $Temp "edge-profile-external"
    Remove-Dir $profile
    $mo = Join-Path $ToolsDir "mo\mo.exe"
    $result = [ordered]@{}
    $edge = $null
    $moPid = $null
    try {
        $edge = Start-Process -FilePath $EdgeExe -PassThru -ArgumentList @(
            "--user-data-dir=`"$profile`"", "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--remote-debugging-port=$CdpPort", "--window-position=40,40", "--window-size=1000,800", "about:blank")
        for ($i = 0; $i -lt 100; $i++) {
            try { Invoke-RestMethod "http://127.0.0.1:$CdpPort/json/version" | Out-Null; break } catch { Start-Sleep -Milliseconds 100 }
        }
        Start-Sleep -Seconds 3
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        # サーバーを起動する（既定のブラウザを開かないように、--no-openを付ける）
        & $mo $Md --port $MoPort --no-open | Out-Null
        for ($i = 0; $i -lt 200 -and -not $moPid; $i++) {
            $c = Get-NetTCPConnection -LocalPort $MoPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($c) { $moPid = [int]$c.OwningProcess } else { Start-Sleep -Milliseconds 50 }
        }
        if (-not $moPid) { throw "mo did not start" }
        $roots = @($edge.Id, $moPid)
        $base = Measure-Tree @($edge.Id)
        $sw.Restart()
        Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:$CdpPort/json/new?http://127.0.0.1:$MoPort/" | Out-Null
        $result.window_ms = $sw.Elapsed.TotalMilliseconds
        $result.ready_ms = Wait-CpuQuiet $roots $sw
        Start-Sleep -Seconds 3
        $m = Measure-Tree $roots
        $result.idle_cpu_pct = Measure-IdleCpu $roots
        $result.procs = $m.Procs; $result.ws_mb = $m.WsMb; $result.pws_mb = $m.PwsMb
        $result.tab_ws_mb = $m.WsMb - $base.WsMb - (Measure-Tree @($moPid)).WsMb
        $result.tab_pws_mb = $m.PwsMb - $base.PwsMb - (Measure-Tree @($moPid)).PwsMb
        $result.server_pws_mb = (Measure-Tree @($moPid)).PwsMb
        if ($ShotPath) { [void](Save-WindowShot $edge.Id $ShotPath) }
    }
    finally {
        if ($moPid) { try { Stop-Process -Id $moPid -Force } catch {} }
        if ($edge) { Stop-Tree @($edge.Id) }
        Start-Sleep -Milliseconds 700
        Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
            Where-Object { $_.CommandLine -like "*edge-profile-external*" } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
    }
    return [pscustomobject]$result
}

$rows = @()
for ($n = 1; $n -le $Runs; $n++) {
    $shot = if ($ShotDir -and $n -eq 1) { Join-Path $ShotDir "$Tool.png" } else { "" }
    $row = switch ($Tool) {
        'arto'  { Invoke-AppRun (Join-Path $ToolsDir "arto-windows-x86_64.exe") "`"$Md`"" $shot }
        'shiba' { Invoke-AppRun (Join-Path $ToolsDir "shiba\shiba.exe") "--no-restore `"$Md`"" $shot }
        'mo'    { Invoke-MoRun $shot }
        'marktext'    { Invoke-AppRun (Join-Path $ToolsDir "marktext\marktext.exe") "`"$Md`"" $shot }
        'ghostwriter' { Invoke-AppRun (Join-Path $ToolsDir "ghostwriter\ghostwriter.exe") "`"$Md`"" $shot }
        'mdhero'      { Invoke-AppRun (Join-Path $ToolsDir "mdhero\PFiles\MDHero\mdhero.exe") "`"$Md`"" $shot }
    }
    $rows += $row
    Write-Host ("  run {0}: window={1:N0} ms  ready={2:N0} ms  pws={3:N0} MB  procs={4}" -f $n, $row.window_ms, $row.ready_ms, $row.pws_mb, $row.procs)
}

"== $Tool (runs=$Runs)"
foreach ($name in "window_ms", "ready_ms", "procs", "ws_mb", "pws_mb", "idle_cpu_pct", "tab_ws_mb", "tab_pws_mb", "server_pws_mb") { Write-Stat $rows $name }
if ($OutFile) { $rows | ConvertTo-Json | Set-Content -Path $OutFile -Encoding UTF8 }
