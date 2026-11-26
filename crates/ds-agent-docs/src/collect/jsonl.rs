//! Transcript discovery and streaming scan for filesystem session stores.
//!
//! Claude Code keeps one directory per repository under `<config>/projects`,
//! holding `.jsonl` (and optionally `.jsonl.zst`) transcripts. Extra directories
//! are searched recursively for `*.json*`. Files are streamed line by line and
//! scanned in parallel while the result keeps the exact input order.

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use rayon::prelude::*;
use serde_json::Value;
use walkdir::WalkDir;

use super::classify::{
    HUMAN_ROLES, IMPLEMENTER_OPENING, error_texts, find_cwd, human_text, is_correction,
    is_headless, is_self_session, make_session, message_id, recognized_record, record_role, truthy,
    user_raw_text,
};
use super::{HumanItem, ScanStats, Session, SessionInput};
use crate::redact::redact;
use crate::repo::Repo;

/// Sessions plus their format-drift counters.
pub type SessionScan = (Vec<Session>, ScanStats);

/// Seconds of a filesystem timestamp relative to the Unix epoch.
fn system_time_secs(time: SystemTime) -> f64 {
    match time.duration_since(UNIX_EPOCH) {
        Ok(elapsed) => elapsed.as_secs_f64(),
        Err(error) => -error.duration().as_secs_f64(),
    }
}

fn home_directory() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
}

/// Claude Code's configuration directory.
fn claude_home() -> PathBuf {
    match std::env::var_os("CLAUDE_CONFIG_DIR") {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => home_directory().join(".claude"),
    }
}

fn expand_user(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix('~') {
        let home = home_directory();
        if rest.is_empty() {
            return home;
        }
        if let Some(after) = rest.strip_prefix('/') {
            return home.join(after);
        }
    }
    path.to_path_buf()
}

fn path_string(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// Stream every decoded line of a transcript, closing the source.
fn read_transcript_lines(path: &Path, visit: &mut impl FnMut(String)) {
    if path.extension().and_then(|ext| ext.to_str()) == Some("zst") {
        let Ok(file) = File::open(path) else {
            return;
        };
        let Ok(decoder) = zstd::Decoder::new(file) else {
            return;
        };
        consume_lines(BufReader::new(decoder), visit);
        return;
    }
    if let Ok(file) = File::open(path) {
        consume_lines(BufReader::new(file), visit);
    }
}

fn consume_lines(reader: impl BufRead, visit: &mut impl FnMut(String)) {
    let mut reader = reader;
    let mut buffer: Vec<u8> = Vec::new();
    loop {
        buffer.clear();
        match reader.read_until(b'\n', &mut buffer) {
            Ok(0) | Err(_) => break,
            Ok(_) => visit(String::from_utf8_lossy(&buffer).into_owned()),
        }
    }
}

/// Visit one item per counted transcript entry: a record, or `None` when the
/// entry did not parse as a JSON object.
fn iterate_records(path: &Path, mut visit: impl FnMut(Option<Value>)) {
    if path.extension().and_then(|ext| ext.to_str()) == Some("json") {
        let Ok(bytes) = std::fs::read(path) else {
            return;
        };
        let raw = String::from_utf8_lossy(&bytes).into_owned();
        iterate_document(&raw, &mut visit);
        return;
    }
    read_transcript_lines(path, &mut |line| {
        if line.trim().is_empty() {
            return;
        }
        let record = match serde_json::from_str::<Value>(&line) {
            Ok(value) if value.is_object() => Some(value),
            _ => None,
        };
        visit(record);
    });
}

fn iterate_document(raw: &str, visit: &mut impl FnMut(Option<Value>)) {
    let data: Value = match serde_json::from_str(raw) {
        Ok(value) => value,
        Err(_) => {
            visit(None);
            return;
        }
    };
    match data {
        Value::Array(items) => {
            for item in items {
                visit(if item.is_object() { Some(item) } else { None });
            }
        }
        Value::Object(map) => {
            let chosen = ["messages", "history"]
                .iter()
                .filter_map(|key| map.get(*key))
                .find(|value| truthy(value));
            let items: Vec<Value> = match chosen {
                Some(Value::Array(list)) => list.clone(),
                _ => vec![Value::Object(map)],
            };
            for item in items {
                visit(if item.is_object() { Some(item) } else { None });
            }
        }
        _ => visit(None),
    }
}

/// Scan one transcript in a single streaming pass; the record count is the
/// drift total.
pub fn scan_jsonl_session(
    path: &Path,
    mtime: f64,
    source: &str,
    repo: &Repo,
) -> (Session, ScanStats) {
    let mut total: u64 = 0;
    let mut recognized: u64 = 0;
    let mut user_ok = false;
    let mut headless = false;
    let mut excluded = false;
    let mut last_cwd: Option<String> = None;
    let mut started = false;
    let mut human: Vec<HumanItem> = Vec::new();
    let mut errors: Vec<String> = Vec::new();

    iterate_records(path, |record| {
        total += 1;
        let Some(record) = record else {
            return;
        };
        let (ok, is_user) = recognized_record(&record);
        if ok {
            recognized += 1;
        }
        if is_user {
            user_ok = true;
        }
        if !excluded
            && record_role(&record)
                .and_then(Value::as_str)
                .is_some_and(|role| HUMAN_ROLES.contains(&role))
        {
            let raw = user_raw_text(&record);
            excluded = is_self_session(&raw) || raw.trim_start().starts_with(IMPLEMENTER_OPENING);
        }
        if let Some(found) = find_cwd(&record) {
            last_cwd = Some(found);
            started = true;
        }
        let Some(cwd) = last_cwd.as_deref() else {
            return;
        };
        if !started || !repo.member(cwd) {
            return;
        }
        if is_headless(&record) {
            headless = true;
        }
        if let Some(text) = human_text(&record) {
            human.push(HumanItem {
                msg: message_id(&record, &text),
                text: redact(&text),
                correction: is_correction(&text),
            });
        }
        errors.extend(error_texts(&record));
    });

    let label = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| path_string(path));
    let session = make_session(SessionInput {
        source: source.to_string(),
        label,
        mtime,
        headless,
        human,
        errors,
        excluded,
        group: None,
    });
    let stats = ScanStats {
        total,
        recognized,
        user_ok,
    };
    (session, stats)
}

/// Scan `(path, mtime)` targets; sessions and stats keep the exact input order.
pub fn scan_targets(targets: &[(PathBuf, f64)], source: &str, repo: &Repo) -> SessionScan {
    let mut stats = ScanStats::default();
    if targets.is_empty() {
        return (Vec::new(), stats);
    }
    let scanned: Vec<(Session, ScanStats)> = if targets.len() == 1 {
        vec![scan_jsonl_session(
            &targets[0].0,
            targets[0].1,
            source,
            repo,
        )]
    } else {
        targets
            .par_iter()
            .map(|(path, mtime)| scan_jsonl_session(path, *mtime, source, repo))
            .collect()
    };
    let mut sessions = Vec::with_capacity(scanned.len());
    for (session, file_stats) in scanned {
        sessions.push(session);
        stats.total += file_stats.total;
        stats.recognized += file_stats.recognized;
        stats.user_ok = stats.user_ok || file_stats.user_ok;
    }
    (sessions, stats)
}

/// Claude Code project directories whose encoded path names this repository.
fn candidate_project_dirs(claude_home: &Path, repo: &Repo) -> Vec<PathBuf> {
    let projects = claude_home.join("projects");
    if !projects.is_dir() {
        return Vec::new();
    }
    let names = repo.encoded_names();
    let Ok(entries) = std::fs::read_dir(&projects) else {
        return Vec::new();
    };
    let mut out: Vec<PathBuf> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        if names
            .iter()
            .any(|encoded| name == *encoded || name.starts_with(&format!("{encoded}-")))
        {
            out.push(path);
        }
    }
    out
}

/// `.jsonl` and `.jsonl.zst` files in one project directory, hidden files skipped.
fn transcript_files(directory: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return Vec::new();
    };
    let mut out: Vec<PathBuf> = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }
        if name.ends_with(".jsonl") || name.ends_with(".jsonl.zst") {
            out.push(entry.path());
        }
    }
    out
}

fn modified_secs(path: &Path) -> Option<f64> {
    let metadata = path.metadata().ok()?;
    let modified = metadata.modified().ok()?;
    Some(system_time_secs(modified))
}

/// Sessions from the Claude Code transcript store.
pub fn claude_sessions(repo: &Repo, cutoff: f64) -> SessionScan {
    let mut directories = candidate_project_dirs(&claude_home(), repo);
    directories.sort_by_key(|path| path_string(path));
    let mut targets: Vec<(PathBuf, f64)> = Vec::new();
    for directory in directories {
        let mut files = transcript_files(&directory);
        files.sort_by_key(|path| path_string(path));
        for path in files {
            if let Some(mtime) = modified_secs(&path)
                && mtime >= cutoff
            {
                targets.push((path, mtime));
            }
        }
    }
    scan_targets(&targets, "claude-code", repo)
}

/// `*.json*` names match the Python recursive glob (`*` never matches a leading dot).
fn matches_json_pattern(name: &str) -> bool {
    name.contains(".json")
}

/// Sessions from the caller-supplied extra directories.
pub fn extra_sessions(repo: &Repo, extra_dirs: &[PathBuf], cutoff: f64) -> SessionScan {
    let mut targets: Vec<(PathBuf, f64)> = Vec::new();
    for directory in extra_dirs {
        let root = expand_user(directory);
        let mut files: Vec<PathBuf> = Vec::new();
        let walker = WalkDir::new(&root).into_iter().filter_entry(|entry| {
            entry.depth() == 0 || !entry.file_name().to_string_lossy().starts_with('.')
        });
        for entry in walker.flatten() {
            if matches_json_pattern(&entry.file_name().to_string_lossy()) {
                files.push(entry.path().to_path_buf());
            }
        }
        files.sort_by_key(|path| path_string(path));
        for path in files {
            if !path.is_file() {
                continue;
            }
            if let Some(mtime) = modified_secs(&path)
                && mtime >= cutoff
            {
                targets.push((path, mtime));
            }
        }
    }
    scan_targets(&targets, "extra", repo)
}
