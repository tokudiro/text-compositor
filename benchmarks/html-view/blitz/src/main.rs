// Obunzuの代替となるネイティブ描画の試作。ObunzuのHTML出力を、JavaScriptなしのBlitzで表示する。
use std::path::Path;
use std::time::Instant;

use base64::Engine;

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

fn main() {
    let t0 = Instant::now();
    let path = std::env::args().nth(1).expect("usage: native-blitz <file.html>");
    let abs = std::fs::canonicalize(&path).expect("no such file");
    let dir = abs.parent().unwrap().to_path_buf();
    let html = std::fs::read_to_string(&abs).expect("read failed");
    let html = inline_images(&html, &dir);
    eprintln!("[trace] html read + images inlined: {:?}", t0.elapsed());
    // 読み込めなかった相対URLが残っても異常終了しないよう、基準URLを与える
    let base = format!("file:///{}/", dir.to_string_lossy().trim_start_matches(r"\\?\").replace('\\', "/"));
    blitz::launch_static_html_cfg(&html, blitz::shell::Config { stylesheets: Vec::new(), base_url: Some(base) });
}
