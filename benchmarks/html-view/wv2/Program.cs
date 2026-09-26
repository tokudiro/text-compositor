// WebView2でHTMLを表示するだけの、計測用の最小アプリ（#180）。
//
//   dotnet Wv2Bench.dll <html> [--udf <dir>] [--args "<ブラウザ引数>"] [--no-script] [--no-webview]
//
// 標準出力へ、"loaded"（最初の読み込みの完了）・"reloaded"（再読み込みの完了）を1行ずつ出す。
// 再読み込みは、ファイルの変更を検知して行う。標準入力から、"quit"（終了）を受け取る。
// 計測は、外側のスクリプト（measure.ps1・measure-visual.ps1）が行う。
//   --no-webview: WebView2を作らず、ウィンドウだけを出す（ホストの基準値）。
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string? html = null, udf = null, browserArgs = null, bgColor = null;
        bool noScript = false, noWebView = false, deferShow = false;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--udf": udf = args[++i]; break;
                case "--args": browserArgs = args[++i]; break;
                case "--no-script": noScript = true; break;
                case "--no-webview": noWebView = true; break;
                case "--defer-show": deferShow = true; break;
                // ページの背景色に、フォーム・WebView2既定の背景色を合わせる（Electronの調整と同じ狙い。#180の「未試験」）。
                case "--bg-color": bgColor = args[++i]; break;
                default: html = args[i]; break;
            }
        }
        if (html is null && !noWebView) { Console.Error.WriteLine("usage: Wv2Bench <html>"); return 2; }

        ApplicationConfiguration.Initialize();
        var form = new Form { Text = "Wv2Bench", Width = 1000, Height = 800, StartPosition = FormStartPosition.Manual, Left = 40, Top = 40 };
        if (deferShow) form.Opacity = 0;   // 内容が描かれるまで、透明にしておく
        if (bgColor is not null) form.BackColor = System.Drawing.ColorTranslator.FromHtml(bgColor);
        WebView2? view = null;
        var loadedOnce = false;

        void Say(string line) { Console.Out.WriteLine(line); Console.Out.Flush(); }

        if (noWebView)
        {
            form.Shown += (_, _) => Say("loaded");
        }
        else
        {
            view = new WebView2 { Dock = DockStyle.Fill };
            if (bgColor is not null) view.DefaultBackgroundColor = System.Drawing.ColorTranslator.FromHtml(bgColor);
            form.Controls.Add(view);
            form.Shown += async (_, _) =>
            {
                var options = new CoreWebView2EnvironmentOptions { AdditionalBrowserArguments = browserArgs };
                var env = await CoreWebView2Environment.CreateAsync(null, udf, options);
                await view.EnsureCoreWebView2Async(env);
                view.CoreWebView2.Settings.IsScriptEnabled = !noScript;
                view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                view.CoreWebView2.Settings.IsStatusBarEnabled = false;
                view.CoreWebView2.NavigationCompleted += (_, e) =>
                {
                    if (deferShow && !loadedOnce) form.Opacity = 1;
                    Say(loadedOnce ? "reloaded" : "loaded");
                    loadedOnce = true;
                };
                view.CoreWebView2.Navigate(new Uri(Path.GetFullPath(html!)).AbsoluteUri);

                // 実際のViewerと同じく、ファイルの変更を検知して、再読み込みする（連続した変更は、まとめる）
                var full = Path.GetFullPath(html!);
                var watcher = new FileSystemWatcher(Path.GetDirectoryName(full)!, Path.GetFileName(full))
                {
                    NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.Size,
                    EnableRaisingEvents = true,
                };
                var debounce = new System.Windows.Forms.Timer { Interval = 10 };
                debounce.Tick += (_, _) => { debounce.Stop(); view.CoreWebView2.Reload(); };
                watcher.Changed += (_, _) => form.BeginInvoke(() => { debounce.Stop(); debounce.Start(); });
            };
        }

        var reader = new Thread(() =>
        {
            string? line;
            while ((line = Console.In.ReadLine()) is not null)
            {
                if (line == "reload") form.BeginInvoke(() => view?.CoreWebView2.Reload());
                else if (line == "quit") { form.BeginInvoke(() => Application.Exit()); break; }
            }
        }) { IsBackground = true };
        reader.Start();

        Application.Run(form);
        return 0;
    }
}
