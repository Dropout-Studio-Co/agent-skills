//! Read-only OpenCode session store reader.
//!
//! The SQLite database is opened through a URI in read-only mode and never
//! written: `immutable=1` when there is no write-ahead log, plain `mode=ro`
//! when both `-wal` and `-shm` exist, and skipped when a `-wal` file exists
//! without its shared-memory partner (reading would need to create it).

use std::collections::HashSet;
use std::path::PathBuf;

use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use rusqlite::types::Value as SqlValue;
use rusqlite::{Connection, OpenFlags};
use serde_json::{Map, Value};

use super::classify::{
    IMPLEMENTER_OPENING, is_correction, is_noise_text, is_self_session, make_session,
    remove_pasted, truthy,
};
use super::{HumanItem, Session, SessionInput};
use crate::redact::redact;
use crate::repo::{Repo, home_directory};

/// Characters Python's `quote()` leaves untouched (letters, digits and `_.-~/`).
const URI_SET: &AsciiSet = &NON_ALPHANUMERIC
    .remove(b'_')
    .remove(b'.')
    .remove(b'-')
    .remove(b'~')
    .remove(b'/');

/// Absolute path of the OpenCode SQLite store.
pub fn opencode_store() -> PathBuf {
    let data_home = match std::env::var_os("XDG_DATA_HOME") {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => home_directory().join(".local").join("share"),
    };
    data_home.join("opencode").join("opencode.db")
}

/// Split a Windows drive prefix (`C:/`) off a `/`-separated path.
fn drive_prefix(text: &str) -> Option<(&str, &str)> {
    let bytes = text.as_bytes();
    if bytes.len() < 3 || !bytes[0].is_ascii_alphabetic() || bytes[1] != b':' || bytes[2] != b'/' {
        return None;
    }
    Some(text.split_at(3))
}

/// SQLite URI for a read-only handle on `path`.
///
/// Backslashes become `/`. A Windows drive path becomes a `file:///C:/...`
/// URI whose drive letter and colon stay literal; everything else, including
/// spaces and `#`/`?`, is percent-encoded so SQLite never reads them as URI
/// syntax.
fn sqlite_uri(path: &std::path::Path) -> String {
    let text = path.to_string_lossy().replace('\\', "/");
    match drive_prefix(&text) {
        Some((drive, rest)) => {
            format!("file:///{drive}{}", utf8_percent_encode(rest, URI_SET))
        }
        None => format!("file:{}", utf8_percent_encode(&text, URI_SET)),
    }
}

fn with_suffix(path: &std::path::Path, suffix: &str) -> PathBuf {
    let mut name = path.to_path_buf().into_os_string();
    name.push(suffix);
    PathBuf::from(name)
}

fn sql_str(value: &SqlValue) -> Option<&str> {
    match value {
        SqlValue::Text(text) => Some(text.as_str()),
        _ => None,
    }
}

fn python_float(number: f64) -> String {
    if number.fract() == 0.0 && number.abs() < 1e16 {
        format!("{number:.1}")
    } else {
        format!("{number}")
    }
}

fn sql_string(value: &SqlValue) -> String {
    match value {
        SqlValue::Null => "None".to_string(),
        SqlValue::Integer(number) => number.to_string(),
        SqlValue::Real(number) => python_float(*number),
        SqlValue::Text(text) => text.clone(),
        SqlValue::Blob(bytes) => format!("{bytes:?}"),
    }
}

fn sql_f64(value: &SqlValue) -> Option<f64> {
    match value {
        SqlValue::Integer(number) => Some(*number as f64),
        SqlValue::Real(number) => Some(*number),
        _ => None,
    }
}

fn python_json_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for letter in text.chars() {
        match letter {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            letter if (letter as u32) < 0x20 || (letter as u32) > 0x7e => {
                let mut units = [0u16; 2];
                for unit in letter.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
            letter => out.push(letter),
        }
    }
    out.push('"');
    out
}

/// Python's `json.dumps` defaults (`, ` and `: ` separators, ASCII escapes).
fn python_json(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(flag) => if *flag { "true" } else { "false" }.to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => python_json_string(text),
        Value::Array(items) => {
            let rendered: Vec<String> = items.iter().map(python_json).collect();
            format!("[{}]", rendered.join(", "))
        }
        Value::Object(map) => {
            let rendered: Vec<String> = map
                .iter()
                .map(|(key, item)| format!("{}: {}", python_json_string(key), python_json(item)))
                .collect();
            format!("{{{}}}", rendered.join(", "))
        }
    }
}

fn display_value(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        other => python_json(other),
    }
}

fn table_names(connection: &Connection) -> rusqlite::Result<HashSet<String>> {
    let mut statement =
        connection.prepare("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
    let mut names = HashSet::new();
    for row in rows {
        names.insert(row?);
    }
    Ok(names)
}

fn column_names(connection: &Connection, table: &str) -> rusqlite::Result<HashSet<String>> {
    let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
    let rows = statement.query_map([], |row| row.get::<_, String>(1))?;
    let mut names = HashSet::new();
    for row in rows {
        names.insert(row?);
    }
    Ok(names)
}

fn recognize_opencode(kind: Option<&str>, data: &Map<String, Value>) -> (bool, bool) {
    match kind {
        Some("user") => {
            let ok = data.get("text").is_some_and(Value::is_string);
            (ok, ok)
        }
        Some("assistant") => (data.get("content").is_some_and(Value::is_array), false),
        _ => (true, false),
    }
}

fn opencode_human_text(text: &str) -> Option<String> {
    let cleaned = remove_pasted(text).trim().to_string();
    if cleaned.is_empty() || is_noise_text(&cleaned) {
        return None;
    }
    Some(cleaned)
}

fn opencode_errors(data: &Map<String, Value>) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();
    let items = match data.get("content") {
        Some(Value::Array(items)) if !items.is_empty() => items,
        _ => return errors,
    };
    for item in items {
        let Value::Object(item) = item else {
            continue;
        };
        if item.get("type").and_then(Value::as_str) != Some("tool") {
            continue;
        }
        let Some(Value::Object(state)) = item.get("state").filter(|value| truthy(value)) else {
            continue;
        };
        if state.get("status").and_then(Value::as_str) != Some("error") {
            continue;
        }
        let detail = match state.get("error") {
            Some(Value::Object(error)) => {
                let message = error.get("message");
                let kind = error.get("type");
                let has_message = message.is_some_and(truthy);
                let has_kind = kind.is_some_and(truthy);
                if has_message && has_kind {
                    format!(
                        "{}: {}",
                        display_value(kind.expect("kind present")),
                        display_value(message.expect("message present"))
                    )
                } else if has_message {
                    display_value(message.expect("message present"))
                } else if has_kind {
                    display_value(kind.expect("kind present"))
                } else {
                    python_json(&Value::Object(error.clone()))
                }
            }
            Some(Value::String(text)) if !text.is_empty() => text.clone(),
            _ => {
                let detail = state
                    .get("output")
                    .filter(|value| truthy(value))
                    .or_else(|| item.get("name").filter(|value| truthy(value)));
                match detail {
                    Some(Value::String(text)) => text.clone(),
                    Some(other) => python_json(other),
                    None => "tool error".to_string(),
                }
            }
        };
        errors.push(detail);
    }
    errors
}

struct SessionRow {
    id: SqlValue,
    directory: SqlValue,
    last: SqlValue,
    parent: SqlValue,
    fork: SqlValue,
}

fn session_rows(
    connection: &Connection,
    has_fork_column: bool,
) -> rusqlite::Result<Vec<SessionRow>> {
    let fork_select = if has_fork_column {
        ", s.fork_session_id"
    } else {
        ""
    };
    let sql = format!(
        "SELECT s.id, s.directory, MAX(m.time_created), s.parent_id{fork_select} \
         FROM session_v2 s JOIN session_message m ON m.session_id=s.id GROUP BY s.id"
    );
    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map([], |row| {
        Ok(SessionRow {
            id: row.get(0)?,
            directory: row.get(1)?,
            last: row.get(2)?,
            parent: row.get(3)?,
            fork: if has_fork_column {
                row.get(4)?
            } else {
                SqlValue::Null
            },
        })
    })?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row?);
    }
    Ok(out)
}

/// Read the OpenCode store. Returns `(sessions, v1_only_count, drift_source)`.
pub fn opencode_sessions(repo: &Repo, cutoff: f64) -> (Vec<Session>, u64, Option<String>) {
    let db = opencode_store();
    if !db.is_file() {
        eprintln!(
            "collect_sessions: no OpenCode database at {}; skipped",
            db.display()
        );
        return (Vec::new(), 0, None);
    }
    let store_uri = sqlite_uri(&db);
    let base = format!("{store_uri}?mode=ro");
    let wal = with_suffix(&db, "-wal");
    let shm = with_suffix(&db, "-shm");
    let uri = if !wal.exists() {
        format!("{base}&immutable=1")
    } else if shm.exists() {
        base
    } else {
        eprintln!(
            "collect_sessions: OpenCode database has a WAL but no shared-memory file; skipped: {}",
            db.display()
        );
        return (Vec::new(), 0, None);
    };
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY
        | OpenFlags::SQLITE_OPEN_URI
        | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let connection = match Connection::open_with_flags(&uri, flags) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!(
                "collect_sessions: cannot read OpenCode database {}; skipped: {error}",
                db.display()
            );
            return (Vec::new(), 0, Some("opencode".to_string()));
        }
    };

    let tables = match table_names(&connection) {
        Ok(tables) => tables,
        Err(error) => {
            eprintln!(
                "collect_sessions: skipping the OpenCode store ({}): {error}",
                db.display()
            );
            return (Vec::new(), 0, Some("opencode".to_string()));
        }
    };
    let mut columns: HashSet<String> = HashSet::new();
    if tables.contains("session_v2") {
        match column_names(&connection, "session_v2") {
            Ok(found) => columns = found,
            Err(error) => {
                eprintln!(
                    "collect_sessions: skipping the OpenCode store ({}): {error}",
                    db.display()
                );
                return (Vec::new(), 0, Some("opencode".to_string()));
            }
        }
    }
    if !tables.contains("session_v2")
        || !tables.contains("session_message")
        || !columns.contains("parent_id")
    {
        eprintln!(
            "collect_sessions: skipping the OpenCode store ({}): required tables or parent_id \
             column missing",
            db.display()
        );
        return (Vec::new(), 0, Some("opencode".to_string()));
    }
    let v2_ids: HashSet<String> =
        match connection
            .prepare("SELECT id FROM session_v2")
            .and_then(|mut statement| {
                let rows = statement.query_map([], |row| row.get::<_, SqlValue>(0))?;
                let mut ids = HashSet::new();
                for row in rows {
                    ids.insert(sql_string(&row?));
                }
                Ok(ids)
            }) {
            Ok(ids) => ids,
            Err(error) => {
                eprintln!(
                    "collect_sessions: skipping the OpenCode store ({}): {error}",
                    db.display()
                );
                return (Vec::new(), 0, Some("opencode".to_string()));
            }
        };

    let v1_only = count_v1_only(&connection, &v2_ids, repo, cutoff);

    let rows = match session_rows(&connection, columns.contains("fork_session_id")) {
        Ok(rows) => rows,
        Err(error) => {
            eprintln!(
                "collect_sessions: skipping the OpenCode store ({}): {error}",
                db.display()
            );
            return (Vec::new(), v1_only, Some("opencode".to_string()));
        }
    };

    let mut sessions: Vec<Session> = Vec::new();
    let mut total: u64 = 0;
    let mut recognized: u64 = 0;
    let mut user_ok = false;
    for row in rows {
        let session_id_value = row.id.clone();
        let session_id = sql_string(&row.id);
        let fork_group = match &row.fork {
            SqlValue::Text(fork) if !fork.is_empty() => fork.clone(),
            _ => session_id.clone(),
        };
        let last_value = sql_f64(&row.last).unwrap_or(0.0);
        let mtime = if last_value > 1e12 {
            last_value / 1000.0
        } else {
            last_value
        };
        let Some(directory) = sql_str(&row.directory) else {
            continue;
        };
        if directory.trim().is_empty() {
            continue;
        }
        if mtime < cutoff || !repo.member(directory) {
            continue;
        }
        let is_child = match &row.parent {
            SqlValue::Null => false,
            SqlValue::Text(parent) => !parent.is_empty(),
            _ => true,
        };
        if is_child {
            sessions.push(make_session(SessionInput {
                source: "opencode".to_string(),
                label: session_id,
                mtime,
                headless: false,
                human: Vec::new(),
                errors: Vec::new(),
                excluded: true,
                group: Some(fork_group),
            }));
            continue;
        }

        let mut human: Vec<HumanItem> = Vec::new();
        let mut errors: Vec<String> = Vec::new();
        let mut excluded = false;
        let messages = connection.prepare(
            "SELECT id, type, data FROM session_message WHERE session_id = ? ORDER BY seq",
        );
        let messages = match messages.and_then(|mut statement| {
            let rows = statement.query_map([&session_id_value], |row| {
                Ok((
                    row.get::<_, SqlValue>(0)?,
                    row.get::<_, SqlValue>(1)?,
                    row.get::<_, SqlValue>(2)?,
                ))
            })?;
            let mut collected = Vec::new();
            for row in rows {
                collected.push(row?);
            }
            Ok(collected)
        }) {
            Ok(messages) => messages,
            Err(error) => {
                eprintln!("collect_sessions: skipping an OpenCode session ({session_id}): {error}");
                continue;
            }
        };
        for (message_id_value, kind_value, data_value) in messages {
            total += 1;
            let Some(raw) = sql_str(&data_value) else {
                continue;
            };
            let Ok(data) = serde_json::from_str::<Value>(raw) else {
                continue;
            };
            let Value::Object(data) = data else {
                continue;
            };
            let kind = sql_str(&kind_value);
            let (ok, well_formed_user) = recognize_opencode(kind, &data);
            if ok {
                recognized += 1;
            }
            if well_formed_user {
                user_ok = true;
                let text = data.get("text").and_then(Value::as_str).unwrap_or("");
                if is_self_session(text) || text.trim_start().starts_with(IMPLEMENTER_OPENING) {
                    excluded = true;
                }
                if let Some(cleaned) = opencode_human_text(text) {
                    human.push(HumanItem {
                        msg: sql_string(&message_id_value),
                        text: redact(&cleaned),
                        correction: is_correction(&cleaned),
                    });
                }
            } else if kind == Some("assistant") && data.get("content").is_some_and(Value::is_array)
            {
                errors.extend(opencode_errors(&data));
            }
        }
        sessions.push(make_session(SessionInput {
            source: "opencode".to_string(),
            label: session_id,
            mtime,
            headless: false,
            human,
            errors,
            excluded,
            group: Some(fork_group),
        }));
    }

    if total >= 20 && (recognized * 2 < total || !user_ok) {
        return (sessions, v1_only, Some("opencode".to_string()));
    }
    (sessions, v1_only, None)
}

/// Count v1-only sessions without touching the v1 message/part tables.
fn count_v1_only(
    connection: &Connection,
    v2_ids: &HashSet<String>,
    repo: &Repo,
    cutoff: f64,
) -> u64 {
    let Ok(columns) = column_names(connection, "session") else {
        return 0;
    };
    if columns.is_empty() {
        return 0;
    }
    let has_time = columns.contains("time_updated");
    let sql = if has_time {
        "SELECT id, directory, time_updated FROM session"
    } else {
        "SELECT id, directory FROM session"
    };
    let mut count = 0u64;
    let scanned = (|| -> rusqlite::Result<()> {
        let mut statement = connection.prepare(sql)?;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let id = sql_string(&row.get::<_, SqlValue>(0)?);
            if v2_ids.contains(&id) {
                continue;
            }
            let directory_value = row.get::<_, SqlValue>(1)?;
            let Some(directory) = sql_str(&directory_value) else {
                continue;
            };
            if directory.trim().is_empty() {
                continue;
            }
            if !repo.member(directory) {
                continue;
            }
            if has_time {
                let last = sql_f64(&row.get::<_, SqlValue>(2)?).unwrap_or(0.0);
                let mtime = if last > 1e12 { last / 1000.0 } else { last };
                if mtime < cutoff {
                    continue;
                }
            }
            count += 1;
        }
        Ok(())
    })();
    if scanned.is_err() {
        return 0;
    }
    count
}

#[cfg(test)]
mod tests {
    use super::*;

    fn error_content(item: Value) -> Map<String, Value> {
        serde_json::from_value(serde_json::json!({
            "content": [item],
        }))
        .expect("assistant content object")
    }

    #[test]
    fn windows_store_paths_become_read_only_uris() {
        assert_eq!(
            sqlite_uri(std::path::Path::new(
                r"C:\work\alice\AppData\Local\opencode\opencode.db"
            )),
            "file:///C:/work/alice/AppData/Local/opencode/opencode.db"
        );
        assert_eq!(
            sqlite_uri(std::path::Path::new(
                r"C:\work\al ice\opencode #1?\opencode.db"
            )),
            "file:///C:/work/al%20ice/opencode%20%231%3F/opencode.db"
        );
    }

    #[test]
    fn unix_store_paths_keep_the_file_prefix_and_encode_specials() {
        assert_eq!(
            sqlite_uri(std::path::Path::new("/srv/state/opencode/opencode.db")),
            "file:/srv/state/opencode/opencode.db"
        );
        assert_eq!(
            sqlite_uri(std::path::Path::new("/srv/open code/opencode.db")),
            "file:/srv/open%20code/opencode.db"
        );
    }

    #[test]
    fn a_tool_error_prefers_state_output_over_the_tool_name() {
        let data = error_content(serde_json::json!({
            "type": "tool",
            "name": "bash",
            "state": {"status": "error", "output": "boom"},
        }));
        assert_eq!(opencode_errors(&data), vec!["boom".to_string()]);
    }

    #[test]
    fn a_tool_error_falls_back_to_the_name_then_the_default() {
        let named = error_content(serde_json::json!({
            "type": "tool",
            "name": "bash",
            "state": {"status": "error"},
        }));
        assert_eq!(opencode_errors(&named), vec!["bash".to_string()]);
        let bare = error_content(serde_json::json!({
            "type": "tool",
            "state": {"status": "error"},
        }));
        assert_eq!(opencode_errors(&bare), vec!["tool error".to_string()]);
    }
}
