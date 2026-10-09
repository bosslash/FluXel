//! Settings, backup/export, and shared-tag management.

use super::*;

impl FluxelApp {
    pub(super) fn settings_ui(&mut self, ui: &mut egui::Ui) {
        ui.heading("SETTINGS");
        ui.label(
            RichText::new(
                "Manage storage, workflow preferences, backups, and application maintenance.",
            )
            .color(theme::MUTED),
        );
        ui.add_space(8.0);
        settings_card(ui, "USER DATA", |ui| {
            path_row(ui, "Database directory", &self.storage.paths.database_dir);
            path_row(ui, "Settings file", &self.storage.paths.settings_file);
            path_row(ui, "Tasks DB", &self.storage.paths.tasks_db());
        });
        ui.add_space(8.0);
        let mut browse_sync = false;
        let mut save = false;
        let mut sync_now = false;
        let mut open_sync = false;
        settings_card(ui, "KANBAN / SYNC", |ui| {
            ui.horizontal(|ui| {
                ui.label("Finish → Archive の日数");
                ui.add(egui::DragValue::new(&mut self.settings.archive_after_days).range(1..=365));
            });
            ui.horizontal_wrapped(|ui| {
                ui.label("同期フォルダー");
                let field_width = (ui.available_width() - 70.0).clamp(180.0, 520.0);
                ui.add_sized(
                    [field_width, 32.0],
                    egui::TextEdit::singleline(&mut self.settings.sync_folder),
                );
                if ui.button("選択").clicked() {
                    browse_sync = true;
                }
            });
            if ui.button("設定を保存").clicked() {
                save = true;
            }
            ui.horizontal(|ui| {
                if ui
                    .button(format!("同期を実行  {PRIMARY_KEY_LABEL}S"))
                    .clicked()
                {
                    sync_now = true;
                }
                if ui.button("同期フォルダーを開く").clicked() {
                    open_sync = true;
                }
            });
            if !self.settings.sync_folder.trim().is_empty() {
                let folder = std::path::Path::new(self.settings.sync_folder.trim());
                match fluxel_egui::sync::inspect(folder) {
                    Ok(summary) if summary.initialized => {
                        ui.label(
                            RichText::new(format!(
                                "{} events · {} active items · {} devices",
                                summary.event_count,
                                summary.active_item_count,
                                summary.device_count
                            ))
                            .small()
                            .color(theme::MUTED),
                        );
                    }
                    Ok(_) => {
                        ui.label(
                            RichText::new("最初の同期時に互換形式の同期領域を作成します")
                                .small()
                                .color(theme::MUTED),
                        );
                    }
                    Err(error) => {
                        ui.label(RichText::new(error.to_string()).small().color(theme::RED));
                    }
                }
            }
        });
        if browse_sync && let Some(path) = rfd::FileDialog::new().pick_folder() {
            self.settings.sync_folder = path.display().to_string();
        }
        if save {
            match self.settings.save(&self.storage.paths.settings_file) {
                Ok(()) => {
                    self.refresh_tasks();
                    self.set_message("設定を保存しました");
                }
                Err(error) => self.set_error(error),
            }
        }
        if sync_now {
            self.run_sync();
        }
        if open_sync {
            let folder = self.settings.sync_folder.trim();
            if folder.is_empty() {
                self.set_message("同期フォルダーを設定してください");
            } else if let Err(error) = open::that(folder) {
                self.set_error(error);
            }
        }
        ui.add_space(8.0);
        let mut export_settings = false;
        let mut export_tasks = false;
        settings_card(ui, "BACKUP / EXPORT", |ui| {
            ui.horizontal(|ui| {
                if ui.button("settings.ini をエクスポート").clicked() {
                    export_settings = true;
                }
                if ui.button("Tasks.db をエクスポート").clicked() {
                    export_tasks = true;
                }
            });
            ui.label(
                RichText::new("実行中のDBもSQLiteのバックアップ機能で安全に書き出します。")
                    .small()
                    .color(theme::MUTED),
            );
        });
        if export_settings
            && let Some(path) = rfd::FileDialog::new()
                .set_file_name("Fluxel_settings.ini")
                .save_file()
        {
            let result = self
                .settings
                .save(&self.storage.paths.settings_file)
                .and_then(|()| self.storage.export_settings(&path));
            match result {
                Ok(()) => {
                    self.settings.export_ini_path = path.display().to_string();
                    let _ = self.settings.save(&self.storage.paths.settings_file);
                    self.set_message("settings.ini をエクスポートしました");
                }
                Err(error) => self.set_error(error),
            }
        }
        if export_tasks
            && let Some(path) = rfd::FileDialog::new()
                .set_file_name("Fluxel_Tasks.db")
                .save_file()
        {
            match self.storage.export_tasks_db(&path) {
                Ok(()) => {
                    self.settings.export_sql_path = path.display().to_string();
                    let _ = self.settings.save(&self.storage.paths.settings_file);
                    self.set_message("Tasks.db をエクスポートしました");
                }
                Err(error) => self.set_error(error),
            }
        }
        ui.add_space(8.0);
        let tags = match self.storage.known_tags() {
            Ok(tags) => tags,
            Err(error) => {
                self.set_error(error);
                Vec::new()
            }
        };
        let mut add_tags = false;
        let mut delete_tag = None;
        settings_card(ui, "TAGS", |ui| {
            ui.label("ShortCut / OpenFile 共通タグ");
            ui.horizontal(|ui| {
                ui.add_sized(
                    [280.0, 32.0],
                    egui::TextEdit::singleline(&mut self.tag_input)
                        .hint_text("追加するタグ（カンマ区切り）"),
                );
                if ui.button("追加").clicked() {
                    add_tags = true;
                }
            });
            ui.horizontal_wrapped(|ui| {
                for tag in &tags {
                    if ui.button(format!("{tag}  ×")).clicked() {
                        delete_tag = Some(tag.clone());
                    }
                }
            });
        });
        if add_tags && !self.tag_input.trim().is_empty() {
            match self.storage.add_known_tags(&self.tag_input) {
                Ok(()) => {
                    self.tag_input.clear();
                    self.set_message("タグを追加しました");
                }
                Err(error) => self.set_error(error),
            }
        }
        if let Some(tag) = delete_tag {
            match self.storage.delete_known_tag(&tag) {
                Ok(()) => {
                    self.refresh_quick(QuickAccessKind::Shortcut);
                    self.refresh_quick(QuickAccessKind::OpenFile);
                    self.set_message("タグを削除しました");
                }
                Err(error) => self.set_error(error),
            }
        }
        ui.add_space(8.0);
        settings_card(ui, "APPLICATION", |ui| {
            ui.label("Fluxel egui 0.1.0");
            ui.label(RichText::new("既存SQLite形式と互換のRust/egui版").color(theme::MUTED));
        });
    }

    /// Runs the Python-compatible append-only folder synchronization.
    pub(super) fn run_sync(&mut self) {
        let folder = self.settings.sync_folder.trim();
        if folder.is_empty() {
            self.select_page(Page::Settings);
            self.set_message("同期フォルダーを設定してください");
            return;
        }
        match fluxel_egui::sync::synchronize(&self.storage, std::path::Path::new(folder)) {
            Ok(report) => {
                self.refresh_all();
                self.set_message(format!(
                    "同期完了: 受信 {} / 送信 {} / 削除 {} / 競合 {}",
                    report.downloaded, report.uploaded, report.deleted, report.conflicts
                ));
            }
            Err(error) => self.set_error(error),
        }
    }
}
