//! System-font setup shared by every screen.

use eframe::egui::{self, FontData, FontDefinitions, FontFamily, FontTweak};

/// Installs Japanese and Latin system fonts with a small baseline correction.
///
/// egui's built-in font metrics place the system glyphs slightly high on both
/// macOS and Windows. Keeping the correction here prevents individual widgets
/// from accumulating platform-specific offsets.
pub fn configure(ctx: &egui::Context) {
    let system_fonts = system_fonts::find_from_presets(
        [
            system_fonts::FontPreset::Japanese,
            system_fonts::FontPreset::Latin,
        ],
        system_fonts::FontStyle::Sans,
    );
    let mut definitions = FontDefinitions::default();
    let mut keys = Vec::new();

    for font in system_fonts {
        let bytes = match font.source {
            system_fonts::FoundFontSource::Path(path) => match std::fs::read(path) {
                Ok(bytes) => bytes,
                Err(_) => continue,
            },
            system_fonts::FoundFontSource::Bytes(bytes) => bytes.as_ref().to_vec(),
        };
        let data = FontData::from_owned(bytes).tweak(FontTweak {
            y_offset: 1.0,
            ..Default::default()
        });
        definitions
            .font_data
            .insert(font.key.clone(), std::sync::Arc::new(data));
        keys.push(font.key);
    }

    for key in keys.into_iter().rev() {
        definitions
            .families
            .entry(FontFamily::Proportional)
            .or_default()
            .insert(0, key.clone());
        definitions
            .families
            .entry(FontFamily::Monospace)
            .or_default()
            .insert(0, key);
    }
    ctx.set_fonts(definitions);
}
