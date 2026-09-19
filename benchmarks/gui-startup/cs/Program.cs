// 起動時間・PDF表示時間の計測用の最小アプリ（#166）。ウィンドウを開き、PDFの1ページ目をPDFiumで描画して
// 表示し、標準出力へ計測値を出して終了する。外側のランチャー（PowerShell）が、起動からの経過時間を測る。
using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Avalonia.Themes.Fluent;
using PDFtoImage;
using SkiaSharp;

static class Program
{
    public static string PdfPath = "";

    [STAThread]
    public static int Main(string[] args)
    {
        PdfPath = args.Length > 0 ? args[0] : "test.pdf";
        return AppBuilder.Configure<App>().UsePlatformDetect().StartWithClassicDesktopLifetime(args);
    }
}

class App : Application
{
    public override void Initialize() => Styles.Add(new FluentTheme());

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow();
        }
        base.OnFrameworkInitializationCompleted();
    }
}

class MainWindow : Window
{
    readonly Image _image = new();

    public MainWindow()
    {
        Width = 800;
        Height = 1000;
        // 見た目の比較用: ツールバー・ボタン・コンボボックス・入力欄・ステータスバーを、日本語で並べる
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Margin = new Thickness(8) };
        toolbar.Children.Add(new Button { Content = "開く…" });
        toolbar.Children.Add(new Button { Content = "再読み込み" });
        toolbar.Children.Add(new ComboBox { ItemsSource = new[] { "50%", "100%", "150%", "200%" }, SelectedIndex = 1 });
        toolbar.Children.Add(new CheckBox { Content = "自動で更新", IsChecked = true });
        toolbar.Children.Add(new TextBox { Text = "日本語の入力欄：検索", Width = 220 });
        var status = new TextBlock { Text = "更新 12ms ／ 図表 3件（キャッシュ命中）— ビルドエラーはここに表示します", Margin = new Thickness(8) };
        DockPanel.SetDock(toolbar, Dock.Top);
        DockPanel.SetDock(status, Dock.Bottom);
        Content = new DockPanel { Children = { toolbar, status, new ScrollViewer { Content = _image } } };
        Opened += (_, _) =>
        {
            Console.WriteLine("first_frame");
            Console.Out.Flush();
            // ウィンドウが表示された後の、次のUIスレッドの処理としてPDFを描画する
            Dispatcher.UIThread.Post(RenderPdf, DispatcherPriority.Background);
        };
    }

    Bitmap Render(int dpi)
    {
        using var fs = File.OpenRead(Program.PdfPath);
        using SKBitmap bmp = Conversion.ToImage(fs, page: 0, options: new RenderOptions(Dpi: dpi));
        // PNGへ圧縮し直さず、ピクセルをそのままWriteableBitmapへコピーする（実際のビューアと同じ方式）
        var wb = new WriteableBitmap(new PixelSize(bmp.Width, bmp.Height), new Vector(96, 96),
            Avalonia.Platform.PixelFormat.Bgra8888, Avalonia.Platform.AlphaFormat.Premul);
        using (var fb = wb.Lock())
        {
            IntPtr src = bmp.GetPixels();
            int rowBytes = Math.Min(bmp.RowBytes, fb.RowBytes);
            var row = new byte[rowBytes];
            for (int y = 0; y < bmp.Height; y++)
            {
                System.Runtime.InteropServices.Marshal.Copy(src + y * bmp.RowBytes, row, 0, rowBytes);
                System.Runtime.InteropServices.Marshal.Copy(row, 0, fb.Address + y * fb.RowBytes, rowBytes);
            }
        }
        return wb;
    }

    void RenderPdf()
    {
        var sw = Stopwatch.StartNew();
        _image.Source = Render(96);
        Console.WriteLine($"pdf_ms={sw.Elapsed.TotalMilliseconds:F1}");

        // 2回目以降（PDFiumの初期化後）と、ズーム相当の高解像度を測る
        sw.Restart();
        for (int i = 0; i < 5; i++) _image.Source = Render(96);
        Console.WriteLine($"pdf_warm_96dpi_ms={sw.Elapsed.TotalMilliseconds / 5:F1}");
        sw.Restart();
        for (int i = 0; i < 5; i++) _image.Source = Render(200);
        Console.WriteLine($"pdf_warm_200dpi_ms={sw.Elapsed.TotalMilliseconds / 5:F1}");

        Console.Out.Flush();
        if (Environment.GetEnvironmentVariable("HOLD") != "1") Environment.Exit(0);
    }
}
