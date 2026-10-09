//! Kanban rendering, selection, movement, and task editing.

use super::*;

impl FluxelApp {
    pub(super) fn kanban_ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            if ui.button("＋ 新しいタスク").clicked() {
                self.new_for_current_page();
            }
            if ui.button("更新").clicked() {
                self.refresh_tasks();
            }
            ui.label(
                RichText::new(format!(
                    "←/→ 列移動  ·  ↑/↓ カード選択  ·  {PRIMARY_KEY_LABEL}←/→ ステータス移動"
                ))
                .small()
                .color(theme::MUTED),
            );
        });
        ui.add_space(4.0);

        let mut hovered: Option<String> = None;
        let mut clicked: Option<(String, bool)> = None;
        ScrollArea::horizontal()
            .id_salt("kanban-horizontal")
            .show(ui, |ui| {
                ui.horizontal_top(|ui| {
                    for (status, label) in [
                        ("todo", "ToDo"),
                        ("doing", "Doing"),
                        ("wait", "Wait"),
                        ("finish", "Finish"),
                        ("archive", "Archive"),
                    ] {
                        let tasks = self
                            .tasks
                            .iter()
                            .filter(|task| task.status.eq_ignore_ascii_case(status))
                            .cloned()
                            .collect::<Vec<_>>();
                        let empty_column_focused = tasks.is_empty()
                            && self.selected_task.is_none()
                            && self.focused_status.eq_ignore_ascii_case(status);
                        ui.vertical(|ui| {
                            ui.set_width(272.0);
                            let header = egui::Frame::new()
                                .stroke(Stroke::new(
                                    if empty_column_focused { 1.0 } else { 0.0 },
                                    Color32::from_gray(117),
                                ))
                                .corner_radius(4)
                                .inner_margin(egui::Margin::symmetric(6, 4))
                                .show(ui, |ui| {
                                    ui.set_width(260.0);
                                    ui.horizontal(|ui| {
                                        ui.heading(label);
                                        ui.with_layout(
                                            Layout::right_to_left(Align::Center),
                                            |ui| {
                                                ui.label(
                                                    RichText::new(format!("{}件", tasks.len()))
                                                        .small()
                                                        .color(theme::MUTED),
                                                );
                                            },
                                        );
                                    });
                                });
                            if empty_column_focused {
                                header.response.scroll_to_me(Some(Align::Center));
                            }
                            ui.separator();
                            ScrollArea::vertical()
                                .id_salt(format!("kanban-{status}"))
                                .max_height(ui.available_height())
                                .show(ui, |ui| {
                                    for task in &tasks {
                                        let selected =
                                            self.selected_task.as_deref() == Some(task.id.as_str());
                                        let response = task_card(ui, task, selected);
                                        if selected {
                                            response.scroll_to_me(None);
                                        }
                                        if response.hovered() {
                                            hovered = Some(task.id.clone());
                                        }
                                        if response.clicked() {
                                            clicked = Some((task.id.clone(), selected));
                                        }
                                        ui.add_space(4.0);
                                    }
                                });
                        });
                        ui.add(egui::Separator::default().vertical().spacing(6.0));
                    }
                });
            });
        if hovered != self.hovered_task {
            self.hovered_task = hovered.clone();
            if let Some(id) = hovered {
                self.select_task(&id);
            }
        }
        if let Some((id, edit)) = clicked {
            self.select_task(&id);
            if edit {
                self.open_task(&id);
            }
        }
    }

    pub(super) fn move_task_selection(&mut self, delta: isize) {
        let status = self
            .selected_task
            .as_ref()
            .and_then(|id| self.tasks.iter().find(|task| &task.id == id))
            .map(|task| task.status.clone())
            .unwrap_or_else(|| self.focused_status.clone());
        let tasks = self
            .tasks
            .iter()
            .filter(|task| task.status.eq_ignore_ascii_case(&status))
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        if tasks.is_empty() {
            return;
        }
        let current = self
            .selected_task
            .as_ref()
            .and_then(|id| tasks.iter().position(|task_id| task_id == id));
        let next = match current {
            Some(index) => (index as isize + delta).clamp(0, tasks.len() as isize - 1) as usize,
            None if delta < 0 => tasks.len() - 1,
            None => 0,
        };
        self.column_vertical_index = next;
        self.selected_task = Some(tasks[next].clone());
    }

    /// Reapplies the Python version's session-only ordering to freshly loaded rows.
    pub(super) fn apply_manual_task_order(&self, tasks: &mut [Task]) {
        let original = tasks
            .iter()
            .enumerate()
            .map(|(index, task)| (task.id.clone(), index))
            .collect::<HashMap<_, _>>();
        tasks.sort_by_key(|task| {
            let status_index = STATUS_ORDER
                .iter()
                .position(|status| task.status.eq_ignore_ascii_case(status))
                .unwrap_or(STATUS_ORDER.len());
            let original_index = original.get(&task.id).copied().unwrap_or(usize::MAX);
            let manual_index = self
                .manual_column_orders
                .get(&task.status.to_lowercase())
                .and_then(|ids| ids.iter().position(|id| id == &task.id));
            (
                status_index,
                manual_index.unwrap_or(usize::MAX),
                original_index,
            )
        });
    }

    /// Reorders the selected card inside its column without changing SQLite data.
    pub(super) fn reorder_selected_task(&mut self, delta: isize) {
        let Some(selected_id) = self.selected_task.clone() else {
            return;
        };
        let Some(status) = self
            .tasks
            .iter()
            .find(|task| task.id == selected_id)
            .map(|task| task.status.to_lowercase())
        else {
            return;
        };
        let column_indices = self
            .tasks
            .iter()
            .enumerate()
            .filter_map(|(index, task)| task.status.eq_ignore_ascii_case(&status).then_some(index))
            .collect::<Vec<_>>();
        let Some(column_index) = column_indices
            .iter()
            .position(|index| self.tasks[*index].id == selected_id)
        else {
            return;
        };
        let target = column_index as isize + delta;
        if !(0..column_indices.len() as isize).contains(&target) {
            return;
        }
        self.tasks.swap(
            column_indices[column_index],
            column_indices[target as usize],
        );
        self.column_vertical_index = target as usize;
        self.manual_column_orders.insert(
            status,
            column_indices
                .iter()
                .map(|index| self.tasks[*index].id.clone())
                .collect(),
        );
    }

    pub(super) fn move_column_focus(&mut self, delta: isize) {
        let current_status = self
            .selected_task
            .as_ref()
            .and_then(|id| self.tasks.iter().find(|task| &task.id == id))
            .map(|task| task.status.as_str())
            .unwrap_or(self.focused_status.as_str());
        let current = STATUS_ORDER
            .iter()
            .position(|status| status.eq_ignore_ascii_case(current_status))
            .unwrap_or(0);
        let next = current as isize + delta;
        if !(0..STATUS_ORDER.len() as isize).contains(&next) {
            return;
        }
        let vertical_index = self.column_vertical_index;
        self.focus_column(STATUS_ORDER[next as usize], vertical_index);
    }

    pub(super) fn focus_column(&mut self, status: &str, preferred_index: usize) {
        self.focused_status = status.to_owned();
        self.column_vertical_index = preferred_index;
        let target = self
            .tasks
            .iter()
            .filter(|task| task.status.eq_ignore_ascii_case(status))
            .nth(preferred_index)
            .or_else(|| {
                self.tasks
                    .iter()
                    .rfind(|task| task.status.eq_ignore_ascii_case(status))
            })
            .map(|task| task.id.clone());
        if let Some(id) = target {
            self.select_task(&id);
        } else {
            self.selected_task = None;
        }
    }

    pub(super) fn select_task(&mut self, id: &str) {
        let Some(task) = self.tasks.iter().find(|task| task.id == id) else {
            return;
        };
        self.focused_status.clear();
        self.column_vertical_index = self
            .tasks
            .iter()
            .filter(|candidate| candidate.status.eq_ignore_ascii_case(&task.status))
            .position(|candidate| candidate.id == task.id)
            .unwrap_or(0);
        self.selected_task = Some(task.id.clone());
    }

    pub(super) fn move_selected_status(&mut self, delta: isize) {
        let Some(id) = self.selected_task.clone() else {
            return;
        };
        let Some(task) = self.tasks.iter().find(|task| task.id == id) else {
            return;
        };
        let Some(index) = STATUS_ORDER
            .iter()
            .position(|status| task.status.eq_ignore_ascii_case(status))
        else {
            return;
        };
        let next = index as isize + delta;
        if !(0..STATUS_ORDER.len() as isize).contains(&next) {
            return;
        }
        match self
            .storage
            .set_task_status(&id, STATUS_ORDER[next as usize])
        {
            Ok(()) => self.refresh_tasks(),
            Err(error) => self.set_error(error),
        }
    }

    pub(super) fn open_selected_task(&mut self) {
        if let Some(id) = self.selected_task.clone() {
            self.open_task(&id);
        }
    }

    pub(super) fn open_task(&mut self, id: &str) {
        match self.storage.get_task(id) {
            Ok(Some(task)) => {
                self.pending_focus = Some(FocusTarget::TaskName);
                self.task_editor = Some(TaskEditor {
                    task,
                    delete_armed: false,
                })
            }
            Ok(None) => self.set_message("タスクが見つかりません"),
            Err(error) => self.set_error(error),
        }
    }

    pub(super) fn task_editor_window(&mut self, ctx: &egui::Context) {
        let focus_name = self.pending_focus == Some(FocusTarget::TaskName);
        if focus_name {
            self.pending_focus = None;
        }
        let Some(editor) = self.task_editor.as_mut() else {
            return;
        };
        let is_new = editor.task.id.is_empty();
        let mut open = true;
        let mut close_requested = false;
        let mut save = false;
        let mut delete = false;
        egui::Window::new(if is_new {
            "新しいタスク"
        } else {
            "タスクの編集"
        })
        .open(&mut open)
        .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
        .collapsible(false)
        .resizable(false)
        .default_width(520.0)
        .min_width(340.0)
        .show(ctx, |ui| {
            ui.spacing_mut().text_edit_width = (ui.available_width() - 116.0).max(190.0);
            egui::Grid::new("task-form-grid")
                .num_columns(2)
                .spacing([14.0, 10.0])
                .show(ui, |ui| {
                    ui.label("タスク名:");
                    let response = ui.add(
                        egui::TextEdit::singleline(&mut editor.task.name)
                            .hint_text("タスク名を入力"),
                    );
                    if focus_name {
                        response.request_focus();
                    }
                    ui.end_row();
                    ui.label("完了日付:");
                    ui.text_edit_singleline(&mut editor.task.end_date);
                    ui.end_row();
                    ui.label("重要度:");
                    egui::ComboBox::from_id_salt("task-importance")
                        .selected_text(&editor.task.importance)
                        .show_ui(ui, |ui| {
                            for value in ["高", "中", "低"] {
                                ui.selectable_value(
                                    &mut editor.task.importance,
                                    value.to_owned(),
                                    value,
                                );
                            }
                        });
                    ui.end_row();
                    if !is_new {
                        ui.label("ステータス:");
                        egui::ComboBox::from_id_salt("task-status")
                            .selected_text(status_label(&editor.task.status))
                            .show_ui(ui, |ui| {
                                for (status, label) in [
                                    ("todo", "ToDo"),
                                    ("doing", "Doing"),
                                    ("wait", "Wait"),
                                    ("finish", "Finish"),
                                    ("archive", "Archive"),
                                ] {
                                    ui.selectable_value(
                                        &mut editor.task.status,
                                        status.to_owned(),
                                        label,
                                    );
                                }
                            });
                        ui.end_row();
                    }
                });
            ui.add_space(4.0);
            ui.label("タスク説明:");
            ui.add_sized(
                [ui.available_width(), 150.0],
                egui::TextEdit::multiline(&mut editor.task.description)
                    .hint_text("URLやファイルパスを含む説明を入力"),
            );
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                if ui
                    .button(format!("保存  {PRIMARY_KEY_LABEL}Enter"))
                    .clicked()
                    || (ui.input(|input| input.modifiers.command && input.key_pressed(Key::Enter)))
                {
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
            let mut task = self.task_editor.as_ref().unwrap().task.clone();
            if task.name.trim().is_empty() {
                self.pending_focus = Some(FocusTarget::TaskName);
                self.set_message("タスク名を入力してください");
            } else {
                match self.storage.save_task(&mut task) {
                    Ok(()) => {
                        self.selected_task = Some(task.id);
                        self.task_editor = None;
                        self.refresh_tasks();
                        self.refresh_dashboard();
                        self.set_message("タスクを保存しました");
                    }
                    Err(error) => self.set_error(error),
                }
            }
        } else if delete {
            let id = self.task_editor.as_ref().unwrap().task.id.clone();
            match self.storage.delete_task(&id) {
                Ok(()) => {
                    self.task_editor = None;
                    self.refresh_tasks();
                    self.refresh_dashboard();
                    self.set_message("タスクを削除しました");
                }
                Err(error) => self.set_error(error),
            }
        } else if !open || close_requested {
            self.task_editor = None;
        }
    }
}

pub(super) fn task_card(ui: &mut egui::Ui, task: &Task, selected: bool) -> egui::Response {
    let width = ui.available_width().max(240.0);
    let (rect, response) = ui.allocate_exact_size(Vec2::new(width, 76.0), Sense::click());
    if ui.is_rect_visible(rect) {
        let painter = ui.painter();
        painter.rect(
            rect,
            5.0,
            Color32::TRANSPARENT,
            Stroke::new(if selected { 1.0 } else { 0.0 }, Color32::from_gray(117)),
            StrokeKind::Inside,
        );
        let color_rect = egui::Rect::from_min_max(
            rect.min + Vec2::new(2.0, 3.0),
            egui::pos2(rect.min.x + 8.0, rect.max.y - 3.0),
        );
        painter.rect_filled(color_rect, 1.0, theme::importance_color(&task.importance));
        let x = rect.min.x + 16.0;
        painter.text(
            egui::pos2(x, rect.min.y + 22.0),
            Align2::LEFT_CENTER,
            if task.name.is_empty() {
                "(no name)"
            } else {
                &task.name
            },
            FontId::proportional(14.0),
            theme::TEXT,
        );
        let due = due_label(&task.end_date);
        let due_color = due_color(&task.end_date);
        painter.text(
            egui::pos2(rect.max.x - 8.0, rect.min.y + 22.0),
            Align2::RIGHT_CENTER,
            due,
            FontId::proportional(11.0),
            due_color,
        );
        painter.text(
            egui::pos2(x, rect.min.y + 51.0),
            Align2::LEFT_CENTER,
            preview(&task.description, 58),
            FontId::proportional(11.0),
            theme::MUTED,
        );
        if selected {
            painter.rect_filled(
                egui::Rect::from_min_max(
                    egui::pos2(rect.max.x - 3.0, rect.min.y + 3.0),
                    egui::pos2(rect.max.x, rect.max.y - 3.0),
                ),
                0.0,
                Color32::from_gray(117),
            );
        }
    }
    response.on_hover_text(format!(
        "{}\n{}",
        task.name,
        strip_storage_markers(&task.description)
    ))
}

pub(super) fn status_label(status: &str) -> &'static str {
    match status.trim().to_lowercase().as_str() {
        "todo" => "ToDo",
        "doing" => "Doing",
        "wait" => "Wait",
        "finish" => "Finish",
        "archive" => "Archive",
        _ => "Unknown",
    }
}

pub(super) fn due_label(value: &str) -> String {
    let Ok(date) = NaiveDate::parse_from_str(value.get(..10).unwrap_or(""), "%Y-%m-%d") else {
        return String::new();
    };
    let today = Local::now().date_naive();
    if date == today {
        "今日".to_owned()
    } else {
        format!("{:02}/{:02}", date.month(), date.day())
    }
}

pub(super) fn due_color(value: &str) -> Color32 {
    let Ok(date) = NaiveDate::parse_from_str(value.get(..10).unwrap_or(""), "%Y-%m-%d") else {
        return theme::MUTED;
    };
    let today = Local::now().date_naive();
    if date < today {
        theme::RED
    } else if date == today {
        theme::ORANGE
    } else {
        theme::MUTED
    }
}

pub(super) fn preview(value: &str, max_chars: usize) -> String {
    let plain = strip_storage_markers(value);
    let one_line = plain.split_whitespace().collect::<Vec<_>>().join(" ");
    if one_line.chars().count() <= max_chars {
        one_line
    } else {
        format!(
            "{}…",
            one_line
                .chars()
                .take(max_chars.saturating_sub(1))
                .collect::<String>()
        )
    }
}
