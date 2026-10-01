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

// 生成HTMLは、ダークモードで、画像に`filter: invert(1) hue-rotate(180deg)`と`mix-blend-mode: lighten`をかけて、
// 明るい図を暗い背景になじませる。Blitzは、どちらも描かない。そこで、同じ計算を、SVGの色の値に、読み込み前に適用する
// （透明な背景は、そのまま透明）。ラスター画像（PNG等）は、変換しない。
// ダークモードのページの背景色（生成HTMLの`--bg`）。`mix-blend-mode: lighten`は、反転で黒になった背景を、ページの色に溶かす。
// 同じ効果として、純白の色は、反転せず、この色にする
const DARK_PAGE_BG: (f64, f64, f64) = (13.0 / 255.0, 17.0 / 255.0, 23.0 / 255.0);

// ダークモードの色の変換。純白は、ページの背景色。ほかは、フィルターの計算に、明るさの下限の補正を足す
fn dark_rgb(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    if r > 0.999 && g > 0.999 && b > 0.999 {
        return DARK_PAGE_BG;
    }
    dark_rgb_adjusted(r, g, b)
}

// CSSの`filter: invert(1) hue-rotate(180deg)`と同じ計算
fn dark_rgb_filter(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    // invert(1)
    let (r, g, b) = (1.0 - r, 1.0 - g, 1.0 - b);
    // hue-rotate(180deg)の行列（cos = -1, sin = 0）
    let nr = -0.574 * r + 1.430 * g + 0.144 * b;
    let ng = 0.426 * r + 0.430 * g + 0.144 * b;
    let nb = 0.426 * r + 1.430 * g - 0.856 * b;
    (nr.clamp(0.0, 1.0), ng.clamp(0.0, 1.0), nb.clamp(0.0, 1.0))
}

fn rgb_to_hsl(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let l = (max + min) / 2.0;
    let d = max - min;
    if d < 1e-9 {
        return (0.0, 0.0, l);
    }
    let s = d / (1.0 - (2.0 * l - 1.0).abs());
    let h = if (max - r).abs() < 1e-9 {
        60.0 * (((g - b) / d) % 6.0)
    } else if (max - g).abs() < 1e-9 {
        60.0 * ((b - r) / d + 2.0)
    } else {
        60.0 * ((r - g) / d + 4.0)
    };
    (h.rem_euclid(360.0), s, l)
}

// マインドマップ・タイムライン・カンバンなどは、明るさが中間の、彩度の高い色（淡い黄・緑・紫）を、節や線に使う。
// 反転すると、ほぼ黒になり、暗い背景と線が溶けて見えない。そこで、そうした色は、反転の結果の明るさに、下限を設ける
const DARK_MIN_LIGHTNESS: f64 = 0.30;

fn dark_rgb_adjusted(r: f64, g: f64, b: f64) -> (f64, f64, f64) {
    let (nr, ng, nb) = dark_rgb_filter(r, g, b);
    let (_, s0, l0) = rgb_to_hsl(r, g, b);
    if s0 > 0.5 && (0.5..0.9).contains(&l0) {
        let (h, s, l) = rgb_to_hsl(nr, ng, nb);
        if l < DARK_MIN_LIGHTNESS {
            return hsl_to_rgb(h, s, DARK_MIN_LIGHTNESS);
        }
    }
    (nr, ng, nb)
}

fn hsl_to_rgb(h: f64, s: f64, l: f64) -> (f64, f64, f64) {
    let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let hp = (h.rem_euclid(360.0)) / 60.0;
    let x = c * (1.0 - (hp % 2.0 - 1.0).abs());
    let (r, g, b) = match hp as u32 {
        0 => (c, x, 0.0),
        1 => (x, c, 0.0),
        2 => (0.0, c, x),
        3 => (0.0, x, c),
        4 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    let m = l - c / 2.0;
    (r + m, g + m, b + m)
}

// Mermaidは、まれに不正な色（例: `hsl(240, 100%, NaN%)`。ポジションマップの点）を出力する。Chromiumは、不正な属性値を
// 無視して、既定の黒で塗る。Blitzも黒で塗るが、ダークモードの変換（黒→白）の対象にならず、暗い背景に黒い点が残る。
// そこで、不正な色を、明示的に黒にしておく（ライトでは、Chromiumと同じ見た目。ダークでは、変換で白になる）
fn fix_invalid_colors(svg: &str) -> String {
    let mut out = String::with_capacity(svg.len());
    let mut rest = svg;
    while let Some(i) = rest.find("hsl(") {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        match tail.find(')') {
            Some(end) if tail[..end].contains("NaN") => {
                out.push_str("#000000");
                rest = &tail[end + 1..];
            }
            Some(end) => {
                out.push_str(&tail[..end + 1]);
                rest = &tail[end + 1..];
            }
            None => {
                out.push_str(tail);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out
}

fn hex_digit_run(s: &str) -> usize {
    s.bytes().take_while(|c| c.is_ascii_hexdigit()).count()
}

fn dark_svg(svg: &str) -> String {
    let mut out = String::with_capacity(svg.len());
    let mut i = 0;
    let b = svg.as_bytes();
    while i < b.len() {
        let rest = &svg[i..];
        // #rgb・#rrggbb（#rgba・#rrggbbaaは、アルファを保つ）。`#mermaid-...`のようなIDは、16進数だけでないので、除く
        if b[i] == b'#' {
            let n = hex_digit_run(&rest[1..]);
            let next_is_ident = rest.as_bytes().get(1 + n).map_or(false, |c| c.is_ascii_alphanumeric() || *c == b'-' || *c == b'_');
            if matches!(n, 3 | 4 | 6 | 8) && !next_is_ident {
                let h = &rest[1..1 + n];
                let comp = |k: usize| -> f64 {
                    let v = if n <= 4 {
                        u8::from_str_radix(&h[k..k + 1].repeat(2), 16).unwrap_or(0)
                    } else {
                        u8::from_str_radix(&h[2 * k..2 * k + 2], 16).unwrap_or(0)
                    };
                    v as f64 / 255.0
                };
                let (r, g, bl) = dark_rgb(comp(0), comp(1), comp(2));
                let to8 = |v: f64| (v * 255.0).round() as u8;
                out.push_str(&format!("#{:02x}{:02x}{:02x}", to8(r), to8(g), to8(bl)));
                // アルファ（#rgbaは、1桁を2桁に広げる）は、そのまま保つ
                match n {
                    4 => out.push_str(&h[3..4].repeat(2)),
                    8 => out.push_str(&h[6..8]),
                    _ => {}
                }
                i += 1 + n;
                continue;
            }
        }
        // rgb(r, g, b)・rgba(r, g, b, a)
        let fun = if rest.starts_with("rgba(") { Some(5) } else if rest.starts_with("rgb(") { Some(4) } else { None };
        if let Some(skip) = fun {
            if let Some(end) = rest.find(')') {
                let parts: Vec<&str> = rest[skip..end].split(',').map(|p| p.trim()).collect();
                let nums: Option<Vec<f64>> = parts.iter().take(3).map(|p| p.parse::<f64>().ok()).collect();
                if let (Some(n3), true) = (nums, parts.len() >= 3) {
                    let (r, g, bl) = dark_rgb(n3[0] / 255.0, n3[1] / 255.0, n3[2] / 255.0);
                    let alpha = parts.get(3).map(|a| format!(", {a}")).unwrap_or_default();
                    let name = if skip == 5 { "rgba" } else { "rgb" };
                    out.push_str(&format!("{name}({}, {}, {}{alpha})", (r * 255.0).round(), (g * 255.0).round(), (bl * 255.0).round()));
                    i += end + 1;
                    continue;
                }
            }
        }
        // hsl(h, s%, l%)・hsla(h, s%, l%, a)（Mermaidが、背景の色に使う）
        let hsl = if rest.starts_with("hsla(") { Some(5) } else if rest.starts_with("hsl(") { Some(4) } else { None };
        if let Some(skip) = hsl {
            if let Some(end) = rest.find(')') {
                let parts: Vec<&str> = rest[skip..end].split(',').map(|p| p.trim()).collect();
                let num = |k: usize| parts.get(k).and_then(|p| p.trim_end_matches('%').trim_end_matches("deg").parse::<f64>().ok());
                if let (Some(h), Some(sat), Some(lig)) = (num(0), num(1), num(2)) {
                    let (r, g, bl) = hsl_to_rgb(h, sat / 100.0, lig / 100.0);
                    let (r, g, bl) = dark_rgb(r, g, bl);
                    let alpha = parts.get(3).map(|a| format!(", {a}")).unwrap_or_default();
                    let name = if skip == 5 { "rgba" } else { "rgb" };
                    out.push_str(&format!("{name}({}, {}, {}{alpha})", (r * 255.0).round(), (g * 255.0).round(), (bl * 255.0).round()));
                    i += end + 1;
                    continue;
                }
            }
        }
        // 色名（white・black）。値の位置（`:`か`="`の直後）だけ
        let mut matched = false;
        for (name, to) in [("white", "#0d1117"), ("black", "#ffffff")] {
            let after = rest.starts_with(name) && !rest.as_bytes().get(name.len()).map_or(false, |c| c.is_ascii_alphanumeric() || *c == b'-');
            let before = i > 0 && matches!(b[i - 1], b':' | b'"' | b' ') && (i < 2 || matches!(b[i - 1], b':' | b'"') || b[i - 2] == b':');
            if after && before {
                out.push_str(to);
                i += name.len();
                matched = true;
                break;
            }
        }
        if matched {
            continue;
        }
        // 1文字進める（UTF-8の境界を守る）
        let ch = rest.chars().next().unwrap();
        out.push(ch);
        i += ch.len_utf8();
    }
    out
}

// Blitz 0.3.0-beta.2のfile://読み込みは、Windowsで"/C:/..."というパスをそのまま開こうとして失敗する。
// 回避として、<img src="相対パス">を、読み込み前にデータURIへ置き換える。
fn inline_images(html: &str, dir: &Path, dark: bool) -> String {
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
                                let s = fix_invalid_colors(&s.replace("sans-serif", "'Noto Sans JP',sans-serif"));
                                bytes = if dark { dark_svg(&s) } else { s }.into_bytes();
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
    let html = inline_images(&html, &dir, dark);

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
