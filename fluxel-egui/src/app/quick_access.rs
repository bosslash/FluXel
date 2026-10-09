//! Shortcut and OpenFile lists, editors, execution, and usage tracking.

use super::*;

impl FluxelApp {
    pub(super) fn quick_access_ui(&mut self, ui: &mut egui::Ui, kind: QuickAccessKind) {
        let is_shortcut = kind == QuickAccessKind::Shortcut;
        let (title, add_label) = if is_shortcut {
            ("よく使うテキストを検索・保存", "＋ テキストを保存")
        } else {
            ("ファイルやフォルダーを検索・保存", "＋ パスを保存")
        };
        ui.heading(title);
        let mut changed = false;
        ui.horizontal_wrapped(|ui| {
            if ui.button(add_label).clicked() {
                self.pending_focus = Some(FocusTarget::QuickTitle);
                self.quick_editor = Some(QuickEditor {
                    kind,
                    item: QuickAccessItem::default(),
                    delete_armed: false,
                });
            }
            if !is_shortcut
                && ui.button("ファイル選択から追加").clicked()
                && let Some(path) = rfd::FileDialog::new().pick_file()
            {
                self.pending_focus = Some(FocusTarget::QuickTitle);
                self.quick_editor = Some(QuickEditor {
                    kind,
                    item: QuickAccessItem {
                        title: path
                            .file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("File")
                            .to_owned(),
                        value: path.display().to_string(),
                        ..QuickAccessItem::default()
                    },
                    delete_armed: false,
                });
            }
        });
        ui.add_space(4.0);
        let focus_search = self.pending_focus == Some(FocusTarget::QuickSearch);
        if focus_search {
            self.pending_focus = None;
        }
        ui.columns(2, |columns| {
            if is_shortcut {
                let response = columns[0].add_sized(
                    [columns[0].available_width(), 32.0],
                    egui::TextEdit::singleline(&mut self.shortcut_query)
                        .hint_text("検索  / でフォーカス"),
                );
                if focus_search {
                    response.request_focus();
                }
                changed |= response.changed();
                changed |= columns[1]
                    .add_sized(
                        [columns[1].available_width(), 32.0],
                        egui::TextEdit::singleline(&mut self.shortcut_tag_query)
                            .hint_text("タグで絞り込み"),
                    )
                    .changed();
            } else {
                let response = columns[0].add_sized(
                    [columns[0].available_width(), 32.0],
                    egui::TextEdit::singleline(&mut self.openfile_query)
                        .hint_text("検索  / でフォーカス"),
                );
                if focus_search {
                    response.request_focus();
                }
                changed |= response.changed();
                changed |= columns[1]
                    .add_sized(
                        [columns[1].available_width(), 32.0],
                        egui::TextEdit::singleline(&mut self.openfile_tag_query)
                            .hint_text("タグで絞り込み"),
                    )
                    .changed();
            }
        });
        if changed {
            self.refresh_quick(kind);
        }
        ui.separator();

        let items = if is_shortcut {
            self.shortcut_items.clone()
        } else {
            self.openfile_items.clone()
        };
        let mut edit = None;
        let mut execute = None;
        ScrollArea::vertical().show(ui, |ui| {
            for item in items {
                egui::Frame::new()
                    .fill(theme::PANEL)
                    .stroke(Stroke::new(1.0, theme::BORDER))
                    .corner_radius(5)
                    .inner_margin(egui::Margin::same(10))
                    .show(ui, |ui| {
                        ui.set_min_width(ui.available_width());
                        ui.horizontal(|ui| {
                            ui.label(RichText::new(&item.title).strong());
                            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                                if ui.button("編集").clicked() {
                                    edit = Some(item.clone());
                                }
                                if ui
                                    .button(if is_shortcut { "実行" } else { "開く" })
                                    .clicked()
                                {
                                    execute = Some(item.clone());
                                }
                                ui.label(
                                    RichText::new(format!("{}回", item.use_count))
                                        .small()
                                        .color(theme::MUTED),
                                );
                            });
                        });
                        ui.add(
                            egui::Label::new(
                                RichText::new(&item.value).small().color(theme::MUTED),
                            )
                            .wrap(),
                        );
                        if !item.tags.is_empty() {
                            ui.label(
                                RichText::new(format!("# {}", item.tags.replace(',', "  #")))
                                    .small()
                                    .color(theme::ACCENT),
                            );
                        }
                    });
                ui.add_space(6.0);
            }
        });
        if let Some(item) = edit {
            self.pending_focus = Some(FocusTarget::QuickTitle);
            self.quick_editor = Some(QuickEditor {
                kind,
                item,
                delete_armed: false,
            });
        }
        if let Some(item) = execute {
            self.execute_quick(kind, item, ui.ctx());
        }
    }

    pub(super) fn execute_quick(
        &mut self,
        kind: QuickAccessKind,
        item: QuickAccessItem,
        ctx: &egui::Context,
    ) {
        let result = match kind {
            QuickAccessKind::Shortcut => {
                // Python版と同じく、URLや `nav:` も含めて保存値をそのままコピーする。
                let value = item.value.trim();
                if value.is_empty() {
                    return;
                }
                ctx.copy_text(value.to_owned());
                Ok::<_, anyhow::Error>(())
            }
            QuickAccessKind::OpenFile => {
                let value = item.value.trim();
                if value.is_empty() {
                    return;
                }
                let target = std::path::Path::new(value);
                if !target.exists() {
                    Err(anyhow::anyhow!("ファイルが見つかりません: {value}"))
                } else {
                    open::that(target).map_err(anyhow::Error::from)
                }
            }
        };
        match result {
            Ok(()) => {
                if let Err(error) = self.storage.bump_quick_access(kind, &item.id) {
                    self.set_error(error);
                } else if kind == QuickAccessKind::Shortcut {
                    self.set_message("クリップボードへコピーしました");
                }
            }
            Err(error) => self.set_error(error),
        }
        self.refresh_quick(kind);
    }

    pub(super) fn quick_editor_window(&mut self, ctx: &egui::Context) {
        let focus_title = self.pending_focus == Some(FocusTarget::QuickTitle);
        if focus_title {
            self.pending_focus = None;
        }
        let Some(editor) = self.quick_editor.as_mut() else {
            return;
        };
        let is_new = editor.item.id.is_empty();
        let is_shortcut = editor.kind == QuickAccessKind::Shortcut;
        let mut open = true;
        let mut close_requested = false;
        let mut save = false;
        let mut delete = false;
        egui::Window::new(if is_shortcut {
            "ShortCut項目"
        } else {
            "OpenFile項目"
        })
        .open(&mut open)
        .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
        .collapsible(false)
        .resizable(false)
        .default_width(520.0)
        .min_width(340.0)
        .show(ctx, |ui| {
            ui.label("タイトル");
            let response = ui.add_sized(
                [ui.available_width(), 32.0],
                egui::TextEdit::singleline(&mut editor.item.title).hint_text("表示名"),
            );
            if focus_title {
                response.request_focus();
            }
            ui.label(if is_shortcut {
                "コマンド／テキスト／URL"
            } else {
                "ファイル／フォルダーパス"
            });
            ui.horizontal(|ui| {
                ui.add_sized(
                    [390.0, 28.0],
                    egui::TextEdit::singleline(&mut editor.item.value),
                );
                if !is_shortcut
                    && ui.button("選択").clicked()
                    && let Some(path) = rfd::FileDialog::new().pick_file()
                {
                    editor.item.value = path.display().to_string();
                }
            });
            ui.label("タグ（カンマ区切り）");
            ui.add_sized(
                [ui.available_width(), 32.0],
                egui::TextEdit::singleline(&mut editor.item.tags).hint_text("例: work, daily"),
            );
            ui.horizontal(|ui| {
                if ui.button("保存").clicked() {
                    save = true;
                }
                if ui.button("キャンセル").clicked() {
                    close_requested = true;
                }
                if !is_new {
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        if editor.delete_armed {
                            if ui
                                .button(RichText::new("削除を確定").color(theme::RED))
                                .clicked()
                            {
                                delete = true;
                            }
                            if ui.button("戻る").clicked() {
                                editor.delete_armed = false;
                            }
                        } else if ui.button(RichText::new("削除").color(theme::RED)).clicked() {
                            editor.delete_armed = true;
                        }
                    });
                }
            });
            if ui.input(|input| input.key_pressed(Key::Escape)) {
                close_requested = true;
            }
        });
        if save {
            let mut editor = self.quick_editor.clone().unwrap();
            if editor.item.title.trim().is_empty() || editor.item.value.trim().is_empty() {
                self.pending_focus = Some(FocusTarget::QuickTitle);
                self.set_message("タイトルと値を入力してください");
            } else {
                match self
                    .storage
                    .save_quick_access(editor.kind, &mut editor.item)
                {
                    Ok(()) => {
                        self.quick_editor = None;
                        self.refresh_quick(editor.kind);
                        self.set_message("項目を保存しました");
                    }
                    Err(error) => self.set_error(error),
                }
            }
        } else if delete {
            let editor = self.quick_editor.clone().unwrap();
            match self
                .storage
                .delete_quick_access(editor.kind, &editor.item.id)
            {
                Ok(()) => {
                    self.quick_editor = None;
                    self.refresh_quick(editor.kind);
                    self.set_message("項目を削除しました");
                }
                Err(error) => self.set_error(error),
            }
        } else if !open || close_requested {
            self.quick_editor = None;
        }
    }
}
