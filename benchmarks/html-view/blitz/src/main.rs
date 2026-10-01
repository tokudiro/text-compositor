// Obunzuの代替となるネイティブ描画の試作。ObunzuのHTML出力を、JavaScriptなしのBlitzで表示する。
use std::path::Path;
use std::time::Instant;

use std::sync::Arc;
use std::task::Context as TaskContext;

use anyrender_vello::VelloWindowRenderer;
use base64::Engine;
use blitz::dom::{DocGuard, DocGuardMut, Document, DocumentConfig};
use blitz::html::HtmlDocument;
use blitz::shell::{create_default_event_loop, BlitzApplication, BlitzShellEvent, BlitzShellProxy, WindowConfig};
use blitz_shell::DataUriNetProvider;
use blitz::traits::events::UiEvent;
use winit::window::{Theme, WindowAttributes};
use keyboard_types::{Key, Modifiers};

fn mime_of(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase()).as_deref() {
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        _ => "application/octet-stream",
    }
}

// Blitz 0.3.0-beta.2のfile://読み込みは、Windowsで"/C:/..."というパスをそのまま開こうとして失敗する。
// 回避として、<img src="相対パス">を、読み込み前にデータURIへ置き換える。
fn inline_images(html: &str, dir: &Path) -> String {
    let mut out = String::with_capacity(html.len());
    let mut rest = html;
    while let Some(i) = rest.find("<img ") {
        let (head, tail) = rest.split_at(i);
        out.push_str(head);
        let end = tail.find('>').map(|e| e + 1).unwrap_or(tail.len());
        let tag = &tail[..end];
        let mut new_tag = tag.to_string();
        if let Some(s) = tag.find("src=\"") {
            let v0 = s + 5;
            if let Some(len) = tag[v0..].find('"') {
                let src = &tag[v0..v0 + len];
                if !src.starts_with("data:") && !src.contains("://") {
                    let p = dir.join(src.replace('/', "\\"));
                    if let Ok(mut bytes) = std::fs::read(&p) {
                        // SVGのfont-familyに日本語のフォントが無いと、字形を持つ最初のフォント（PCによっては丸ゴシック）が選ばれる。
                        // 総称のsans-serifの前に、日本語のフォントを足して、見た目を固定する。
                        if mime_of(&p) == "image/svg+xml" {
                            if let Ok(s) = String::from_utf8(bytes.clone()) {
                                bytes = s.replace("sans-serif", "'Noto Sans JP',sans-serif").into_bytes();
                            }
                        }
                        let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
                        let uri = format!("data:{};base64,{}", mime_of(&p), b64);
                        new_tag = format!("{}{}{}", &tag[..v0], uri, &tag[v0 + len..]);
                    } else {
                        eprintln!("[warn] image not found: {}", p.display());
                    }
                }
            }
        }
        out.push_str(&new_tag);
        rest = &tail[end..];
    }
    out.push_str(rest);
    out
}

// Blitzは、文書に対するキー操作のスクロール（PageDown等）を持たない（キーは、フォーカスのある入力欄にだけ届く）。
// そこで、文書を包んで、キーを先に受け取り、ビューポートをスクロールする（#382）。
struct KeyScrollDoc {
    doc: HtmlDocument,
    proxy: BlitzShellProxy,
}

// スクロール量（論理ピクセル）。ページ単位は、ウィンドウの高さの9割
fn scroll_amount(key: &Key, modifiers: Modifiers, page: f64) -> Option<f64> {
    const LINE: f64 = 48.0;
    const FAR: f64 = 1.0e9;
    match key {
        Key::PageDown => Some(page),
        Key::PageUp => Some(-page),
        Key::ArrowDown => Some(LINE),
        Key::ArrowUp => Some(-LINE),
        Key::Home => Some(-FAR),
        Key::End => Some(FAR),
        Key::Character(c) if c == " " => Some(if modifiers.contains(Modifiers::SHIFT) { -page } else { page }),
        _ => None,
    }
}

impl Document for KeyScrollDoc {
    fn inner(&self) -> DocGuard<'_> {
        self.doc.inner()
    }
    fn inner_mut(&mut self) -> DocGuardMut<'_> {
        self.doc.inner_mut()
    }
    fn handle_ui_event(&mut self, event: UiEvent) {
        if let UiEvent::KeyDown(key) = &event {
            let (page, doc_id) = {
                let v = self.doc.viewport();
                (v.window_size.1 as f64 / v.scale() as f64 * 0.9, self.doc.id())
            };
            if let Some(dy) = scroll_amount(&key.key, key.modifiers, page) {
                let changed = self.doc.scroll_viewport_by_has_changed(0.0, -dy); // 符号は、Blitzの規約（正の値で、上へ）に合わせる
                if changed {
                    // キーのイベントは、シェルが再描画を要求しないため、ここで頼む
                    self.proxy.send_event(BlitzShellEvent::RequestRedraw { doc_id });
                }
                return;
            }
        }
        self.doc.handle_ui_event(event);
    }
    fn poll(&mut self, task_context: Option<TaskContext>) -> bool {
        self.doc.poll(task_context)
    }
    fn id(&self) -> usize {
        self.doc.id()
    }
}

fn main() {
    let t0 = Instant::now();
    let args: Vec<String> = std::env::args().skip(1).collect();
    // `--dark`: OSの設定を変えずに、ダークモードで表示する（`prefers-color-scheme: dark`の確認用）
    let dark = args.iter().any(|a| a == "--dark");
    let path = args.iter().find(|a| !a.starts_with("--")).expect("usage: native-blitz [--dark] <file.html>").clone();
    let abs = std::fs::canonicalize(&path).expect("no such file");
    let dir = abs.parent().unwrap().to_path_buf();
    let html = std::fs::read_to_string(&abs).expect("read failed");
    let html = inline_images(&html, &dir);
    // 生成HTMLは、ダークモードで画像に`filter: invert(1)`と`mix-blend-mode`を使うが、Blitzはどちらも描かない。
    // そのままだと、図の暗い文字・矢印が、暗い背景に載って読めない。回避として、画像に白い背景を足す
    let html = html.replacen(
        "</head>",
        "<style>@media (prefers-color-scheme: dark) { img { background: #fff; border-radius: 4px; } }</style></head>",
        1,
    );
    eprintln!("[trace] html read + images inlined: {:?}", t0.elapsed());
    // 読み込めなかった相対URLが残っても異常終了しないよう、基準URLを与える
    let base = format!("file:///{}/", dir.to_string_lossy().trim_start_matches(r"\\?\").replace('\\', "/"));
    // blitz::launch_static_html_cfgと同じ組み立て。違いは、文書を包むことと、データURI以外のネットワークを使わないこと
    let event_loop = create_default_event_loop();
    let (proxy, receiver) = BlitzShellProxy::new(event_loop.create_proxy());
    let net = DataUriNetProvider::shared(Some(Arc::new(proxy.clone())));
    let mut app = BlitzApplication::new(proxy.clone(), receiver);
    let doc = HtmlDocument::from_html(
        &html,
        DocumentConfig { base_url: Some(base), net_provider: Some(net), ..Default::default() },
    );
    let wrapped = KeyScrollDoc { doc, proxy };
    // 起動後にテーマを切り替えると、Blitzの再スタイルが一部の要素に及ばない（暗い背景に暗い文字が残る）。
    // そのため、ウィンドウの作成時に指定して、最初から暗いスタイルで描画する
    let attributes = WindowAttributes::default().with_theme(if dark { Some(Theme::Dark) } else { None });
    app.add_window(WindowConfig::with_attributes(Box::new(wrapped) as _, VelloWindowRenderer::new(), attributes));
    event_loop.run_app(app).unwrap();
}
