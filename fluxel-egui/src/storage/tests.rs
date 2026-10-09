//! Cross-feature SQLite compatibility tests.

use super::*;

fn test_storage() -> (tempfile::TempDir, Storage) {
    let temp = tempfile::tempdir().unwrap();
    let paths = AppPaths {
        state_dir: temp.path().to_owned(),
        database_dir: temp.path().to_owned(),
        settings_file: temp.path().join("settings.ini"),
    };
    let storage = Storage::new(paths).unwrap();
    (temp, storage)
}

#[test]
fn creates_python_compatible_databases() {
    let (_temp, storage) = test_storage();
    let conn = Connection::open(storage.paths.tasks_db()).unwrap();
    let columns = conn
        .prepare("PRAGMA table_info(tasks)")
        .unwrap()
        .query_map([], |row| row.get::<_, String>(1))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert_eq!(
        columns,
        [
            "id",
            "name",
            "description",
            "importance",
            "created_at",
            "update_at",
            "end_date",
            "status",
            "stored_urls"
        ]
    );
}

#[test]
fn task_round_trip_keeps_schema_values() {
    let (_temp, storage) = test_storage();
    let mut task = Task {
        name: "移植確認".to_owned(),
        description: "https://example.com".to_owned(),
        importance: "高".to_owned(),
        end_date: "2030-01-02".to_owned(),
        status: "todo".to_owned(),
        ..Task::default()
    };
    storage.save_task(&mut task).unwrap();
    let loaded = storage.get_task(&task.id).unwrap().unwrap();
    assert_eq!(loaded.name, "移植確認");
    assert_eq!(loaded.description, r"\url:https://example.com");
    assert_eq!(loaded.importance, "高");
}

#[test]
fn quick_access_round_trip_preserves_tags() {
    let (_temp, storage) = test_storage();
    let mut item = QuickAccessItem {
        title: "Docs".to_owned(),
        value: "https://example.com".to_owned(),
        tags: "work, docs,WORK".to_owned(),
        ..QuickAccessItem::default()
    };
    storage
        .save_quick_access(QuickAccessKind::Shortcut, &mut item)
        .unwrap();
    let rows = storage
        .quick_access_items(QuickAccessKind::Shortcut, "Docs", "work")
        .unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(split_tags(&rows[0].tags).len(), 2);
}

#[test]
fn gantt_rejects_reverse_range() {
    let (_temp, storage) = test_storage();
    let mut project = GanttProject {
        title: "P".to_owned(),
        ..GanttProject::default()
    };
    storage.save_gantt_project(&mut project).unwrap();
    let mut term = GanttTerm {
        id: String::new(),
        project_id: project.id,
        title: "T".to_owned(),
        description: String::new(),
        start_date: NaiveDate::from_ymd_opt(2030, 2, 2).unwrap(),
        end_date: NaiveDate::from_ymd_opt(2030, 2, 1).unwrap(),
        color: "#2E7BD9".to_owned(),
        sort_order: 0,
    };
    assert!(storage.save_gantt_term(&mut term).is_err());
}

#[test]
fn exports_consistent_tasks_backup() {
    let (temp, storage) = test_storage();
    let mut task = Task {
        name: "backup".to_owned(),
        status: "todo".to_owned(),
        ..Task::default()
    };
    storage.save_task(&mut task).unwrap();
    let destination = temp.path().join("exports").join("Tasks-copy.db");
    storage.export_tasks_db(&destination).unwrap();
    let count: i64 = Connection::open(destination)
        .unwrap()
        .query_row("SELECT COUNT(*) FROM tasks", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn marker_helpers_match_existing_format() {
    assert_eq!(
        normalize_description("open https://example.com/a"),
        r"open \url:https://example.com/a"
    );
    assert_eq!(
        strip_storage_markers(r"open \url:https://example.com/a"),
        "open https://example.com/a"
    );
    assert_eq!(
        normalize_description(r"read \file|C:\Docs\a.txt|"),
        r"read \file|C:\Docs\a.txt|"
    );
}

#[test]
fn task_search_matches_python_filters_and_title_ranking() {
    let (_temp, storage) = test_storage();
    for (name, description, importance, status, end_date) in [
        ("Alpha title", "body", "高", "todo", "2030-01-03"),
        ("Body only", "contains alpha", "high", "doing", "2030-01-01"),
        ("Archived alpha", "body", "低", "archive", "2030-01-02"),
    ] {
        let mut task = Task {
            name: name.to_owned(),
            description: description.to_owned(),
            importance: importance.to_owned(),
            status: status.to_owned(),
            end_date: end_date.to_owned(),
            ..Task::default()
        };
        storage.save_task(&mut task).unwrap();
    }

    let rows = storage.search_tasks("alpha", false, "", "").unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].name, "Alpha title");

    let filtered = storage.search_tasks("", true, "todo", "high").unwrap();
    assert_eq!(filtered.len(), 1);
    assert_eq!(filtered[0].name, "Alpha title");
}

#[test]
fn deleting_a_known_tag_removes_all_associations() {
    let (_temp, storage) = test_storage();
    let mut shortcut = QuickAccessItem {
        title: "Shortcut".to_owned(),
        value: "value".to_owned(),
        tags: "shared, keep".to_owned(),
        ..QuickAccessItem::default()
    };
    let mut openfile = QuickAccessItem {
        title: "File".to_owned(),
        value: "/tmp/file".to_owned(),
        tags: "shared".to_owned(),
        ..QuickAccessItem::default()
    };
    storage
        .save_quick_access(QuickAccessKind::Shortcut, &mut shortcut)
        .unwrap();
    storage
        .save_quick_access(QuickAccessKind::OpenFile, &mut openfile)
        .unwrap();

    storage.delete_known_tag("shared").unwrap();
    assert_eq!(
        storage
            .quick_access_items(QuickAccessKind::Shortcut, "", "")
            .unwrap()[0]
            .tags,
        "keep"
    );
    assert!(
        storage
            .quick_access_items(QuickAccessKind::OpenFile, "", "")
            .unwrap()[0]
            .tags
            .is_empty()
    );
}

#[test]
fn gantt_move_operations_preserve_content_and_duration() {
    let (_temp, storage) = test_storage();
    let mut first_project = GanttProject {
        title: "First".to_owned(),
        ..GanttProject::default()
    };
    let mut second_project = GanttProject {
        title: "Second".to_owned(),
        ..GanttProject::default()
    };
    storage.save_gantt_project(&mut first_project).unwrap();
    storage.save_gantt_project(&mut second_project).unwrap();

    let date = NaiveDate::from_ymd_opt(2030, 1, 1).unwrap();
    let mut first = GanttTerm {
        id: String::new(),
        project_id: first_project.id.clone(),
        title: "First term".to_owned(),
        description: "keep me".to_owned(),
        start_date: date,
        end_date: date + Duration::days(2),
        color: "#123456".to_owned(),
        sort_order: 0,
    };
    let mut second = GanttTerm {
        id: String::new(),
        project_id: first_project.id.clone(),
        title: "Second term".to_owned(),
        description: "second".to_owned(),
        start_date: date,
        end_date: date + Duration::days(1),
        color: "#654321".to_owned(),
        sort_order: 0,
    };
    storage.save_gantt_term(&mut first).unwrap();
    storage.save_gantt_term(&mut second).unwrap();

    assert!(storage.reorder_gantt_term(&second.id, -1).unwrap());
    assert_eq!(storage.gantt_terms().unwrap()[0].id, second.id);
    assert!(storage.move_gantt_term_days(&first.id, 4).unwrap());
    assert!(
        storage
            .move_gantt_term_to_project(&first.id, &second_project.id)
            .unwrap()
    );
    let moved = storage
        .gantt_terms()
        .unwrap()
        .into_iter()
        .find(|term| term.id == first.id)
        .unwrap();
    assert_eq!(moved.project_id, second_project.id);
    assert_eq!(moved.description, "keep me");
    assert_eq!((moved.end_date - moved.start_date).num_days(), 2);
    assert_eq!(moved.start_date, date + Duration::days(4));
}
