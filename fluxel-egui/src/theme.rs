use eframe::egui::{self, Color32, CornerRadius, Stroke, TextStyle};

pub const BG: Color32 = Color32::from_rgb(21, 24, 29);
pub const PANEL: Color32 = Color32::from_rgb(29, 33, 39);
pub const PANEL_ALT: Color32 = Color32::from_rgb(32, 36, 42);
pub const BORDER: Color32 = Color32::from_rgb(52, 59, 70);
pub const TEXT: Color32 = Color32::from_rgb(232, 232, 232);
pub const MUTED: Color32 = Color32::from_rgb(146, 157, 172);
pub const ACCENT: Color32 = Color32::from_rgb(92, 156, 204);
pub const RED: Color32 = Color32::from_rgb(229, 57, 53);
pub const BLUE: Color32 = Color32::from_rgb(30, 136, 229);
pub const GREEN: Color32 = Color32::from_rgb(67, 160, 71);
pub const ORANGE: Color32 = Color32::from_rgb(255, 152, 0);

pub fn apply(ctx: &egui::Context) {
    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = BG;
    visuals.window_fill = PANEL;
    visuals.extreme_bg_color = Color32::from_rgb(18, 20, 24);
    visuals.faint_bg_color = PANEL_ALT;
    visuals.widgets.noninteractive.bg_fill = PANEL;
    visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, BORDER);
    visuals.widgets.inactive.bg_fill = PANEL_ALT;
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, BORDER);
    visuals.widgets.hovered.bg_fill = Color32::from_rgb(48, 55, 65);
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, ACCENT);
    visuals.widgets.active.bg_fill = Color32::from_rgb(40, 68, 91);
    visuals.widgets.active.bg_stroke = Stroke::new(1.0, ACCENT);
    visuals.widgets.noninteractive.corner_radius = CornerRadius::same(6);
    visuals.widgets.inactive.corner_radius = CornerRadius::same(6);
    visuals.widgets.hovered.corner_radius = CornerRadius::same(6);
    visuals.widgets.active.corner_radius = CornerRadius::same(6);
    visuals.widgets.open.corner_radius = CornerRadius::same(6);
    visuals.selection.bg_fill = Color32::from_rgb(40, 68, 91);
    visuals.selection.stroke = Stroke::new(1.0, ACCENT);
    visuals.window_corner_radius = CornerRadius::same(8);
    ctx.set_visuals(visuals);

    let mut style = (*ctx.style_of(egui::Theme::Dark)).clone();
    style.spacing.item_spacing = egui::vec2(9.0, 8.0);
    style.spacing.button_padding = egui::vec2(13.0, 7.0);
    style.spacing.interact_size = egui::vec2(40.0, 32.0);
    style.spacing.text_edit_width = 280.0;
    style.spacing.window_margin = egui::Margin::same(16);
    style
        .text_styles
        .insert(TextStyle::Heading, egui::FontId::proportional(21.0));
    style
        .text_styles
        .insert(TextStyle::Body, egui::FontId::proportional(14.0));
    style
        .text_styles
        .insert(TextStyle::Button, egui::FontId::proportional(13.0));
    style
        .text_styles
        .insert(TextStyle::Small, egui::FontId::proportional(11.0));
    ctx.set_style_of(egui::Theme::Dark, style);
}

pub fn importance_color(value: &str) -> Color32 {
    match value.trim().to_lowercase().as_str() {
        "高" | "high" => RED,
        "中" | "medium" | "middle" => BLUE,
        "低" | "low" => GREEN,
        _ => Color32::from_gray(158),
    }
}

pub fn color_from_hex(value: &str) -> Color32 {
    let raw = value.trim().trim_start_matches('#');
    if raw.len() == 6
        && let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&raw[0..2], 16),
            u8::from_str_radix(&raw[2..4], 16),
            u8::from_str_radix(&raw[4..6], 16),
        )
    {
        return Color32::from_rgb(r, g, b);
    }
    ACCENT
}
