// Issue #99: pythonnet経由でbuild.pyのTypstRenderer.render()を呼び出せるかを確認するだけの
// 最小疎通確認（スパイク）。ファイル監視・PDF表示・GUI本体は範囲外。
using System.Linq;
using Python.Runtime;

// スパイクとして固定のMarkdown文字列を変換する（ファイル指定・CLI引数は範囲外）。
const string SampleMarkdown = """
# Hello from viewer-csharp

This is **bold** text and a list:

- one
- two
""";

// viewer-csharp/ はリポジトリ直下に置かれる想定なので、実行ファイルの場所に依存させず、
// ビルド元ソースの位置からリポジトリルートを求める。
string repoRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));
Console.WriteLine($"[viewer-csharp] repo root: {repoRoot}");

// 埋め込み先のPython実行体（libpython）とPYTHONHOMEは環境依存（開発機ではMicrosoft Store版Python）
// なので、環境変数で上書きできるようにする（#99の検証項目そのもの）。
// 環境変数が未指定の場合は、実行ファイルと同じフォルダの python-embed/（組込版Python、#102）を
// 自動的に使う。配布時はexeの隣にpython-embed/を配置する想定（ViewerCSharp.csproj参照）なので、
// 毎回環境変数を設定しなくても動く。
string defaultEmbedDir = Path.Combine(AppContext.BaseDirectory, "python-embed");
bool hasDefaultEmbed = Directory.Exists(defaultEmbedDir);

string? pythonDll = Environment.GetEnvironmentVariable("VIEWER_PYTHON_DLL");
if (string.IsNullOrEmpty(pythonDll) && hasDefaultEmbed)
{
    // python3.dll（stable ABI用の汎用スタブ、Py_IncRef等の実体シンボルを提供しない）を誤って
    // 選ばないよう明示的に除外する。"python3??.dll"のようなWindowsワイルドカードは末尾の
    // '?'が0文字にもマッチするため、python3.dllにもヒットしてしまうことを実機確認した。
    string[] candidates = Directory.GetFiles(defaultEmbedDir, "python3*.dll")
        .Where(f => !Path.GetFileName(f).Equals("python3.dll", StringComparison.OrdinalIgnoreCase))
        .ToArray();
    pythonDll = candidates.Length > 0 ? candidates[0] : null;
}
if (!string.IsNullOrEmpty(pythonDll))
{
    Runtime.PythonDLL = pythonDll;
}

string? pythonHome = Environment.GetEnvironmentVariable("VIEWER_PYTHON_HOME");
if (string.IsNullOrEmpty(pythonHome) && hasDefaultEmbed)
{
    pythonHome = defaultEmbedDir;
}
if (!string.IsNullOrEmpty(pythonHome))
{
    PythonEngine.PythonHome = pythonHome;
}

PythonEngine.Initialize();

// 【終了時ハング対策】pythonnetはAppDomain.ProcessExitにPythonEngine.OnProcessExitを自動登録
// しており、プロセス終了時に別スレッド（ファイナライザースレッド）でPythonEngine.Shutdown()
// 経由のGIL取得（PyGILState_Ensure）を試みる。dotnet-dumpのスレッドダンプで、このGIL取得が
// 永久にブロックすることを確認した（#99 Issue #100参照）。
// 単にusing (Py.GIL())でGIL State APIのGILを解放するだけでは不十分だった。原因は
// PythonEngine.Initialize()直後、メインスレッドがPython実行コンテキスト（スレッドステート）を
// 暗黙的に保持したままになっているため（pythonnet公式Issue #1701で報告されている既知の挙動）。
// PythonEngine.BeginAllowThreads()（CPythonのPyEval_SaveThread相当）でこれを明示的に手放す
// 必要がある。
PythonEngine.BeginAllowThreads();

string typstCode;
using (Py.GIL())
{
    Console.WriteLine($"[viewer-csharp] embedded Python: {PythonEngine.Version}");

    // build.py を `import build` できるよう、リポジトリルートをsys.pathへ追加する。
    // 依存パッケージ（markdown-it-py等）用のsite-packagesを別途追加したい場合は
    // VIEWER_PYTHON_EXTRA_PATH（区切り文字はPath.PathSeparator）で指定する。
    dynamic sys = Py.Import("sys");
    sys.path.insert(0, repoRoot);
    string? extraPath = Environment.GetEnvironmentVariable("VIEWER_PYTHON_EXTRA_PATH");
    string defaultSitePackages = Path.Combine(defaultEmbedDir, "site-packages");
    if (string.IsNullOrEmpty(extraPath) && Directory.Exists(defaultSitePackages))
    {
        extraPath = defaultSitePackages;
    }
    if (!string.IsNullOrEmpty(extraPath))
    {
        foreach (string p in extraPath.Split(Path.PathSeparator))
        {
            sys.path.insert(0, p);
        }
    }

    dynamic buildModule = Py.Import("build");
    dynamic renderer = buildModule.TypstRenderer();
    typstCode = renderer.render(SampleMarkdown, filepath: "", drop_leading_title: false);
}

Console.WriteLine("[viewer-csharp] --- TypstRenderer.render() output ---");
Console.WriteLine(typstCode);

Console.Out.Flush();
Environment.Exit(0);
