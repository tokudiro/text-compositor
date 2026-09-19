param(
    [Parameter(Mandatory)]
    [ValidateSet('host', 'wv2', 'wry', 'electron', 'browser-app', 'browser-tab')]
    [string]$Candidate,
    [int]$Runs = 10,
    [int]$Reloads = 5,
    [string]$Label = "",
    # ブラウザ引数（wv2・electron）。例: "--disable-gpu --in-process-gpu"
    [string]$BrowserArgs = "",
    [switch]$NoScript,
    [string]$OutFile = ""
)
# HTML表示の候補（#180）を、同じ条件で計測する。測る項目:
#   startup_ms   起動（または、タブを開く）から、最初の読み込みの完了まで
#   reload_ms    ファイルを書き換えて、再読み込みが完了するまで（平均）
#   procs        プロセス数（プロセスツリー全体）
#   ws_mb        ワーキングセットの合計（共有ページを重複して数える）
#   pws_mb       プライベートなワーキングセットの合計（タスクマネージャーの「メモリ」に近い。主に、これを見る）
#   idle_cpu_pct 待機中のCPU使用率（1コアに対する％）
# プロセスツリーは、起動したアプリ（ブラウザ候補は、サーバーとブラウザ）とその子孫すべて。
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $Here)
$Fixture = Join-Path $Here "fixture"
$Html = Join-Path $Fixture "index.html"
$Temp = Join-Path $RepoRoot "temp"
$Dotnet = if ($env:DOTNET_ROOT) { Join-Path $env:DOTNET_ROOT "dotnet.exe" } else { "dotnet" }
$Python = if ($env:BENCH_PYTHON) { $env:BENCH_PYTHON } else { Join-Path $RepoRoot ".venv-dev\Scripts\python.exe" }
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$Wv2Dll = Join-Path $Here "wv2\bin\Release\net10.0-windows\Wv2Bench.dll"
$ElectronExe = Join-Path $Temp "html-view-tools\electron\electron.exe"
$ElectronApp = Join-Path $Here "electron"
$WryExe = Join-Path $Here "wry\target\release\wry-bench.exe"
$ServePy = Join-Path $Here "browser\serve.py"
$Port = 8766
$CdpPort = 9333

# -- プロセスツリー ---------------------------------------------------------

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

# -- 標準出力の1行を待つ ------------------------------------------------------

function Wait-Line($Ctx, [string]$Expect, [int]$TimeoutMs = 30000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ($true) {
        if ($null -eq $Ctx.Pending) { $Ctx.Pending = $Ctx.Proc.StandardOutput.ReadLineAsync() }
        $remaining = [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds
        if ($remaining -le 0 -or -not $Ctx.Pending.Wait($remaining)) { throw "timeout waiting for '$Expect'" }
        $line = $Ctx.Pending.Result
        $Ctx.Pending = $null
        if ($null -eq $line) { throw "process ended while waiting for '$Expect'" }
        if ($line -eq $Expect) { return }
    }
}

function Send-Line($Ctx, [string]$Text) {
    $Ctx.Proc.StandardInput.WriteLine($Text)
    $Ctx.Proc.StandardInput.Flush()
}

function Start-Piped([string]$File, [string]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $psi.Arguments = $Arguments
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardInput = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    return [System.Diagnostics.Process]::Start($psi)
}

function Start-Edge([string]$Profile, [string]$Url, [bool]$AppMode) {
    $args = @("--user-data-dir=`"$Profile`"", "--no-first-run", "--no-default-browser-check", "--disable-sync",
              "--remote-debugging-port=$CdpPort", "--window-position=40,40", "--window-size=1000,800")
    $args += $(if ($AppMode) { "--app=$Url" } else { $Url })
    return Start-Process -FilePath $Edge -ArgumentList $args -PassThru
}

function Remove-Dir([string]$Path) {
    if (Test-Path $Path) { try { [System.IO.Directory]::Delete($Path, $true) } catch {} }
}

# -- 1回の計測 ---------------------------------------------------------------

function Invoke-Run([int]$Index) {
    $ctx = @{ Proc = $null; Pending = $null }
    $roots = @()
    $profile = Join-Path $Temp "edge-profile-bench"
    $result = [ordered]@{}
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        switch ($Candidate) {
            { $_ -in 'host', 'wv2' } {
                $udf = Join-Path $Temp "wv2-udf-bench"   # 2回目以降は、作成済みのプロファイルを使う（実際のアプリと同じ）
                $a ="`"$Wv2Dll`" `"$Html`" --udf `"$udf`""
                if ($Candidate -eq 'host') { $a += " --no-webview" }
                if ($BrowserArgs) { $a += " --args `"$BrowserArgs`"" }
                if ($NoScript) { $a += " --no-script" }
                $ctx.Proc = Start-Piped $Dotnet $a
                $roots = @($ctx.Proc.Id)
                Wait-Line $ctx "loaded"
                $result.startup_ms = $sw.Elapsed.TotalMilliseconds
            }
            'wry' {
                $ud = Join-Path $Temp "wry-udf-bench"
                $a = "`"$Html`" --user-data `"$ud`""
                if ($BrowserArgs) { $a += " --args `"$BrowserArgs`"" }
                $ctx.Proc = Start-Piped $WryExe $a
                $roots = @($ctx.Proc.Id)
                Wait-Line $ctx "loaded"
                $result.startup_ms = $sw.Elapsed.TotalMilliseconds
            }
            'electron' {
                $ud = Join-Path $Temp "electron-userdata-bench"
                $a = "`"$ElectronApp`" `"$Html`" --user-data `"$ud`""
                if ($BrowserArgs) { $a += " $BrowserArgs" }
                $ctx.Proc = Start-Piped $ElectronExe $a
                $roots = @($ctx.Proc.Id)
                Wait-Line $ctx "loaded"
                $result.startup_ms = $sw.Elapsed.TotalMilliseconds
            }
            'browser-app' {
                Remove-Dir $profile
                $ctx.Proc = Start-Piped $Python "`"$ServePy`" --dir `"$Fixture`" --port $Port"
                Wait-Line $ctx "listening"
                $edge = Start-Edge $profile "http://127.0.0.1:$Port/" $true
                $roots = @($ctx.Proc.Id, $edge.Id)
                Wait-Line $ctx "loaded"
                $result.startup_ms = $sw.Elapsed.TotalMilliseconds
            }
            'browser-tab' {
                # すでに起動しているブラウザへ、タブを1つ追加する場合の、増加分を測る。
                Remove-Dir $profile
                $ctx.Proc = Start-Piped $Python "`"$ServePy`" --dir `"$Fixture`" --port $Port"
                Wait-Line $ctx "listening"
                $edge = Start-Edge $profile "about:blank" $false
                $roots = @($ctx.Proc.Id, $edge.Id)
                for ($i = 0; $i -lt 100; $i++) {
                    try { Invoke-RestMethod "http://127.0.0.1:$CdpPort/json/version" | Out-Null; break } catch { Start-Sleep -Milliseconds 100 }
                }
                Start-Sleep -Seconds 3
                $base = Measure-Tree $roots
                $sw.Restart()
                Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:$CdpPort/json/new?http://127.0.0.1:$Port/" | Out-Null
                Wait-Line $ctx "loaded"
                $result.startup_ms = $sw.Elapsed.TotalMilliseconds
            }
        }

        Start-Sleep -Seconds 3
        $m = Measure-Tree $roots
        $cpu0 = Get-Cpu $m.Pids
        $t0 = [DateTime]::UtcNow
        Start-Sleep -Seconds 5
        $cpu1 = Get-Cpu (Get-Tree $roots)
        $result.idle_cpu_pct = (($cpu1 - $cpu0) / ([DateTime]::UtcNow - $t0).TotalSeconds) * 100
        $result.procs = $m.Procs
        $result.ws_mb = $m.WsMb
        $result.pws_mb = $m.PwsMb
        if ($Candidate -eq 'browser-tab') {
            $result.tab_ws_mb = $m.WsMb - $base.WsMb
            $result.tab_pws_mb = $m.PwsMb - $base.PwsMb
        }

        if ($Candidate -ne 'host') {
            $times = @()
            for ($i = 0; $i -lt $Reloads; $i++) {
                $sw.Restart()
                (Get-Item $Html).LastWriteTime = Get-Date   # ファイルを書き換えたことにする
                # wv2・electronは、ファイルの変更を検知して、自分で再読み込みする。ブラウザ候補は、合図を送る。
                if ($Candidate -notin 'wv2', 'wry', 'electron') { Send-Line $ctx "reload" }
                Wait-Line $ctx "reloaded"
                $times += $sw.Elapsed.TotalMilliseconds
                Start-Sleep -Milliseconds 300
            }
            $result.reload_ms = ($times | Measure-Object -Average).Average
            $after = Measure-Tree $roots
            $result.pws_after_reload_mb = $after.PwsMb
        }
    }
    finally {
        try { Send-Line $ctx "quit" } catch {}
        if ($ctx.Proc) { [void]$ctx.Proc.WaitForExit(4000) }
        if ($roots.Count -gt 0) { Stop-Tree $roots }
        Start-Sleep -Milliseconds 500
        # 残ったブラウザ（このスクリプトが起動したプロファイル）を片付ける
        Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
            Where-Object { $_.CommandLine -like "*edge-profile-bench*" } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
        Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" |
            Where-Object { $_.CommandLine -like "*wv2-udf-bench*" -or $_.CommandLine -like "*wry-udf-bench*" } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
    }
    return [pscustomobject]$result
}

# -- 実行と集計 ----------------------------------------------------------------

$rows = @()
for ($n = 1; $n -le $Runs; $n++) {
    $row = Invoke-Run $n
    $rows += $row
    Write-Host ("  run {0}: startup={1:N0} ms  pws={2:N0} MB  procs={3}" -f $n, $row.startup_ms, $row.pws_mb, $row.procs)
}

function Stat($rows, $name) {
    $v = @($rows | Where-Object { $null -ne $_.$name } | ForEach-Object { [double]$_.$name })
    if ($v.Count -eq 0) { return }
    $rest = if ($v.Count -gt 1) { $v[1..($v.Count - 1)] } else { $v }
    $m = $rest | Measure-Object -Average -Minimum -Maximum
    "{0,-20} 1回目={1,9:N1}  2回目以降 mean={2,9:N1} min={3,9:N1} max={4,9:N1}" -f $name, $v[0], $m.Average, $m.Minimum, $m.Maximum
}

$title = if ($Label) { $Label } else { $Candidate }
"== $title (runs=$Runs, reloads=$Reloads)"
foreach ($name in "startup_ms", "reload_ms", "procs", "ws_mb", "pws_mb", "pws_after_reload_mb", "idle_cpu_pct", "tab_ws_mb", "tab_pws_mb") { Stat $rows $name }
if ($OutFile) { $rows | ConvertTo-Json | Set-Content -Path $OutFile -Encoding UTF8 }
