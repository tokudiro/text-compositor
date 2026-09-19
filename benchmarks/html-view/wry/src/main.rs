// Tauriのホスト層（tao＋wry）でHTMLを表示するだけの、計測用の最小アプリ（#180）。
//
//   wry-bench <html> [--user-data <dir>] [--args "<ブラウザ引数>"] [--defer-show]
//
// 標準出力へ、"loaded"・"reloaded"を出す（他の候補と同じ）。
// 再読み込みは、ファイルの変更を検知して行う（更新日時とサイズを、15 msごとに確かめる）。
// 標準入力の"quit"で終了する。
//   --defer-show: 内容が描かれるまで、ウィンドウを表示しない。
use std::io::BufRead;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use tao::dpi::{LogicalPosition, LogicalSize};
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::window::WindowBuilder;
use wry::{PageLoadEvent, WebContext, WebViewBuilder};
#[cfg(windows)]
use wry::WebViewBuilderExtWindows;

enum Msg {
    Loaded,
    Reload,
    Quit,
}

fn main() {
    let mut html: Option<PathBuf> = None;
    let mut user_data: Option<PathBuf> = None;
    let mut browser_args: Option<String> = None;
    let mut defer_show = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--user-data" => user_data = args.next().map(PathBuf::from),
            "--args" => browser_args = args.next(),
            "--defer-show" => defer_show = true,
            _ => html = Some(PathBuf::from(a)),
        }
    }
    let html = std::fs::canonicalize(html.expect("usage: wry-bench <html>")).expect("html not found");

    let event_loop = EventLoopBuilder::<Msg>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    let window = WindowBuilder::new()
        .with_title("WryBench")
        .with_inner_size(LogicalSize::new(1000.0, 800.0))
        .with_position(LogicalPosition::new(40.0, 40.0))
        .with_visible(!defer_show)
        .build(&event_loop)
        .expect("window");

    let mut context = WebContext::new(user_data);
    let load_proxy = proxy.clone();
    let mut builder = WebViewBuilder::new_with_web_context(&mut context)
        .with_url(url_of(&html))
        .with_on_page_load_handler(move |event, _url| {
            if matches!(event, PageLoadEvent::Finished) {
                let _ = load_proxy.send_event(Msg::Loaded);
            }
        });
    #[cfg(windows)]
    if let Some(a) = browser_args {
        builder = builder.with_additional_browser_args(a);
    }
    #[cfg(not(windows))]
    let _ = browser_args;
    let webview = builder.build(&window).expect("webview");

    // ファイルの変更を検知する（更新日時とサイズ）。連続した変更は、まとめる。
    let watch_proxy = proxy.clone();
    let watch_path = html.clone();
    thread::spawn(move || {
        let stamp = |p: &PathBuf| std::fs::metadata(p).ok().map(|m| (m.modified().ok(), m.len()));
        let mut last = stamp(&watch_path);
        loop {
            thread::sleep(Duration::from_millis(15));
            let now = stamp(&watch_path);
            if now != last {
                thread::sleep(Duration::from_millis(10));
                last = stamp(&watch_path);
                let _ = watch_proxy.send_event(Msg::Reload);
            }
        }
    });

    let quit_proxy = proxy;
    thread::spawn(move || {
        for line in std::io::stdin().lock().lines().map_while(Result::ok) {
            if line.trim() == "quit" {
                let _ = quit_proxy.send_event(Msg::Quit);
                break;
            }
        }
    });

    let mut loaded_once = false;
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(Msg::Loaded) => {
                if !loaded_once && defer_show {
                    window.set_visible(true);
                }
                println!("{}", if loaded_once { "reloaded" } else { "loaded" });
                loaded_once = true;
            }
            Event::UserEvent(Msg::Reload) => {
                let _ = webview.reload();
            }
            Event::UserEvent(Msg::Quit)
            | Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => *control_flow = ControlFlow::Exit,
            _ => {}
        }
    });
}

/// ファイルのパスを、`file:///`のURLにする（Windowsの`\\?\`接頭辞は除く）。
fn url_of(path: &PathBuf) -> String {
    let s = path.to_string_lossy().replace('\\', "/");
    let s = s.trim_start_matches("//?/");
    format!("file:///{}", s)
}
