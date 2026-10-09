//! Stable JSON event types shared with the Python folder-sync protocol.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

pub const FORMAT_VERSION: u8 = 1;
pub const SUPPORTED_KINDS: [&str; 6] = [
    "task",
    "shortcut",
    "openfile",
    "tag",
    "gantt_project",
    "gantt_term",
];

#[derive(Clone, Debug)]
pub struct SyncItem {
    pub kind: String,
    pub entity_id: String,
    pub data: Map<String, Value>,
}

impl SyncItem {
    pub fn key(&self) -> String {
        format!("{}:{}", self.kind, self.entity_id)
    }

    pub fn hash(&self) -> String {
        content_hash(Some(&self.data)).unwrap_or_default()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SyncEvent {
    pub format_version: u8,
    pub event_id: String,
    pub device_id: String,
    pub kind: String,
    pub entity_id: String,
    pub operation: String,
    pub created_at: String,
    pub base_hash: Option<String>,
    pub item_hash: Option<String>,
    pub data: Option<Map<String, Value>>,
}

impl SyncEvent {
    pub fn key(&self) -> String {
        format!("{}:{}", self.kind, self.entity_id)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct SyncReport {
    pub downloaded: usize,
    pub uploaded: usize,
    pub deleted: usize,
    pub conflicts: usize,
}

/// Produces Python's `json.dumps(sort_keys=True, separators=(",", ":"))` form.
pub fn canonical_json(value: &Value) -> String {
    serde_json::to_string(value).expect("JSON values are serializable")
}

pub fn content_hash(data: Option<&Map<String, Value>>) -> Option<String> {
    let data = data?;
    let encoded = canonical_json(&Value::Object(data.clone()));
    Some(format!("{:x}", Sha256::digest(encoded.as_bytes())))
}
