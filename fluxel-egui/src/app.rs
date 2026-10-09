use std::collections::HashMap;

use chrono::{Datelike, Duration, Local, NaiveDate};
use eframe::egui::{
    self, Align, Align2, Color32, FontId, Key, Layout, RichText, ScrollArea, Sense, Stroke,
    StrokeKind, Vec2,
};
use global_hotkey::{
    GlobalHotKeyEvent, GlobalHotKeyManager, HotKeyState,
    hotkey::{CMD_OR_CTRL, Code, HotKey, Modifiers},
};

mod dashboard;
mod gantt;
mod kanban;
mod quick_access;
mod search;
mod settings_ui;
mod widgets;

use kanban::*;
use widgets::*;

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
    manual_column_orders: HashMap<String, Vec<String>>,
    task_editor: Option<TaskEditor>,
    search_open: bool,
    search_query: String,
    search_include_archive: bool,
    search_status_filter: String,
    search_importance_filter: String,
    search_selected_index: usize,
    search_results: Vec<Task>,
    shortcut_query: String,
    shortcut_tag_query: String,
    shortcut_items: Vec<QuickAccessItem>,
    openfile_query: String,
    openfile_tag_query: String,
    openfile_items: Vec<QuickAccessItem>,
    quick_editor: Option<QuickEditor>,
    tag_input: String,
    dashboard_statuses: [bool; 5],
    dashboard: DashboardSnapshot,
    gantt_projects: Vec<GanttProject>,
    gantt_terms: Vec<GanttTerm>,
    gantt_filter: Option<String>,
    gantt_day_width: f32,
    gantt_editor: Option<GanttEditor>,
    selected_gantt_project: Option<String>,
    selected_gantt_term: Option<String>,
    pending_focus: Option<FocusTarget>,
    _hotkey_manager: Option<GlobalHotKeyManager>,
    global_hotkeys: Vec<(u32, Page)>,
    toast: Option<(String, f64)>,
}

impl FluxelApp {
    pub fn new(cc: &eframe::CreationContext<'_>, storage: Storage) -> Self {
        crate::fonts::configure(&cc.egui_ctx);
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
            manual_column_orders: HashMap::new(),
            task_editor: None,
            search_open: false,
            search_query: String::new(),
            search_include_archive: false,
            search_status_filter: String::new(),
            search_importance_filter: String::new(),
            search_selected_index: 0,
            search_results: Vec::new(),
            shortcut_query: String::new(),
            shortcut_tag_query: String::new(),
            shortcut_items: Vec::new(),
            openfile_query: String::new(),
            openfile_tag_query: String::new(),
            openfile_items: Vec::new(),
            quick_editor: None,
            tag_input: String::new(),
            dashboard_statuses: [true, true, true, false, false],
            dashboard: DashboardSnapshot::default(),
            gantt_projects: Vec::new(),
            gantt_terms: Vec::new(),
            gantt_filter: None,
            gantt_day_width: 18.0,
            gantt_editor: None,
            selected_gantt_project: None,
            selected_gantt_term: None,
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
            Ok(mut tasks) => {
                self.apply_manual_task_order(&mut tasks);
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
                if self
                    .selected_gantt_term
                    .as_ref()
                    .is_some_and(|id| !self.gantt_terms.iter().any(|term| &term.id == id))
                {
                    self.selected_gantt_term = None;
                }
                if self
                    .selected_gantt_project
                    .as_ref()
                    .is_some_and(|id| !self.gantt_projects.iter().any(|project| &project.id == id))
                {
                    self.selected_gantt_project = None;
                }
                if let Some(term_id) = self.selected_gantt_term.as_ref()
                    && let Some(term) = self.gantt_terms.iter().find(|term| &term.id == term_id)
                {
                    self.selected_gantt_project = Some(term.project_id.clone());
                } else if self.selected_gantt_project.is_none() {
                    if let Some(term) = self.gantt_terms.first() {
                        self.selected_gantt_project = Some(term.project_id.clone());
                        self.selected_gantt_term = Some(term.id.clone());
                    } else if let Some(project) = self.gantt_projects.first() {
                        self.selected_gantt_project = Some(project.id.clone());
                    }
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
            } else if ctx.input(|input| input.key_pressed(Key::S)) {
                self.run_sync();
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
            } else if primary && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.reorder_selected_task(-1);
            } else if primary && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.reorder_selected_task(1);
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
        if self.page == Page::Gantt && self.gantt_editor.is_none() && !self.search_open {
            if primary && alt && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.move_selected_gantt_to_project(-1);
            } else if primary && alt && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.move_selected_gantt_to_project(1);
            } else if primary && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.reorder_selected_gantt_term(-1);
            } else if primary && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.reorder_selected_gantt_term(1);
            } else if alt && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.navigate_gantt_project(-1);
            } else if alt && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.navigate_gantt_project(1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowUp)) {
                self.navigate_gantt_term(-1);
            } else if !primary && ctx.input(|input| input.key_pressed(Key::ArrowDown)) {
                self.navigate_gantt_term(1);
            } else if ctx.input(|input| input.key_pressed(Key::Enter)) {
                self.open_selected_gantt_item();
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
