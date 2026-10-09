#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod fonts;

use app::FluxelApp;
use eframe::egui;
use fluxel_egui::{paths::AppPaths, storage::Storage};

fn main() -> eframe::Result {
    let paths = AppPaths::discover().expect("Fluxel data directory could not be initialized");
    let storage = Storage::new(paths).expect("Fluxel SQLite databases could not be initialized");
    let options = eframe::NativeOptions {
        renderer: eframe::Renderer::Glow,
        viewport: egui::ViewportBuilder::default()
            .with_title("Fluxel")
            .with_inner_size([1440.0, 820.0])
            .with_min_inner_size([480.0, 620.0])
            .with_app_id("Fluxel"),
        ..Default::default()
    };
    eframe::run_native(
        "Fluxel",
        options,
        Box::new(move |cc| Ok(Box::new(FluxelApp::new(cc, storage)))),
    )
}
