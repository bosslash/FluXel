use chrono::NaiveDate;

pub const STATUS_ORDER: [&str; 5] = ["todo", "doing", "wait", "finish", "archive"];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Page {
    Kanban,
    Dashboard,
    Shortcut,
    OpenFile,
    Gantt,
    Settings,
}

impl Page {
    pub const ALL: [(Self, &'static str); 6] = [
        (Self::Kanban, "Kanban"),
        (Self::Dashboard, "Dashboard"),
        (Self::Shortcut, "ShortCut"),
        (Self::OpenFile, "OpenFile"),
        (Self::Gantt, "Gantt"),
        (Self::Settings, "Setting"),
    ];
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct Task {
    pub id: String,
    pub name: String,
    pub description: String,
    pub importance: String,
    pub created_at: String,
    pub update_at: String,
    pub end_date: String,
    pub status: String,
    pub stored_urls: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuickAccessKind {
    Shortcut,
    OpenFile,
}

impl QuickAccessKind {
    pub fn tables(self) -> (&'static str, &'static str) {
        match self {
            Self::Shortcut => ("shortcut_phrases", "shortcut_phrase_tags"),
            Self::OpenFile => ("openfile_entries", "openfile_entry_tags"),
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct QuickAccessItem {
    pub id: String,
    pub title: String,
    pub value: String,
    pub tags: String,
    pub use_count: i64,
    pub last_used_date: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct GanttProject {
    pub id: String,
    pub title: String,
    pub description: String,
    pub is_completed: bool,
    pub sort_order: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GanttTerm {
    pub id: String,
    pub project_id: String,
    pub title: String,
    pub description: String,
    pub start_date: NaiveDate,
    pub end_date: NaiveDate,
    pub color: String,
    pub sort_order: i64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct DashboardSnapshot {
    pub importance_counts: [usize; 4],
    pub remaining_total: usize,
    pub overdue_total: usize,
    pub due_in_7_days: usize,
    pub deadlines: Vec<(NaiveDate, [usize; 4])>,
}

pub fn normalized_importance(value: &str) -> usize {
    match value.trim().to_lowercase().as_str() {
        "高" | "high" => 0,
        "中" | "medium" | "middle" => 1,
        "低" | "low" => 2,
        _ => 3,
    }
}
