//! Reusable editor and settings widgets.

use super::*;

pub(super) fn editor_buttons(
    ui: &mut egui::Ui,
    is_new: bool,
    delete_armed: &mut bool,
    save: &mut bool,
    delete: &mut bool,
    close_requested: &mut bool,
) {
    ui.horizontal(|ui| {
        if ui.button("保存").clicked() {
            *save = true;
        }
        if ui.button("キャンセル").clicked() {
            *close_requested = true;
        }
        if !is_new {
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if *delete_armed {
                    if ui
                        .button(RichText::new("削除を確定").color(theme::RED))
                        .clicked()
                    {
                        *delete = true;
                    }
                    if ui.button("戻る").clicked() {
                        *delete_armed = false;
                    }
                } else if ui.button(RichText::new("削除").color(theme::RED)).clicked() {
                    *delete_armed = true;
                }
            });
        }
    });
}

pub(super) fn date_editor(ui: &mut egui::Ui, date: &mut NaiveDate) {
    let mut year = date.year();
    let mut month = date.month();
    let mut day = date.day();
    let mut changed = false;
    ui.spacing_mut().item_spacing.x = 3.0;
    changed |= ui
        .add_sized(
            [64.0, 28.0],
            egui::DragValue::new(&mut year).range(1970..=2200),
        )
        .changed();
    ui.label("/");
    changed |= ui
        .add_sized([42.0, 28.0], egui::DragValue::new(&mut month).range(1..=12))
        .changed();
    ui.label("/");
    changed |= ui
        .add_sized([42.0, 28.0], egui::DragValue::new(&mut day).range(1..=31))
        .changed();
    if changed {
        while NaiveDate::from_ymd_opt(year, month, day).is_none() && day > 1 {
            day -= 1;
        }
        if let Some(value) = NaiveDate::from_ymd_opt(year, month, day) {
            *date = value;
        }
    }
}

pub(super) fn settings_card(ui: &mut egui::Ui, title: &str, content: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(theme::PANEL)
        .stroke(Stroke::new(1.0, theme::BORDER))
        .corner_radius(8)
        .inner_margin(egui::Margin::same(14))
        .show(ui, |ui| {
            ui.label(RichText::new(title).strong().color(Color32::WHITE));
            ui.separator();
            content(ui);
        });
}

/// Paints one line inside a strict width and adds an ellipsis when it does not fit.
///
/// Painter text normally extends beyond the allocated widget, which can make dense
/// boards and timelines overlap adjacent columns. Keeping this behavior in one helper
/// gives every custom-painted row the same clipping and vertical alignment.
pub(super) fn paint_elided_text(
    ui: &egui::Ui,
    position: egui::Pos2,
    text: impl Into<String>,
    font_id: FontId,
    color: Color32,
    max_width: f32,
) {
    let mut job = egui::text::LayoutJob::simple(text.into(), font_id, color, max_width.max(1.0));
    job.wrap.max_rows = 1;
    job.wrap.break_anywhere = true;
    job.wrap.overflow_character = Some('…');
    let galley = ui.fonts_mut(|fonts| fonts.layout_job(job));
    let top_left = egui::pos2(position.x, position.y - galley.size().y / 2.0);
    ui.painter().galley(top_left, galley, color);
}

pub(super) fn path_row(ui: &mut egui::Ui, label: &str, path: &std::path::Path) {
    ui.label(RichText::new(label).small().color(theme::MUTED));
    ui.horizontal_top(|ui| {
        let button_space = 60.0;
        ui.add_sized(
            [(ui.available_width() - button_space).max(180.0), 32.0],
            egui::Label::new(RichText::new(path.display().to_string()).color(theme::TEXT)).wrap(),
        );
        if ui.small_button("開く").clicked() {
            let _ = open::that(path);
        }
    });
}
