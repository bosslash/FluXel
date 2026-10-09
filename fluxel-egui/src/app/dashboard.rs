//! Dashboard controls and read-only workload visualizations.

use super::*;

impl FluxelApp {
    pub(super) fn dashboard_ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.heading("OPERATIONS OVERVIEW");
            ui.label(
                RichText::new("TASK WORKLOAD AND DEADLINE HEALTH")
                    .small()
                    .color(theme::MUTED),
            );
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui.button("Refresh").clicked() {
                    self.refresh_dashboard();
                }
            });
        });
        egui::Frame::new()
            .fill(theme::PANEL)
            .stroke(Stroke::new(1.0, theme::BORDER))
            .inner_margin(egui::Margin::symmetric(10, 6))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("DISPLAY").small().color(theme::MUTED));
                    for (index, label) in ["TODO", "DOING", "WAIT", "FINISH", "ARCHIVE"]
                        .iter()
                        .enumerate()
                    {
                        if ui
                            .selectable_label(self.dashboard_statuses[index], *label)
                            .clicked()
                        {
                            self.dashboard_statuses[index] = !self.dashboard_statuses[index];
                            self.refresh_dashboard();
                        }
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new(format!("{} TASKS", self.dashboard.remaining_total))
                                .small()
                                .color(theme::MUTED),
                        );
                    });
                });
            });
        ui.add_space(6.0);
        ui.columns(3, |columns| {
            metric_card(
                &mut columns[0],
                "TASKS IN SCOPE",
                self.dashboard.remaining_total,
                theme::ACCENT,
            );
            metric_card(
                &mut columns[1],
                "OVERDUE",
                self.dashboard.overdue_total,
                theme::RED,
            );
            metric_card(
                &mut columns[2],
                "DUE IN 7 DAYS",
                self.dashboard.due_in_7_days,
                Color32::from_rgb(209, 162, 75),
            );
        });
        ui.add_space(8.0);
        ui.columns(2, |columns| {
            donut_chart(&mut columns[0], &self.dashboard);
            deadline_chart(&mut columns[1], &self.dashboard);
        });
    }
}

pub(super) fn metric_card(ui: &mut egui::Ui, label: &str, value: usize, color: Color32) {
    egui::Frame::new()
        .fill(theme::PANEL)
        .stroke(Stroke::new(1.0, theme::BORDER))
        .inner_margin(egui::Margin::same(12))
        .show(ui, |ui| {
            ui.label(RichText::new(label).small().color(theme::MUTED));
            ui.label(
                RichText::new(value.to_string())
                    .size(28.0)
                    .strong()
                    .color(color),
            );
        });
}

pub(super) fn donut_chart(ui: &mut egui::Ui, snapshot: &DashboardSnapshot) {
    egui::Frame::new()
        .fill(theme::PANEL)
        .stroke(Stroke::new(1.0, theme::BORDER))
        .inner_margin(egui::Margin::same(12))
        .show(ui, |ui| {
            ui.label(RichText::new("IMPORTANCE MIX").strong());
            let size = Vec2::new(ui.available_width(), 220.0);
            let (rect, _) = ui.allocate_exact_size(size, Sense::hover());
            let center = rect.center();
            let radius = 72.0;
            let total = snapshot.importance_counts.iter().sum::<usize>().max(1) as f32;
            let colors = [
                theme::RED,
                theme::BLUE,
                theme::GREEN,
                Color32::from_gray(120),
            ];
            let mut angle = -std::f32::consts::FRAC_PI_2;
            for (count, color) in snapshot.importance_counts.iter().zip(colors) {
                let sweep = (*count as f32 / total) * std::f32::consts::TAU;
                let segments = (sweep.abs() * 24.0).ceil().max(2.0) as usize;
                let points = (0..=segments)
                    .map(|index| {
                        let value = angle + sweep * index as f32 / segments as f32;
                        center + Vec2::angled(value) * radius
                    })
                    .collect::<Vec<_>>();
                ui.painter()
                    .add(egui::Shape::line(points, Stroke::new(22.0, color)));
                angle += sweep;
            }
            ui.painter().text(
                center,
                Align2::CENTER_CENTER,
                snapshot.remaining_total.to_string(),
                FontId::proportional(24.0),
                theme::TEXT,
            );
            ui.painter().text(
                center + Vec2::new(0.0, 24.0),
                Align2::CENTER_CENTER,
                "TASKS",
                FontId::proportional(10.0),
                theme::MUTED,
            );
        });
}

pub(super) fn deadline_chart(ui: &mut egui::Ui, snapshot: &DashboardSnapshot) {
    egui::Frame::new()
        .fill(theme::PANEL)
        .stroke(Stroke::new(1.0, theme::BORDER))
        .inner_margin(egui::Margin::same(12))
        .show(ui, |ui| {
            ui.label(RichText::new("DEADLINE WORKLOAD").strong());
            let chart_size = Vec2::new(ui.available_width(), 220.0);
            let (rect, _) = ui.allocate_exact_size(chart_size, Sense::hover());
            let entries = snapshot.deadlines.iter().take(28).collect::<Vec<_>>();
            let max_total = entries
                .iter()
                .map(|(_, counts)| counts.iter().sum::<usize>())
                .max()
                .unwrap_or(1)
                .max(1) as f32;
            let bar_width = (rect.width() / entries.len().max(1) as f32).clamp(8.0, 28.0);
            let colors = [
                theme::RED,
                theme::BLUE,
                theme::GREEN,
                Color32::from_gray(120),
            ];
            for (index, (date, counts)) in entries.iter().enumerate() {
                let x = rect.left() + index as f32 * bar_width;
                let mut bottom = rect.bottom() - 24.0;
                for (count, color) in counts.iter().zip(colors) {
                    let height = *count as f32 / max_total * (rect.height() - 50.0);
                    let bar = egui::Rect::from_min_max(
                        egui::pos2(x + 2.0, bottom - height),
                        egui::pos2(x + bar_width - 2.0, bottom),
                    );
                    ui.painter().rect_filled(bar, 1.0, color);
                    bottom -= height;
                }
                if index % 4 == 0 {
                    ui.painter().text(
                        egui::pos2(x + bar_width / 2.0, rect.bottom() - 16.0),
                        Align2::CENTER_TOP,
                        format!("{}/{}", date.month(), date.day()),
                        FontId::proportional(9.0),
                        theme::MUTED,
                    );
                }
            }
        });
}
