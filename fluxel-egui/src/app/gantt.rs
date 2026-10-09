//! Gantt project and term navigation, editing, and timeline rendering.

use super::*;

impl FluxelApp {
    pub(super) fn gantt_ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading("GANTT PLANNING");
            if ui.button("＋ Project").clicked() {
                self.pending_focus = Some(FocusTarget::GanttTitle);
                self.gantt_editor = Some(GanttEditor::Project(GanttProject::default(), false));
            }
            if ui.button("＋ Term").clicked() {
                self.new_gantt_term();
            }
            if ui.button("Today").clicked() {
                self.gantt_filter = None;
            }
            if ui
                .small_button("−")
                .on_hover_text("タイムラインを縮小")
                .clicked()
            {
                self.gantt_day_width = (self.gantt_day_width - 2.0).max(8.0);
            }
            if ui
                .small_button("+")
                .on_hover_text("タイムラインを拡大")
                .clicked()
            {
                self.gantt_day_width = (self.gantt_day_width + 2.0).min(48.0);
            }
            egui::ComboBox::from_id_salt("gantt-filter")
                .selected_text(
                    self.gantt_filter
                        .as_ref()
                        .and_then(|id| self.gantt_projects.iter().find(|p| &p.id == id))
                        .map(|p| p.title.as_str())
                        .unwrap_or("All projects"),
                )
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.gantt_filter, None, "All projects");
                    for project in &self.gantt_projects {
                        ui.selectable_value(
                            &mut self.gantt_filter,
                            Some(project.id.clone()),
                            &project.title,
                        );
                    }
                });
        });
        ui.label(
            RichText::new("クリックで選択・ダブルクリックで編集・バーを左右にドラッグして日付移動")
                .small()
                .color(theme::MUTED),
        );
        let zoom_delta = ui.input(|input| {
            if input.modifiers.command {
                input.smooth_scroll_delta.y
            } else {
                0.0
            }
        });
        if zoom_delta.abs() > f32::EPSILON {
            self.gantt_day_width =
                (self.gantt_day_width + zoom_delta.signum() * 2.0).clamp(8.0, 48.0);
        }
        ui.separator();
        let projects = self
            .gantt_projects
            .iter()
            .filter(|project| {
                self.gantt_filter
                    .as_ref()
                    .is_none_or(|id| &project.id == id)
            })
            .cloned()
            .collect::<Vec<_>>();
        let project_ids = projects
            .iter()
            .map(|project| project.id.clone())
            .collect::<Vec<_>>();
        let terms = self
            .gantt_terms
            .iter()
            .filter(|term| project_ids.contains(&term.project_id))
            .cloned()
            .collect::<Vec<_>>();
        if projects.is_empty() {
            egui::Frame::new()
                .fill(theme::PANEL)
                .stroke(Stroke::new(1.0, theme::BORDER))
                .corner_radius(8)
                .inner_margin(egui::Margin::same(18))
                .show(ui, |ui| {
                    ui.label(RichText::new("プロジェクトがありません").strong());
                    ui.label(
                        RichText::new("「＋ Project」から最初のプロジェクトを作成してください。")
                            .color(theme::MUTED),
                    );
                });
            return;
        }
        let action = gantt_canvas(
            ui,
            &projects,
            &terms,
            self.gantt_day_width,
            self.selected_gantt_project.as_deref(),
            self.selected_gantt_term.as_deref(),
        );
        if let Some(selection) = action.selection {
            match selection {
                GanttSelection::Project(id) => {
                    self.selected_gantt_project = Some(id);
                    self.selected_gantt_term = None;
                }
                GanttSelection::Term { id, project_id } => {
                    self.selected_gantt_project = Some(project_id);
                    self.selected_gantt_term = Some(id);
                }
            }
        }
        if let Some((term_id, days)) = action.moved_term {
            match self.storage.move_gantt_term_days(&term_id, days) {
                Ok(true) => self.refresh_gantt(),
                Ok(false) => {}
                Err(error) => self.set_error(error),
            }
        }
        if let Some(project) = action.edit_project {
            self.selected_gantt_project = Some(project.id.clone());
            self.selected_gantt_term = None;
            self.pending_focus = Some(FocusTarget::GanttTitle);
            self.gantt_editor = Some(GanttEditor::Project(project, false));
        }
        if let Some(term) = action.edit_term {
            self.selected_gantt_project = Some(term.project_id.clone());
            self.selected_gantt_term = Some(term.id.clone());
            self.pending_focus = Some(FocusTarget::GanttTitle);
            self.gantt_editor = Some(GanttEditor::Term(term, false));
        }
    }

    /// Selects the adjacent term in the same flattened order as the Python canvas.
    pub(super) fn navigate_gantt_term(&mut self, direction: isize) {
        let visible_project_ids = self
            .gantt_projects
            .iter()
            .filter(|project| {
                self.gantt_filter
                    .as_ref()
                    .is_none_or(|id| &project.id == id)
            })
            .map(|project| project.id.as_str())
            .collect::<Vec<_>>();
        let visible_terms = self
            .gantt_terms
            .iter()
            .filter(|term| visible_project_ids.contains(&term.project_id.as_str()))
            .collect::<Vec<_>>();
        if visible_terms.is_empty() {
            return;
        }
        let project_id = self
            .selected_gantt_term
            .as_ref()
            .and_then(|id| visible_terms.iter().find(|term| &term.id == id))
            .map(|term| term.project_id.as_str())
            .or(self.selected_gantt_project.as_deref());
        let siblings = visible_terms
            .iter()
            .copied()
            .filter(|term| Some(term.project_id.as_str()) == project_id)
            .collect::<Vec<_>>();
        let candidates = if siblings.is_empty() {
            visible_terms
        } else {
            siblings
        };
        let current = self
            .selected_gantt_term
            .as_ref()
            .and_then(|id| candidates.iter().position(|term| &term.id == id));
        let target = match current {
            Some(index) => {
                (index as isize + direction).clamp(0, candidates.len() as isize - 1) as usize
            }
            None if direction < 0 => candidates.len() - 1,
            None => 0,
        };
        let term = candidates[target];
        self.selected_gantt_project = Some(term.project_id.clone());
        self.selected_gantt_term = Some(term.id.clone());
    }

    /// Selects an adjacent project, preferring its first term when available.
    pub(super) fn navigate_gantt_project(&mut self, direction: isize) {
        if self.gantt_projects.is_empty() {
            return;
        }
        let current = self.selected_gantt_project.as_ref().and_then(|id| {
            self.gantt_projects
                .iter()
                .position(|project| &project.id == id)
        });
        let target = match current {
            Some(index) => (index as isize + direction)
                .clamp(0, self.gantt_projects.len() as isize - 1)
                as usize,
            None if direction < 0 => self.gantt_projects.len() - 1,
            None => 0,
        };
        let project_id = self.gantt_projects[target].id.clone();
        self.selected_gantt_term = self
            .gantt_terms
            .iter()
            .find(|term| term.project_id == project_id)
            .map(|term| term.id.clone());
        self.selected_gantt_project = Some(project_id);
    }

    /// Persists a one-row term reorder and restores selection after reload.
    pub(super) fn reorder_selected_gantt_term(&mut self, direction: isize) {
        let Some(id) = self.selected_gantt_term.clone() else {
            return;
        };
        match self.storage.reorder_gantt_term(&id, direction) {
            Ok(true) => self.refresh_gantt(),
            Ok(false) => {}
            Err(error) => self.set_error(error),
        }
    }

    /// Moves the selected term to the adjacent project, keeping all term content.
    pub(super) fn move_selected_gantt_to_project(&mut self, direction: isize) {
        let Some(term_id) = self.selected_gantt_term.clone() else {
            return;
        };
        let Some(term) = self.gantt_terms.iter().find(|term| term.id == term_id) else {
            return;
        };
        let Some(current) = self
            .gantt_projects
            .iter()
            .position(|project| project.id == term.project_id)
        else {
            return;
        };
        let target = current as isize + direction;
        if !(0..self.gantt_projects.len() as isize).contains(&target) {
            return;
        }
        let target_id = self.gantt_projects[target as usize].id.clone();
        match self
            .storage
            .move_gantt_term_to_project(&term_id, &target_id)
        {
            Ok(true) => {
                self.selected_gantt_project = Some(target_id);
                self.refresh_gantt();
            }
            Ok(false) => {}
            Err(error) => self.set_error(error),
        }
    }

    /// Opens the currently selected project or term for editing.
    pub(super) fn open_selected_gantt_item(&mut self) {
        self.pending_focus = Some(FocusTarget::GanttTitle);
        if let Some(id) = self.selected_gantt_term.as_ref()
            && let Some(term) = self.gantt_terms.iter().find(|term| &term.id == id)
        {
            self.gantt_editor = Some(GanttEditor::Term(term.clone(), false));
        } else if let Some(id) = self.selected_gantt_project.as_ref()
            && let Some(project) = self.gantt_projects.iter().find(|project| &project.id == id)
        {
            self.gantt_editor = Some(GanttEditor::Project(project.clone(), false));
        }
    }

    pub(super) fn new_gantt_term(&mut self) {
        let Some(project) = self.gantt_projects.first() else {
            self.set_message("先にProjectを作成してください");
            return;
        };
        let today = Local::now().date_naive();
        self.pending_focus = Some(FocusTarget::GanttTitle);
        self.gantt_editor = Some(GanttEditor::Term(
            GanttTerm {
                id: String::new(),
                project_id: project.id.clone(),
                title: String::new(),
                description: String::new(),
                start_date: today,
                end_date: today + Duration::days(6),
                color: "#2E7BD9".to_owned(),
                sort_order: 0,
            },
            false,
        ));
    }

    pub(super) fn gantt_editor_window(&mut self, ctx: &egui::Context) {
        let focus_title = self.pending_focus == Some(FocusTarget::GanttTitle);
        if focus_title {
            self.pending_focus = None;
        }
        let Some(editor) = self.gantt_editor.as_mut() else {
            return;
        };
        let mut open = true;
        let mut close_requested = false;
        let mut save = false;
        let mut delete = false;
        match editor {
            GanttEditor::Project(project, delete_armed) => {
                let is_new = project.id.is_empty();
                egui::Window::new(if is_new {
                    "New Project"
                } else {
                    "Edit Project"
                })
                .open(&mut open)
                .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
                .collapsible(false)
                .resizable(false)
                .default_width(480.0)
                .show(ctx, |ui| {
                    ui.label("プロジェクト名");
                    let response = ui.add_sized(
                        [ui.available_width(), 32.0],
                        egui::TextEdit::singleline(&mut project.title)
                            .hint_text("プロジェクト名を入力"),
                    );
                    if focus_title {
                        response.request_focus();
                    }
                    ui.label("説明");
                    ui.add_sized(
                        [ui.available_width(), 100.0],
                        egui::TextEdit::multiline(&mut project.description),
                    );
                    ui.checkbox(&mut project.is_completed, "完了済み");
                    editor_buttons(
                        ui,
                        is_new,
                        delete_armed,
                        &mut save,
                        &mut delete,
                        &mut close_requested,
                    );
                });
            }
            GanttEditor::Term(term, delete_armed) => {
                let is_new = term.id.is_empty();
                egui::Window::new(if is_new { "New Term" } else { "Edit Term" })
                    .open(&mut open)
                    .anchor(Align2::CENTER_CENTER, [0.0, 0.0])
                    .collapsible(false)
                    .resizable(false)
                    .default_width(500.0)
                    .show(ctx, |ui| {
                        ui.label("プロジェクト");
                        egui::ComboBox::from_id_salt("term-project")
                            .selected_text(
                                self.gantt_projects
                                    .iter()
                                    .find(|p| p.id == term.project_id)
                                    .map(|p| p.title.as_str())
                                    .unwrap_or("Project"),
                            )
                            .show_ui(ui, |ui| {
                                for project in &self.gantt_projects {
                                    ui.selectable_value(
                                        &mut term.project_id,
                                        project.id.clone(),
                                        &project.title,
                                    );
                                }
                            });
                        ui.label("期間名");
                        let response = ui.add_sized(
                            [ui.available_width(), 32.0],
                            egui::TextEdit::singleline(&mut term.title).hint_text("期間名を入力"),
                        );
                        if focus_title {
                            response.request_focus();
                        }
                        ui.label("説明");
                        ui.add_sized(
                            [ui.available_width(), 90.0],
                            egui::TextEdit::multiline(&mut term.description),
                        );
                        ui.horizontal(|ui| {
                            ui.label("開始日");
                            date_editor(ui, &mut term.start_date);
                        });
                        ui.horizontal(|ui| {
                            ui.label("終了日");
                            date_editor(ui, &mut term.end_date);
                        });
                        ui.horizontal(|ui| {
                            ui.label("色");
                            ui.text_edit_singleline(&mut term.color);
                        });
                        editor_buttons(
                            ui,
                            is_new,
                            delete_armed,
                            &mut save,
                            &mut delete,
                            &mut close_requested,
                        );
                    });
            }
        }
        if ctx.input(|input| input.key_pressed(Key::Escape)) {
            close_requested = true;
        }
        if save {
            let editor = self.gantt_editor.clone().unwrap();
            let result = match editor {
                GanttEditor::Project(mut project, _) => {
                    self.storage.save_gantt_project(&mut project)
                }
                GanttEditor::Term(mut term, _) => self.storage.save_gantt_term(&mut term),
            };
            match result {
                Ok(()) => {
                    self.gantt_editor = None;
                    self.refresh_gantt();
                    self.set_message("Ganttを保存しました");
                }
                Err(error) => self.set_error(error),
            }
        } else if delete {
            let editor = self.gantt_editor.clone().unwrap();
            let result = match editor {
                GanttEditor::Project(project, _) => self.storage.delete_gantt_project(&project.id),
                GanttEditor::Term(term, _) => self.storage.delete_gantt_term(&term.id),
            };
            match result {
                Ok(()) => {
                    self.gantt_editor = None;
                    self.refresh_gantt();
                    self.set_message("Gantt項目を削除しました");
                }
                Err(error) => self.set_error(error),
            }
        } else if !open || close_requested {
            self.gantt_editor = None;
        }
    }
}

enum GanttSelection {
    Project(String),
    Term { id: String, project_id: String },
}

#[derive(Default)]
struct GanttCanvasAction {
    selection: Option<GanttSelection>,
    edit_project: Option<GanttProject>,
    edit_term: Option<GanttTerm>,
    moved_term: Option<(String, i64)>,
}

fn gantt_canvas(
    ui: &mut egui::Ui,
    projects: &[GanttProject],
    terms: &[GanttTerm],
    day_width: f32,
    selected_project: Option<&str>,
    selected_term: Option<&str>,
) -> GanttCanvasAction {
    let mut action = GanttCanvasAction::default();
    let today = Local::now().date_naive();
    let min_date = terms
        .iter()
        .map(|term| term.start_date)
        .min()
        .unwrap_or(today - Duration::days(14))
        .min(today - Duration::days(14));
    let max_date = terms
        .iter()
        .map(|term| term.end_date)
        .max()
        .unwrap_or(today + Duration::days(60))
        .max(today + Duration::days(60));
    let left_width = 220.0;
    let total_days = (max_date - min_date).num_days().max(1) as f32 + 1.0;
    let canvas_width = left_width + total_days * day_width;
    ScrollArea::both().id_salt("gantt-canvas").show(ui, |ui| {
        ui.set_min_width(canvas_width);
        let mut row = 0usize;
        for project in projects {
            let project_terms = terms
                .iter()
                .filter(|term| term.project_id == project.id)
                .collect::<Vec<_>>();
            let (rect, response) =
                ui.allocate_exact_size(Vec2::new(canvas_width, 34.0), Sense::click());
            ui.painter().rect_filled(
                rect,
                0.0,
                if selected_project == Some(project.id.as_str()) && selected_term.is_none() {
                    Color32::from_rgb(40, 68, 91)
                } else if response.hovered() {
                    Color32::from_rgb(43, 49, 58)
                } else {
                    theme::PANEL_ALT
                },
            );
            ui.painter().text(
                rect.left_center() + Vec2::new(8.0, 0.0),
                Align2::LEFT_CENTER,
                format!(
                    "{}{}",
                    project.title,
                    if project.is_completed { "  ✓" } else { "" }
                ),
                FontId::proportional(13.0),
                theme::TEXT,
            );
            ui.painter().text(
                egui::pos2(rect.left() + left_width - 10.0, rect.center().y),
                Align2::RIGHT_CENTER,
                "編集",
                FontId::proportional(10.0),
                theme::MUTED,
            );
            let response = response.on_hover_cursor(egui::CursorIcon::PointingHand);
            if response.clicked() {
                action.selection = Some(GanttSelection::Project(project.id.clone()));
            }
            if response.double_clicked() {
                action.edit_project = Some(project.clone());
            }
            row += 1;
            for term in project_terms {
                let (rect, response) =
                    ui.allocate_exact_size(Vec2::new(canvas_width, 34.0), Sense::click_and_drag());
                if selected_term == Some(term.id.as_str()) {
                    ui.painter()
                        .rect_filled(rect, 0.0, Color32::from_rgb(40, 68, 91));
                } else if response.hovered() {
                    ui.painter()
                        .rect_filled(rect, 0.0, Color32::from_rgb(39, 45, 53));
                } else if row.is_multiple_of(2) {
                    ui.painter()
                        .rect_filled(rect, 0.0, Color32::from_rgb(25, 29, 34));
                }
                ui.painter().text(
                    rect.left_center() + Vec2::new(18.0, 0.0),
                    Align2::LEFT_CENTER,
                    &term.title,
                    FontId::proportional(12.0),
                    theme::TEXT,
                );
                ui.painter().text(
                    egui::pos2(rect.left() + left_width - 10.0, rect.center().y),
                    Align2::RIGHT_CENTER,
                    "編集",
                    FontId::proportional(10.0),
                    theme::MUTED,
                );
                let start = (term.start_date - min_date).num_days() as f32;
                let days = (term.end_date - term.start_date).num_days().max(0) as f32 + 1.0;
                let bar = egui::Rect::from_min_size(
                    egui::pos2(
                        rect.left() + left_width + start * day_width,
                        rect.top() + 7.0,
                    ),
                    Vec2::new((days * day_width).max(8.0), 20.0),
                );
                ui.painter()
                    .rect_filled(bar, 4.0, theme::color_from_hex(&term.color));
                ui.painter().text(
                    bar.left_center() + Vec2::new(6.0, 0.0),
                    Align2::LEFT_CENTER,
                    &term.title,
                    FontId::proportional(10.0),
                    Color32::WHITE,
                );
                let today_x =
                    rect.left() + left_width + (today - min_date).num_days() as f32 * day_width;
                ui.painter().line_segment(
                    [
                        egui::pos2(today_x, rect.top()),
                        egui::pos2(today_x, rect.bottom()),
                    ],
                    Stroke::new(1.0, theme::ORANGE),
                );
                let response = response.on_hover_cursor(egui::CursorIcon::PointingHand);
                if response.clicked() {
                    action.selection = Some(GanttSelection::Term {
                        id: term.id.clone(),
                        project_id: term.project_id.clone(),
                    });
                }
                if response.double_clicked() {
                    action.edit_term = Some(term.clone());
                }
                if response.drag_stopped()
                    && let Some(pointer) = response.interact_pointer_pos()
                {
                    let drag = response.drag_delta();
                    let origin = pointer - drag;
                    if bar.contains(origin) {
                        let days = (drag.x / day_width).round() as i64;
                        if days != 0 {
                            action.moved_term = Some((term.id.clone(), days));
                        }
                    }
                }
                row += 1;
            }
        }
    });
    action
}
