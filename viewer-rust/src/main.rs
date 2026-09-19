//! Issue #99: PyO3経由でbuild.pyのTypstRenderer.render()を呼び出せるかを確認するだけの
//! 最小疎通確認（スパイク）。ファイル監視・PDF表示・GUI本体は範囲外。
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::{Path, PathBuf};

/// スパイクとして固定のMarkdown文字列を変換する（ファイル指定・CLI引数は範囲外）。
const SAMPLE_MARKDOWN: &str = "\
# Hello from viewer-rust

This is **bold** text and a list:

- one
- two
";

fn repo_root() -> PathBuf {
    // viewer-rust/ はリポジトリ直下に置かれる想定なので、コンパイル時のマニフェストディレクトリ
    // (viewer-rust/) の親をリポジトリルートとする。実行場所(cwd)に依存させないための措置。
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("viewer-rust should live directly under the repository root")
        .to_path_buf()
}

/// 【Windows実機での自動検出、#101】PYTHONHOMEが未指定の場合、実行ファイルと同じ
/// フォルダに組込版Python一式（python310.dll・python310.zip・site-packages等）が
/// 直接展開されている前提で、そこを自動的にPYTHONHOMEとして使う。
/// C#版（#100）のようにDLLパスをAPIで明示指定する仕組みがPyO3にはなく、python310.dll自体は
/// Windowsの標準DLL検索順序（実行ファイルと同じフォルダが最優先）でロードされるため、
/// C#版のような「exeの隣にpython-embed/サブフォルダ」構成はそのままでは使えない
/// （実行ファイルと同じフォルダに直接置く必要がある）。
fn set_default_python_home_if_unset() {
    if std::env::var_os("PYTHONHOME").is_some() {
        return;
    }
    let Ok(exe_path) = std::env::current_exe() else {
        return;
    };
    let Some(exe_dir) = exe_path.parent() else {
        return;
    };
    if exe_dir.join("python310.dll").exists() {
        std::env::set_var("PYTHONHOME", exe_dir);
    }
}

fn main() -> PyResult<()> {
    let root = repo_root();
    println!("[viewer-rust] repo root: {}", root.display());

    set_default_python_home_if_unset();

    Python::with_gil(|py| -> PyResult<()> {
        let version: String = py.import_bound("sys")?.getattr("version")?.extract()?;
        println!("[viewer-rust] embedded Python: {version}");

        // build.py を `import build` できるよう、リポジトリルートをsys.pathへ追加する。
        let sys_path = py.import_bound("sys")?.getattr("path")?;
        sys_path.call_method1("insert", (0, root.to_str().unwrap()))?;

        let build_module = py.import_bound("build")?;
        let renderer_class = build_module.getattr("TypstRenderer")?;
        let renderer = renderer_class.call0()?;

        let kwargs = PyDict::new_bound(py);
        kwargs.set_item("filepath", "")?;
        kwargs.set_item("drop_leading_title", false)?;
        let typst_code: String = renderer
            .call_method("render", (SAMPLE_MARKDOWN,), Some(&kwargs))?
            .extract()?;

        println!("[viewer-rust] --- TypstRenderer.render() output ---");
        println!("{typst_code}");
        Ok(())
    })
}
