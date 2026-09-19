// 起動時間・PDF表示時間の計測用の最小アプリ（#166）。C#版（Avalonia）と同じ流れで、ウィンドウを開き、
// PDFの1ページ目をPDFiumで描画してテクスチャにし、標準出力へ計測値を出して終了する。
use eframe::egui;
use pdfium_render::prelude::*;
use std::io::Write;
use std::time::Instant;

struct App {
    pdf_path: String,
    texture: Option<egui::TextureHandle>,
    frame: u32,
    text: String,
    zoom: usize,
    auto: bool,
}

fn render(pdfium: &Pdfium, path: &str, target_width: i32) -> egui::ColorImage {
    let doc = pdfium.load_pdf_from_file(path, None).expect("load pdf");
    let page = doc.pages().get(0).expect("page 0");
    let config = PdfRenderConfig::new().set_target_width(target_width);
    let img = page.render_with_config(&config).expect("render").as_image().expect("image").to_rgba8();
    let size = [img.width() as usize, img.height() as usize];
    egui::ColorImage::from_rgba_unmultiplied(size, img.as_raw())
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.frame += 1;
        if self.frame == 1 {
            // 最初のフレームを描画した時点
            println!("first_frame");
            std::io::stdout().flush().ok();
            ctx.request_repaint();
            return;
        }
        if self.frame == 2 {
            let pdfium = Pdfium::new(
                Pdfium::bind_to_library(Pdfium::pdfium_platform_library_name_at_path("./")).expect("bind pdfium"),
            );
            // 96dpiで、A4の幅（8.27インチ）に相当する約794px
            let t = Instant::now();
            let image = render(&pdfium, &self.pdf_path, 794);
            self.texture = Some(ctx.load_texture("page", image, Default::default()));
            println!("pdf_ms={:.1}", t.elapsed().as_secs_f64() * 1000.0);

            let t = Instant::now();
            for _ in 0..5 {
                let image = render(&pdfium, &self.pdf_path, 794);
                self.texture = Some(ctx.load_texture("page", image, Default::default()));
            }
            println!("pdf_warm_96dpi_ms={:.1}", t.elapsed().as_secs_f64() * 1000.0 / 5.0);
            let t = Instant::now();
            for _ in 0..5 {
                let image = render(&pdfium, &self.pdf_path, 1654);
                self.texture = Some(ctx.load_texture("page", image, Default::default()));
            }
            println!("pdf_warm_200dpi_ms={:.1}", t.elapsed().as_secs_f64() * 1000.0 / 5.0);
            std::io::stdout().flush().ok();
            if std::env::var("HOLD").as_deref() != Ok("1") {
                std::process::exit(0);
            }
        }
        // 見た目の比較用: ツールバー・ボタン・コンボボックス・入力欄・ステータスバーを、日本語で並べる
        egui::Panel::top("toolbar").show_inside(ui, |ui| {
            ui.horizontal(|ui| {
                ui.button("開く…");
                ui.button("再読み込み");
                egui::ComboBox::from_id_salt("zoom")
                    .selected_text(["50%", "100%", "150%", "200%"][self.zoom])
                    .show_ui(ui, |ui| {
                        for (i, l) in ["50%", "100%", "150%", "200%"].iter().enumerate() {
                            ui.selectable_value(&mut self.zoom, i, *l);
                        }
                    });
                ui.checkbox(&mut self.auto, "自動で更新");
                ui.add(egui::TextEdit::singleline(&mut self.text).desired_width(220.0));
            });
        });
        egui::Panel::bottom("status").show_inside(ui, |ui| {
            ui.label("更新 12ms ／ 図表 3件（キャッシュ命中）— ビルドエラーはここに表示します");
        });
        egui::CentralPanel::default().show_inside(ui, |ui| {
            if let Some(tex) = &self.texture {
                ui.image(tex);
            }
        });
        ctx.request_repaint();
    }
}

fn main() -> eframe::Result {
    let pdf_path = std::env::args().nth(1).unwrap_or_else(|| "test.pdf".to_string());
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([800.0, 1000.0]),
        ..Default::default()
    };
    eframe::run_native(
        "startup-rs",
        options,
        Box::new(|cc| {
            if let Ok(path) = std::env::var("CJK_FONT") {
                let bytes = std::fs::read(path).expect("read font");
                let mut fonts = egui::FontDefinitions::default();
                fonts.font_data.insert("cjk".to_owned(), std::sync::Arc::new(egui::FontData::from_owned(bytes)));
                fonts.families.get_mut(&egui::FontFamily::Proportional).unwrap().insert(0, "cjk".to_owned());
                fonts.families.get_mut(&egui::FontFamily::Monospace).unwrap().push("cjk".to_owned());
                cc.egui_ctx.set_fonts(fonts);
            }
            Ok(Box::new(App { pdf_path, texture: None, frame: 0, text: "日本語の入力欄：検索".to_string(), zoom: 1, auto: true }))
        }),
    )
}
