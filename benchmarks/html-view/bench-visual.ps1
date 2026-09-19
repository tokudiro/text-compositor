# 画面の見た目で測る（完了を通知しないアプリ向け。#180）。`. .\bench-visual.ps1`で読み込む。
#
# CPUの落ち着き（bench-lib.ps1のWait-CpuQuiet）は、測定のループ自体に1秒強の下限があり、「1秒を超えるか」の
# 判断に使えなかった。代わりに、ウィンドウの画面を繰り返しキャプチャして、内容が最初に変わる時刻
# （first_paint_ms）と、画面が落ち着く時刻（settle_ms。最後に画面が変わった時刻）を測る。
# 全候補で、ウィンドウを同じ位置・大きさ（40,40の1000x800）に置いて、同じ範囲を比べる。
if (-not ('BenchCap' -as [type])) {
    Add-Type -AssemblyName System.Drawing
    # PowerShell 7（.NET）では、System.Drawingの実体が、内部のアセンブリに分かれているため、実行環境から、全部を探して参照する
    $refs = if ($PSVersionTable.PSEdition -eq 'Core') {
        $runtimeDir = [System.IO.Path]::GetDirectoryName([object].Assembly.Location)
        @('System.Drawing.Common', 'System.Drawing.Primitives', 'System.Private.Windows.GdiPlus', 'System.Private.Windows.Core') |
            ForEach-Object { Join-Path $runtimeDir "$_.dll" } | Where-Object { Test-Path $_ }
    } else { @('System.Drawing') }
    Add-Type -ReferencedAssemblies $refs @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
public static class BenchCap {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);

    // 画面の範囲を、間引いたグレースケールで返す（step画素おき）。
    public static byte[] Grab(int x, int y, int w, int h, int step) {
        using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb))
        using (var g = Graphics.FromImage(bmp)) {
            g.CopyFromScreen(x, y, 0, 0, new Size(w, h));
            var data = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try {
                int cols = w / step, rows = h / step;
                var result = new byte[cols * rows];
                var line = new byte[data.Stride];
                for (int r = 0; r < rows; r++) {
                    Marshal.Copy(IntPtr.Add(data.Scan0, r * step * data.Stride), line, 0, data.Stride);
                    for (int c = 0; c < cols; c++) {
                        int i = c * step * 4;
                        result[r * cols + c] = (byte)((line[i] + line[i + 1] + line[i + 2]) / 3);
                    }
                }
                return result;
            } finally { bmp.UnlockBits(data); }
        }
    }

    // 2つの画面で、明るさが16以上違う画素の割合。
    public static double Diff(byte[] a, byte[] b) {
        int n = 0;
        for (int i = 0; i < a.Length; i++) if (Math.Abs(a[i] - b[i]) > 16) n++;
        return a.Length == 0 ? 0 : (double)n / a.Length;
    }

    // 文書の内容が描かれているか。背景（最頻の明るさ）と違う画素の割合。ウィンドウの縁や、背後の画面を
    // 拾わないよう、中央部（縁から25サンプル＝100画素を除く）だけを見る。何も描かれていないウィンドウは、ほぼ0。
    // 文字や図が出ると、数%以上になる。
    public static double Ink(byte[] gray, int cols, int rows, int margin) {
        var hist = new int[256];
        int n = 0;
        for (int r = margin; r < rows - margin; r++)
            for (int c = margin; c < cols - margin; c++) { hist[gray[r * cols + c]]++; n++; }
        int mode = 0;
        for (int i = 1; i < 256; i++) if (hist[i] > hist[mode]) mode = i;
        int ink = 0;
        for (int r = margin; r < rows - margin; r++)
            for (int c = margin; c < cols - margin; c++) if (Math.Abs(gray[r * cols + c] - mode) > 24) ink++;
        return n == 0 ? 0 : (double)ink / n;
    }

    public static void SavePng(int x, int y, int w, int h, string path) {
        using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb))
        using (var g = Graphics.FromImage(bmp)) {
            g.CopyFromScreen(x, y, 0, 0, new Size(w, h));
            bmp.Save(path, ImageFormat.Png);
        }
    }

    public static void Place(IntPtr h) {
        SetWindowPos(h, new IntPtr(-1), 40, 40, 1000, 800, 0x40);  // 最前面・表示
        SetForegroundWindow(h);
    }
}
"@
    [void][BenchCap]::SetProcessDPIAware()
}

# ウィンドウのハンドルが得られたあと、画面が落ち着くまでを測る。Stopwatchは、起動（または、操作）の時点から
# 動かしておく。戻り値: first_paint_ms（内容が最初に変わる）・settle_ms（最後に画面が変わる）。
# 測れなかった項目は、$null。
function Wait-VisualSettle([IntPtr]$Handle, $Stopwatch, [int]$TimeoutMs = 25000, [int]$StableMs = 900, [string]$SaveDir = "") {
    [BenchCap]::Place($Handle)
    Start-Sleep -Milliseconds 60
    $x = 40; $y = 40; $w = 1000; $h = 800; $step = 4
    $first = [BenchCap]::Grab($x, $y, $w, $h, $step)
    $prev = $first
    $firstPaint = $null
    $content = $null
    if ([BenchCap]::Ink($first, ($w / $step), ($h / $step), 25) -gt 0.02) { $content = $Stopwatch.Elapsed.TotalMilliseconds }
    $lastChange = $Stopwatch.Elapsed.TotalMilliseconds
    $changes = 0; $index = 0; $content = $null
    while ($Stopwatch.Elapsed.TotalMilliseconds -lt $TimeoutMs) {
        Start-Sleep -Milliseconds 30
        $frame = [BenchCap]::Grab($x, $y, $w, $h, $step)
        $now = $Stopwatch.Elapsed.TotalMilliseconds
        if ($SaveDir -and $index -lt 60) { [BenchCap]::SavePng($x, $y, $w, $h, (Join-Path $SaveDir ("start-{0:000}-{1:0000}ms.png" -f $index, $now))) }
        $index++
        if ($null -eq $firstPaint -and [BenchCap]::Diff($frame, $first) -gt 0.01) { $firstPaint = $now }
        if ($null -eq $content -and [BenchCap]::Ink($frame, ($w / $step), ($h / $step), 25) -gt 0.02) { $content = $now }
        if ([BenchCap]::Diff($frame, $prev) -gt 0.003) { $lastChange = $now; $changes++ }
        $prev = $frame
        if ($null -ne $firstPaint -and ($now - $lastChange) -gt $StableMs) {
            return [pscustomobject]@{ first_paint_ms = $firstPaint; content_ms = $content; settle_ms = $lastChange; changes = $changes }
        }
    }
    return [pscustomobject]@{ first_paint_ms = $firstPaint; content_ms = $content; settle_ms = $null; changes = $changes }
}

# 再読み込みのときの、ちらつきを測る。原稿（HTML）を、同じ内容で書き直して（更新日時だけが変わる）、
# 再読み込みを起こし、その間の画面を繰り返しキャプチャする。内容は同じなので、再読み込みの前と違う画面
# （白い画面・レイアウトの崩れ・スクロール位置の飛びなど）が出たら、ちらつきである。
# 戻り値: disturbed_frames（前と違う画面の枚数）・disturb_ms（前と違う状態が続いた時間）・max_diff（最大の違い、0〜1）。
function Measure-Flicker([string]$TouchPath, [string]$SaveDir = "", [int]$DurationMs = 1500) {
    $x = 40; $y = 40; $w = 1000; $h = 800; $step = 4
    $base = [BenchCap]::Grab($x, $y, $w, $h, $step)
    $bytes = [System.IO.File]::ReadAllBytes($TouchPath)
    # 内容を実際に変える（先頭行の末尾の空白を、足す・除く。表示は変わらない）。更新日時だけの変更に反応しないアプリが
    # あるうえ、末尾を変えると、編集位置へスクロールして追従するアプリ（Shiba等）で、スクロールの動きが混ざるため。
    $nl = [Array]::IndexOf($bytes, [byte]10)
    if ($nl -gt 0 -and $bytes[$nl - 1] -eq 32) { $new = $bytes[0..($nl - 2)] + $bytes[$nl..($bytes.Length - 1)] }
    else { $new = $bytes[0..($nl - 1)] + [byte]32 + $bytes[$nl..($bytes.Length - 1)] }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    [System.IO.File]::WriteAllBytes($TouchPath, [byte[]]$new)
    $count = 0; $first = $null; $last = $null; $max = 0.0; $frames = 0
    while ($sw.Elapsed.TotalMilliseconds -lt $DurationMs) {
        $now = $sw.Elapsed.TotalMilliseconds
        $d = [BenchCap]::Diff([BenchCap]::Grab($x, $y, $w, $h, $step), $base)
        $frames++
        if ($SaveDir) { [BenchCap]::SavePng($x, $y, $w, $h, (Join-Path $SaveDir ("frame-{0:000}-{1:0000}ms-diff{2:00}.png" -f $frames, $now, ($d * 100)))) }
        if ($d -gt 0.02) {
            $count++
            if ($null -eq $first) { $first = $now }
            $last = $now
        }
        if ($d -gt $max) { $max = $d }
    }
    $duration = if ($null -ne $first) { $last - $first } else { 0 }
    return [pscustomobject]@{ disturbed_frames = $count; disturb_ms = $duration; max_diff = $max; frames = $frames }
}
