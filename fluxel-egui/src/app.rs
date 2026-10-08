use chrono::{Datelike, Duration, Local, NaiveDate};
use eframe::egui::{
    self, Align, Align2, Color32, FontId, Key, Layout, RichText, ScrollArea, Sense, Stroke,
    StrokeKind, Vec2,
};
use global_hotkey::{
    GlobalHotKeyEvent, GlobalHotKeyManager, HotKeyState,
    hotkey::{CMD_OR_CTRL, Code, HotKey, Modifiers},
};

use fluxel_egui::{
    models::{
        DashboardSnapshot, GanttProject, GanttTerm, Page, QuickAccessItem, QuickAccessKind,
        STATUS_ORDER, Task,
    },
    settings::AppSettings,
    storage::{Storage, strip_storage_markers},
    theme,
};

#[derive(Clone)]
struct TaskEditor {
    task: Task,
    delete_armed: bool,
}

#[derive(Clone)]
struct QuickEditor {
    kind: QuickAccessKind,
    item: QuickAccessItem,
    delete_armed: bool,
}

#[derive(Clone)]
enum GanttEditor {
    Project(GanttProject, bool),
    Term(GanttTerm, bool),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FocusTarget {
    TaskName,
    QuickTitle,
    QuickSearch,
    GanttTitle,
    SearchQuery,
}

#[cfg(target_os = "macos")]
const PRIMARY_KEY_LABEL: &str = "⌘";
#[cfg(not(target_os = "macos"))]
const PRIMARY_KEY_LABEL: &str = "Ctrl+";

pub struct FluxelApp {
    storage: Storage,
    settings: AppSettings,
    page: Page,
    tasks: Vec<Task>,
    selected_task: Option<String>,
    focused_status: String,
    column_vertical_index: usize,
    hovered_task: Option<String>,
    task_editor: Option<TaskEditor>,
    search_open: bool,
    search_query: String,
    search_include_archive: bool,
    search_results: Vec<Task>,
    shortcut_query: String,
    shortcut_tag_query: String,
    shortcut_items: Vec<QuickAccessItem>,
    openfile_query: String,
    openfile_tag_query: String,
    openfile_items: Vec<QuickAccessItem>,
    quick_editor: Option<QuickEditor>,
    dashboard_statuses: [bool; 5],
    dashboard: DashboardSnapshot,
    gantt_projects: Vec<GanttProject>,
    gantt_terms: Vec<GanttTerm>,
    gantt_filter: Option<String>,
    gantt_editor: Option<GanttEditor>,
    pending_focus: Option<FocusTarget>,
    _hotkey_manager: Option<GlobalHotKeyManager>,
    global_hotkeys: Vec<(u32, Page)>,
    toast: Option<(String, f64)>,
}

impl FluxelApp {
    pub fn new(cc: &eframe::CreationContext<'_>, storage: Storage) -> Self {
        egui_system_fonts::add_auto(&cc.egui_ctx, egui_system_fonts::FontStyle::Sans);
        theme::apply(&cc.egui_ctx);
        let settings = AppSettings::load(&storage.paths.settings_file);
        let (hotkey_manager, global_hotkeys) = register_global_hotkeys();
        let mut app = Self {
            storage,
            settings,
            page: Page::Kanban,
            tasks: Vec::new(),
            selected_task: None,
            focused_status: String::new(),
            column_vertical_index: 0,
            hovered_task: None,
            task_editor: None,
            search_open: false,
            search_query: String::new(),
            search_include_archive: false,
            search_results: Vec::new(),
            shortcut_query: String::new(),
            shortcut_tag_query: String::new(),
            shortcut_items: Vec::new(),
            openfile_query: String::new(),
            openfile_tag_query: String::new(),
            openfile_items: Vec::new(),
            quick_editor: None,
            dashboard_statuses: [true, true, true, false, false],
            dashboard: DashboardSnapshot::default(),
            gantt_projects: Vec::new(),
            gantt_terms: Vec::new(),
            gantt_filter: None,
            gantt_editor: None,
            pending_focus: None,
            _hotkey_manager: hotkey_manager,
            global_hotkeys,
            toast: None,
        };
        app.refresh_all();
        app
    }

    fn refresh_all(&mut self) {
        self.refresh_tasks();
        self.refresh_quick(QuickAccessKind::Shortcut);
        self.refresh_quick(QuickAccessKind::OpenFile);
        self.refresh_dashboard();
        self.refresh_gantt();
    }

    fn refresh_tasks(&mut self) {
        match self.storage.list_tasks(self.settings.archive_after_days) {
            Ok(tasks) => {
                self.tasks = tasks;
                if self
                    .selected_task
                    .as_ref()
                    .is_some_and(|id| !self.tasks.iter().any(|task| &task.id == id))
                {
                    self.selected_task = None;
                }
                if let Some(id) = self.selected_task.clone() {
                    self.select_task(&id);
                } else if self.focused_status.is_empty() {
                    if let Some(task) = self.tasks.first() {
                        let id = task.id.clone();
                        self.select_task(&id);
                    } else {
                        self.focused_status = STATUS_ORDER[0].to_owned();
                    }
                }
            }
            Err(error) => self.set_error(error),
        }
    }

    fn refresh_quick(&mut self, kind: QuickAccessKind) {
        let (query, tags) = match kind {
            QuickAccessKind::Shortcut => (&self.shortcut_query, &self.shortcut_tag_query),
            QuickAccessKind::OpenFile => (&self.openfile_query, &self.openfile_tag_query),
        };
        match self.storage.quick_access_items(kind, query, tags) {
            Ok(items) => match kind {
                QuickAccessKind::Shortcut => self.shortcut_items = items,
                QuickAccessKind::OpenFile => self.openfile_items = items,
            },
            Err(error) => self.set_error(error),
        }
    }

    fn refresh_dashboard(&mut self) {
        let statuses = STATUS_ORDER
            .iter()
            .zip(self.dashboard_statuses)
            .filter_map(|(status, enabled)| enabled.then_some(*status))
            .collect::<Vec<_>>();
        match self.storage.dashboard(&statuses) {
            Ok(snapshot) => self.dashboard = snapshot,
            Err(error) => self.set_error(error),
        }
    }

    fn refresh_gantt(&mut self) {
        match (
            self.storage.gantt_projects(true),
            self.storage.gantt_terms(),
        ) {
            (Ok(projects), Ok(terms)) => {
                self.gantt_projects = projects;
                self.gantt_terms = terms;
                if self
                    .gantt_filter
                    .as_ref()
                    .is_some_and(|id| !self.gantt_projects.iter().any(|project| &project.id == id))
                {
                    self.gantt_filter = None;
                }
            }
            (Err(error), _) | (_, Err(error)) => self.set_error(error),
        }
    }

    fn set_error(&mut self, error: impl std::fmt::Display) {
        self.toast = Some((format!("エラー: {error}"), 6.0));
    }

    fn set_message(&mut self, message: impl Into<String>) {
        self.toast = Some((message.into(), 3.0));
    }

    fn select_page(&mut self, page: Page) {
        self.page = page;
        match page {
            Page::Kanban => self.refresh_tasks(),
            Page::Dashboard => self.refresh_dashboard(),
            Page::Shortcut => {
                self.refresh_quick(QuickAccessKind::Shortcut);
                self.pending_focus = Some(FocusTarget::QuickSearch);
            }
            Page::OpenFile => {
                self.refresh_quick(QuickAccessKind::OpenFile);
                self.pending_focus = Some(FocusTarget::QuickSearch);
            }
            Page::Gantt => self.refresh_gantt(),
            Page::Settings => {}
        }
    }

    fn open_search(&mut self) {
        self.search_open = true;
        self.pending_focus = Some(FocusTarget::SearchQuery);
        self.refresh_search();
    }

    fn keyboard_shortcuts(&mut self, ctx: &egui::Context) {
        let (primary, shift, alt) = ctx.input(|input| {
            (
                input.modifiers.command,
                input.modifiers.shift,
                input.modifiers.alt,
            )
        });
        if primary && !shift && !alt {
            if ctx.input(|input| input.key_pressed(Key::K)) {
                self.select_page(Page::Kanban);
            } else if ctx.input(|input| input.key_pressed(Key::P)) {
                self.select_page(Page::Shortcut);
            } else if ctx.input(|input| input.key_pressed(Key::O)) {
                self.select_page(Page::OpenFile);
            } else if ctx.input(|input| input.key_pressed(Key::F)) {
                self.open_search();
            } else if ctx.input(|input| input.key_pressed(Key::N)) {
                self.new_for_current_page();
            }
        }
        if matches!(self.page, Page::Shortcut | Page::OpenFile)
            && self.task_editor.is_none()
            && self.quick_editor.is_none()
            && self.gantt_editor.is_none()
            && !self.search_open
            && !ctx.egui_wants_keyboard_input()
            && ctx.input_mut(|input| input.consume_key(egui::Modifiers::NONE, Key::Slash))
        {
            self.pending_focus = Some(FocusTarget::QuickSearch);
        }
        if self.page == Page::Kanban && self.task_editor.is_none() && !self.search_open {
            if primary && ctx.input(|input| input.key_pressed(Key::ArrowLeft)) {
                self.move_selected_status(-1);
            } else if primary && ctx.input(|input| input.key_pressed(Key::ArrowRight)) {
                self.move_selected_status(1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowLeft)) {
                self.move_column_focus(-1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowRight)) {
                self.move_column_focus(1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.move_task_selection(-1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.move_task_selection(1);
            } else if ctx.input(|input| input.key_pressed(Key::Enter)) {
                self.open_selected_task();
            }
        }
    }

    fn process_global_hotkeys(&mut self, ctx: &egui::Context) {
        while let Ok(event) = GlobalHotKeyEvent::receiver().try_recv() {
            if event.state != HotKeyState::Pressed {
                continue;
            }
            let Some((_, page)) = self.global_hotkeys.iter().find(|(id, _)| *id == event.id) else {
                continue;
            };
            let page = *page;
            self.select_page(page);
            ctx.send_viewport_cmd(egui::ViewportCommand::Visible(true));
            ctx.send_viewport_cmd(egui::ViewportCommand::Minimized(false));
            ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
        }
    }

    fn new_for_current_page(&mut self) {
        match self.page {
            Page::Kanban => {
                self.pending_focus = Some(FocusTarget::TaskName);
                self.task_editor = Some(TaskEditor {
                    task: Task {
                        importance: "低".to_owned(),
                        end_date: Local::now().date_naive().to_string(),
                        status: "todo".to_owned(),
                        ..Task::default()
                    },
                    delete_armed: false,
                })
            }
            Page::Shortcut => {
                self.pending_focus = Some(FocusTarget::QuickTitle);
                self.quick_editor = Some(QuickEditor {
                    kind: QuickAccessKind::Shortcut,
                    item: QuickAccessItem::default(),
                    delete_armed: false,
                })
            }
            Page::OpenFile => {
                self.pending_focus = Some(FocusTarget::QuickTitle);
                self.quick_editor = Some(QuickEditor {
                    kind: QuickAccessKind::OpenFile,
                    item: QuickAccessItem::default(),
                    delete_armed: false,
                })
            }
            Page::Gantt => self.new_gantt_term(),
            _ => {}
        }
    }

    fn header(&mut self, ui: &mut egui::Ui) {
        egui::Panel::top("top_navigation")
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(37, 37, 37))
                    .stroke(Stroke::new(1.0, theme::BORDER))
                    .inner_margin(egui::Margin::symmetric(12, 10)),
            )
            .show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    for (page, label) in Page::ALL {
                        let active = self.page == page;
                        let text = RichText::new(label).color(if active {
                            Color32::WHITE
                        } else {
                            theme::TEXT
                        });
                        let response =
                            ui.add(egui::Button::new(text).frame(false).selected(active));
                        if response.clicked() {
                            self.select_page(page);
                        }
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        if ui.button(format!("検索  {PRIMARY_KEY_LABEL}F")).clicked() {
                            self.open_search();
                        }
                    });
                });
            });
    }

    fn main_content(&mut self, ui: &mut egui::Ui) {
        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(theme::BG)
                    .inner_margin(egui::Margin::same(16)),
            )
            .show(ui, |ui| match self.page {
                Page::Kanban => self.kanban_ui(ui),
                Page::Dashboard => self.dashboard_ui(ui),
                Page::Shortcut => self.quick_access_ui(ui, QuickAccessKind::Shortcut),
                Page::OpenFile => self.quick_access_ui(ui, QuickAccessKind::OpenFile),
                Page::Gantt => self.gantt_ui(ui),
                Page::Settings => self.settings_ui(ui),
            });
    }

    fn kanban_ui(&mut self, ui: &mut egui::Ui) {
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

    fn move_task_selection(&mut self, delta: isize) {
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

    fn move_column_focus(&mut self, delta: isize) {
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

    fn focus_column(&mut self, status: &str, preferred_index: usize) {
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

    fn select_task(&mut self, id: &str) {
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

    fn move_selected_status(&mut self, delta: isize) {
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

    fn open_selected_task(&mut self) {
        if let Some(id) = self.selected_task.clone() {
            self.open_task(&id);
        }
    }

    fn open_task(&mut self, id: &str) {
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

    fn task_editor_window(&mut self, ctx: &egui::Context) {
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

    fn refresh_search(&mut self) {
        match self
            .storage
            .search_tasks(&self.search_query, self.search_include_archive)
        {
            Ok(tasks) => self.search_results = tasks,
            Err(error) => self.set_error(error),
        }
    }

    fn search_window(&mut self, ctx: &egui::Context) {
        if !self.search_open {
            return;
        }
        let mut open = self.search_open;
        let mut selected = None;
        let mut changed = false;
        let escape_pressed = ctx.input(|input| input.key_pressed(Key::Escape));
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
                            .hint_text("タイトル・本文・重要度を検索"),
                    );
                    if focus_query {
                        response.request_focus();
                    }
                    changed |= response.changed();
                    changed |= ui
                        .checkbox(&mut self.search_include_archive, "Archiveを含む")
                        .changed();
                });
                ui.separator();
                ScrollArea::vertical().show(ui, |ui| {
                    for task in &self.search_results {
                        let text = format!(
                            "{}  ·  {}  ·  {}",
                            task.name,
                            status_label(&task.status),
                            due_label(&task.end_date)
                        );
                        if ui.selectable_label(false, text).double_clicked() {
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

    fn quick_access_ui(&mut self, ui: &mut egui::Ui, kind: QuickAccessKind) {
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

    fn execute_quick(&mut self, kind: QuickAccessKind, item: QuickAccessItem, ctx: &egui::Context) {
        let result = match kind {
            QuickAccessKind::Shortcut => {
                if let Some(nav) = item.value.strip_prefix("nav:") {
                    let page = match nav.trim().to_lowercase().as_str() {
                        "kanban" => Some(Page::Kanban),
                        "dashboard" => Some(Page::Dashboard),
                        "shortcut" => Some(Page::Shortcut),
                        "openfile" => Some(Page::OpenFile),
                        "gantt" => Some(Page::Gantt),
                        "settings" | "setting" => Some(Page::Settings),
                        _ => None,
                    };
                    if let Some(page) = page {
                        self.select_page(page);
                    }
                    Ok(())
                } else if item.value.starts_with("http://") || item.value.starts_with("https://") {
                    open::that(&item.value).map_err(anyhow::Error::from)
                } else {
                    ctx.copy_text(item.value.clone());
                    self.set_message("クリップボードへコピーしました");
                    Ok(())
                }
            }
            QuickAccessKind::OpenFile => open::that(&item.value).map_err(anyhow::Error::from),
        };
        if let Err(error) = result {
            self.set_error(error);
        }
        if let Err(error) = self.storage.bump_quick_access(kind, &item.id) {
            self.set_error(error);
        }
        self.refresh_quick(kind);
    }

    fn quick_editor_window(&mut self, ctx: &egui::Context) {
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

    fn dashboard_ui(&mut self, ui: &mut egui::Ui) {
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

    fn gantt_ui(&mut self, ui: &mut egui::Ui) {
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
            RichText::new("行をクリックすると編集できます")
                .small()
                .color(theme::MUTED),
        );
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
        let mut edit_project = None;
        let mut edit_term = None;
        gantt_canvas(ui, &projects, &terms, &mut edit_project, &mut edit_term);
        if let Some(project) = edit_project {
            self.pending_focus = Some(FocusTarget::GanttTitle);
            self.gantt_editor = Some(GanttEditor::Project(project, false));
        }
        if let Some(term) = edit_term {
            self.pending_focus = Some(FocusTarget::GanttTitle);
            self.gantt_editor = Some(GanttEditor::Term(term, false));
        }
    }

    fn new_gantt_term(&mut self) {
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

    fn gantt_editor_window(&mut self, ctx: &egui::Context) {
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

    fn settings_ui(&mut self, ui: &mut egui::Ui) {
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
        settings_card(ui, "APPLICATION", |ui| {
            ui.label("Fluxel egui 0.1.0");
            ui.label(RichText::new("既存SQLite形式と互換のRust/egui版").color(theme::MUTED));
        });
    }

    fn toast_ui(&mut self, ctx: &egui::Context) {
        let Some((message, remaining)) = self.toast.as_mut() else {
            return;
        };
        let dt = ctx.input(|input| input.stable_dt).min(0.1) as f64;
        *remaining -= dt;
        egui::Area::new("toast".into())
            .anchor(Align2::CENTER_BOTTOM, [0.0, -24.0])
            .show(ctx, |ui| {
                egui::Frame::new()
                    .fill(Color32::from_rgba_premultiplied(25, 25, 25, 240))
                    .stroke(Stroke::new(1.5, theme::ACCENT))
                    .corner_radius(10)
                    .inner_margin(egui::Margin::symmetric(20, 12))
                    .show(ui, |ui| {
                        ui.label(
                            RichText::new(message.as_str())
                                .strong()
                                .color(Color32::WHITE),
                        );
                    });
            });
        if *remaining <= 0.0 {
            self.toast = None;
        } else {
            ctx.request_repaint();
        }
    }
}

impl eframe::App for FluxelApp {
    fn logic(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.process_global_hotkeys(ctx);
        ctx.request_repaint_after(std::time::Duration::from_millis(100));
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.keyboard_shortcuts(&ctx);
        self.header(ui);
        self.main_content(ui);
        self.task_editor_window(&ctx);
        self.quick_editor_window(&ctx);
        self.gantt_editor_window(&ctx);
        self.search_window(&ctx);
        self.toast_ui(&ctx);
    }
}

fn register_global_hotkeys() -> (Option<GlobalHotKeyManager>, Vec<(u32, Page)>) {
    let Ok(manager) = GlobalHotKeyManager::new() else {
        log::warn!("global hotkeys are unavailable on this desktop session");
        return (None, Vec::new());
    };
    let modifiers = CMD_OR_CTRL | Modifiers::ALT | Modifiers::SHIFT;
    let mut registered = Vec::new();
    for (code, page) in [
        (Code::KeyK, Page::Kanban),
        (Code::KeyP, Page::Shortcut),
        (Code::KeyO, Page::OpenFile),
    ] {
        let hotkey = HotKey::new(Some(modifiers), code);
        let id = hotkey.id();
        match manager.register(hotkey) {
            Ok(()) => registered.push((id, page)),
            Err(error) => log::warn!("failed to register a Fluxel hotkey: {error}"),
        }
    }
    (Some(manager), registered)
}

fn task_card(ui: &mut egui::Ui, task: &Task, selected: bool) -> egui::Response {
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

fn status_label(status: &str) -> &'static str {
    match status.trim().to_lowercase().as_str() {
        "todo" => "ToDo",
        "doing" => "Doing",
        "wait" => "Wait",
        "finish" => "Finish",
        "archive" => "Archive",
        _ => "Unknown",
    }
}

fn due_label(value: &str) -> String {
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

fn due_color(value: &str) -> Color32 {
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

fn preview(value: &str, max_chars: usize) -> String {
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

fn metric_card(ui: &mut egui::Ui, label: &str, value: usize, color: Color32) {
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

fn donut_chart(ui: &mut egui::Ui, snapshot: &DashboardSnapshot) {
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

fn deadline_chart(ui: &mut egui::Ui, snapshot: &DashboardSnapshot) {
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

fn gantt_canvas(
    ui: &mut egui::Ui,
    projects: &[GanttProject],
    terms: &[GanttTerm],
    edit_project: &mut Option<GanttProject>,
    edit_term: &mut Option<GanttTerm>,
) {
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
    let day_width = 18.0;
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
                if response.hovered() {
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
            if response
                .on_hover_cursor(egui::CursorIcon::PointingHand)
                .clicked()
            {
                *edit_project = Some(project.clone());
            }
            row += 1;
            for term in project_terms {
                let (rect, response) =
                    ui.allocate_exact_size(Vec2::new(canvas_width, 34.0), Sense::click());
                if response.hovered() {
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
                if response
                    .on_hover_cursor(egui::CursorIcon::PointingHand)
                    .clicked()
                {
                    *edit_term = Some(term.clone());
                }
                row += 1;
            }
        }
    });
}

fn editor_buttons(
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

fn date_editor(ui: &mut egui::Ui, date: &mut NaiveDate) {
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

fn settings_card(ui: &mut egui::Ui, title: &str, content: impl FnOnce(&mut egui::Ui)) {
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

fn path_row(ui: &mut egui::Ui, label: &str, path: &std::path::Path) {
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
