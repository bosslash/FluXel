//! Task-search filters, keyboard selection, and result navigation.

use super::*;

impl FluxelApp {
    pub(super) fn refresh_search(&mut self) {
        if self.search_query.trim().is_empty()
            && self.search_status_filter.is_empty()
            && self.search_importance_filter.is_empty()
        {
            self.search_results.clear();
            self.search_selected_index = 0;
            return;
        }
        match self.storage.search_tasks(
            &self.search_query,
            self.search_include_archive,
            &self.search_status_filter,
            &self.search_importance_filter,
        ) {
            Ok(tasks) => {
                self.search_results = tasks;
                self.search_selected_index = self
                    .search_selected_index
                    .min(self.search_results.len().saturating_sub(1));
            }
            Err(error) => self.set_error(error),
        }
    }

    pub(super) fn search_window(&mut self, ctx: &egui::Context) {
        if !self.search_open {
            return;
        }
        let mut open = self.search_open;
        let mut selected = None;
        let mut changed = false;
        let escape_pressed = ctx.input(|input| input.key_pressed(Key::Escape));
        if ctx.input(|input| input.key_pressed(Key::ArrowDown)) && !self.search_results.is_empty() {
            self.search_selected_index =
                (self.search_selected_index + 1).min(self.search_results.len() - 1);
        }
        if ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
            self.search_selected_index = self.search_selected_index.saturating_sub(1);
        }
        if ctx.input(|input| input.key_pressed(Key::Enter)) {
            selected = self
                .search_results
                .get(self.search_selected_index)
                .map(|task| task.id.clone());
        }
        let focus_query = self.pending_focus == Some(FocusTarget::SearchQuery);
        if focus_query {
            self.pending_focus = None;
        }
        egui::Window::new("タスク検索")
            .open(&mut open)
            .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
            .collapsible(false)
            .default_width(620.0)
            .default_height(460.0)
            .show(ctx, |ui| {
                ui.horizontal_wrapped(|ui| {
                    let query_width = (ui.available_width() - 150.0).max(220.0);
                    let response = ui.add_sized(
                        [query_width, 32.0],
                        egui::TextEdit::singleline(&mut self.search_query)
                            .hint_text("タイトル・本文を検索"),
                    );
                    if focus_query {
                        response.request_focus();
                    }
                    changed |= response.changed();
                    changed |= ui
                        .checkbox(&mut self.search_include_archive, "Archiveを含む")
                        .changed();
                });
                ui.horizontal_wrapped(|ui| {
                    egui::ComboBox::from_id_salt("search-status")
                        .selected_text(if self.search_status_filter.is_empty() {
                            "全ステータス"
                        } else {
                            status_label(&self.search_status_filter)
                        })
                        .show_ui(ui, |ui| {
                            changed |= ui
                                .selectable_value(
                                    &mut self.search_status_filter,
                                    String::new(),
                                    "全ステータス",
                                )
                                .changed();
                            for status in STATUS_ORDER {
                                changed |= ui
                                    .selectable_value(
                                        &mut self.search_status_filter,
                                        status.to_owned(),
                                        status_label(status),
                                    )
                                    .changed();
                            }
                        });
                    egui::ComboBox::from_id_salt("search-importance")
                        .selected_text(match self.search_importance_filter.as_str() {
                            "high" => "高",
                            "medium" => "中",
                            "low" => "低",
                            _ => "全重要度",
                        })
                        .show_ui(ui, |ui| {
                            for (value, label) in [
                                ("", "全重要度"),
                                ("high", "高"),
                                ("medium", "中"),
                                ("low", "低"),
                            ] {
                                changed |= ui
                                    .selectable_value(
                                        &mut self.search_importance_filter,
                                        value.to_owned(),
                                        label,
                                    )
                                    .changed();
                            }
                        });
                });
                ui.separator();
                ScrollArea::vertical().show(ui, |ui| {
                    for (index, task) in self.search_results.iter().enumerate() {
                        let text = format!(
                            "{}  ·  {}  ·  {}",
                            task.name,
                            status_label(&task.status),
                            due_label(&task.end_date)
                        );
                        let response =
                            ui.selectable_label(index == self.search_selected_index, text);
                        if response.clicked() {
                            self.search_selected_index = index;
                        }
                        if response.double_clicked() {
                            selected = Some(task.id.clone());
                        }
                        let preview = preview(&task.description, 120);
                        if !preview.is_empty() {
                            ui.label(RichText::new(preview).small().color(theme::MUTED));
                        }
                        ui.separator();
                    }
                });
            });
        if escape_pressed {
            open = false;
        }
        self.search_open = open;
        if changed {
            self.refresh_search();
        }
        if let Some(id) = selected {
            self.search_open = false;
            self.open_task(&id);
        }
    }
}
