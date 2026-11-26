//! `collect` command: compact digest of past agent sessions for one repository.
//!
//! Scans local transcript stores of common coding agents (Claude Code and
//! OpenCode, plus any extra dirs passed), keeps only sessions that ran inside
//! the repository (its main checkout or any live linked worktree), and prints
//! the high-signal parts: human messages (corrections flagged first) and failed
//! tool calls. Secrets and home paths are redacted.

pub mod classify;
pub mod jsonl;
pub mod opencode;

use std::collections::{BTreeMap, HashMap};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use chrono::TimeZone;
use serde_json::{Value, json};

use crate::git::run_git;
use crate::redact::{clip, redact};
use crate::repo::{Repo, resolve_lenient, resolve_repo_root};

use self::classify::drift_source;

/// Arguments accepted by the `collect` subcommand.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectArgs {
    /// Repository root; defaults to the current repository.
    pub repo: Option<PathBuf>,
    /// Only sessions touched within this many days.
    pub days: i64,
    /// Maximum characters of session evidence kept.
    pub max_chars: usize,
    /// Extra transcript directories to scan.
    pub extra_dirs: Vec<PathBuf>,
    /// Exit non-zero when a transcript format drifted.
    pub strict: bool,
    /// Optional path where the evidence JSON is written.
    pub evidence_out: Option<PathBuf>,
}

/// One human message kept as evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HumanItem {
    /// Stable message identifier.
    pub msg: String,
    /// Redacted message text.
    pub text: String,
    /// Whether the message reads as a correction.
    pub correction: bool,
}

/// One collected session.
#[derive(Debug, Clone)]
pub struct Session {
    /// `<source>:<label>` identity.
    pub id: String,
    /// Store the session came from.
    pub source: String,
    /// File name or session id.
    pub label: String,
    /// Last-modified time, seconds since the epoch.
    pub mtime: f64,
    /// Whether the session is non-interactive.
    pub headless: bool,
    /// Fork/group identity.
    pub group: String,
    /// Human evidence, in transcript order.
    pub human: Vec<HumanItem>,
    /// Tool-error texts.
    pub errors: Vec<String>,
    /// Whether the session is left out of the digest.
    pub excluded: bool,
}

/// Inputs used to assemble a [`Session`].
#[derive(Debug)]
pub struct SessionInput {
    /// Store the session came from.
    pub source: String,
    /// File name or session id.
    pub label: String,
    /// Last-modified time, seconds since the epoch.
    pub mtime: f64,
    /// Whether the session is non-interactive.
    pub headless: bool,
    /// Human evidence.
    pub human: Vec<HumanItem>,
    /// Tool-error texts.
    pub errors: Vec<String>,
    /// Whether the session is already excluded.
    pub excluded: bool,
    /// Fork/group identity, defaulting to the label.
    pub group: Option<String>,
}

/// Format-drift counters for one source.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ScanStats {
    /// Records read.
    pub total: u64,
    /// Records recognised as transcript entries.
    pub recognized: u64,
    /// Whether at least one well-formed user record was seen.
    pub user_ok: bool,
}

/// Session counts reported in the header and the evidence.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Counts {
    /// Sessions in the window.
    pub total: usize,
    /// Non-excluded interactive sessions.
    pub interactive: usize,
    /// Non-excluded headless sessions.
    pub headless: usize,
    /// Sessions left out.
    pub excluded: usize,
}

/// Run the collector and return its process exit code.
pub fn run_collect(args: CollectArgs) -> i32 {
    let repo = Repo::new(&resolve_repo_root(args.repo.as_deref()));
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs_f64())
        .unwrap_or(0.0);
    let cutoff = now - args.days as f64 * 86400.0;

    let ((claude_result, extra_result), opencode_result) = std::thread::scope(|scope| {
        let filesystem = scope.spawn(|| {
            (
                jsonl::claude_sessions(&repo, cutoff),
                jsonl::extra_sessions(&repo, &args.extra_dirs, cutoff),
            )
        });
        let store = scope.spawn(|| opencode::opencode_sessions(&repo, cutoff));
        let filesystem = filesystem.join().unwrap_or_else(|_| {
            (
                (Vec::new(), ScanStats::default()),
                (Vec::new(), ScanStats::default()),
            )
        });
        let store = store.join().unwrap_or_else(|_| (Vec::new(), 0, None));
        (filesystem, store)
    });

    let (claude, claude_stats) = claude_result;
    let (extra, extra_stats) = extra_result;
    let (opens, v1_only, opencode_drift) = opencode_result;
    let mut sessions = claude;
    sessions.extend(extra);
    sessions.extend(opens);

    let mut drift: Vec<String> = Vec::new();
    if let Some(source) = drift_source("claude-code", &claude_stats) {
        drift.push(source);
    }
    if let Some(source) = drift_source("extra", &extra_stats) {
        drift.push(source);
    }
    if let Some(source) = opencode_drift {
        drift.push(source);
    }

    let (text, shown, _counts, _range) =
        build_digest(&repo, &sessions, args.days, args.max_chars, now, &drift);
    if let Some(path) = args.evidence_out.as_deref() {
        let mut evidence = build_evidence(&repo, &sessions, args.days, now, &drift, v1_only);
        evidence["counts"]["digest_shown"] = json!(shown);
        let status = write_evidence(path, &evidence);
        if status != 0 {
            return status;
        }
    }
    let stdout = std::io::stdout();
    let mut handle = stdout.lock();
    let _ = handle.write_all(text.as_bytes());
    let _ = handle.flush();
    if args.strict && !drift.is_empty() {
        return 3;
    }
    0
}

fn local_date(mtime: f64) -> String {
    let seconds = if mtime.is_finite() {
        mtime.trunc() as i64
    } else {
        0
    };
    match chrono::Local.timestamp_opt(seconds, 0).single() {
        Some(moment) => moment.format("%Y-%m-%d").to_string(),
        None => "1970-01-01".to_string(),
    }
}

fn generated_at(now: f64) -> String {
    let seconds = if now.is_finite() {
        now.trunc() as i64
    } else {
        0
    };
    match chrono::DateTime::<chrono::Utc>::from_timestamp(seconds, 0) {
        Some(moment) => moment.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        None => String::new(),
    }
}

fn counts_for(sessions: &[Session]) -> Counts {
    let total = sessions.len();
    let interactive = sessions
        .iter()
        .filter(|session| !session.excluded && !session.headless)
        .count();
    let headless = sessions
        .iter()
        .filter(|session| !session.excluded && session.headless)
        .count();
    Counts {
        total,
        interactive,
        headless,
        excluded: total - interactive - headless,
    }
}

fn date_range(sessions: &[&Session]) -> (String, String) {
    if sessions.is_empty() {
        return ("none".to_string(), "none".to_string());
    }
    let mut start = f64::INFINITY;
    let mut end = f64::NEG_INFINITY;
    for session in sessions {
        start = start.min(session.mtime);
        end = end.max(session.mtime);
    }
    (local_date(start), local_date(end))
}

fn header_line(
    repo: &Repo,
    days: i64,
    counts: &Counts,
    shown: usize,
    shown_sessions: &[&Session],
) -> String {
    let (start, end) = date_range(shown_sessions);
    format!(
        "# Session digest for {}\n_{} sessions in last {} days: {} interactive, {} headless, \
         {} excluded, {} shown. {} to {}. Corrections marked \u{2691}._",
        redact(&repo.root.to_string_lossy()),
        counts.total,
        days,
        counts.interactive,
        counts.headless,
        counts.excluded,
        shown,
        start,
        end
    )
}

fn session_block(session: &Session) -> String {
    let mut lines = vec![format!(
        "## {} \u{b7} {} \u{b7} {}",
        local_date(session.mtime),
        session.source,
        session.label
    )];
    let flagged = session.human.iter().filter(|item| item.correction).take(15);
    for item in flagged {
        lines.push(format!("- \u{2691} {}", clip(&item.text, 400)));
    }
    let others = session
        .human
        .iter()
        .filter(|item| !item.correction)
        .take(15);
    for item in others {
        lines.push(format!("- {}", clip(&item.text, 250)));
    }
    for error in session.errors.iter().take(8) {
        lines.push(format!("- \u{2717} error: {}", clip(error, 200)));
    }
    format!("{}\n", lines.join("\n"))
}

fn week_index(mtime: f64, now: f64) -> i64 {
    ((now - mtime).max(0.0) / (7.0 * 86400.0)).floor() as i64
}

/// One session per weekly bucket in turn, interactive groups before headless.
fn round_robin(sessions: &[Session], now: f64) -> Vec<&Session> {
    let mut ordered: Vec<&Session> = Vec::new();
    for headless in [false, true] {
        let group: Vec<&Session> = sessions
            .iter()
            .filter(|session| !session.excluded && session.headless == headless)
            .collect();
        let mut buckets: BTreeMap<i64, Vec<&Session>> = BTreeMap::new();
        for session in group {
            buckets
                .entry(week_index(session.mtime, now))
                .or_default()
                .push(session);
        }
        for bucket in buckets.values_mut() {
            bucket.sort_by(|left, right| right.mtime.total_cmp(&left.mtime));
        }
        let keys: Vec<i64> = buckets.keys().copied().collect();
        let mut position: HashMap<i64, usize> = keys.iter().map(|key| (*key, 0)).collect();
        loop {
            let mut more = false;
            for key in &keys {
                let bucket = &buckets[key];
                let index = position.get_mut(key).expect("position is seeded per key");
                if *index < bucket.len() {
                    ordered.push(bucket[*index]);
                    *index += 1;
                    more = true;
                }
            }
            if !more {
                break;
            }
        }
    }
    ordered
}

/// Build the digest text and the number of blocks it actually shows.
fn build_digest(
    repo: &Repo,
    sessions: &[Session],
    days: i64,
    max_chars: usize,
    now: f64,
    drift: &[String],
) -> (String, usize, Counts, (String, String)) {
    let counts = counts_for(sessions);
    let ordered = round_robin(sessions, now);
    let pairs: Vec<(&Session, String)> = ordered
        .iter()
        .map(|session| (*session, session_block(session)))
        .collect();
    let mut shown = 0usize;
    let mut chosen: Vec<String> = Vec::new();
    let mut chosen_sessions: Vec<&Session> = Vec::new();
    for _ in 0..6 {
        let header = header_line(repo, days, &counts, shown, &chosen_sessions);
        let mut remaining = max_chars as i64 - header.chars().count() as i64;
        chosen = Vec::new();
        chosen_sessions = Vec::new();
        for (session, block) in &pairs {
            let length = block.chars().count() as i64;
            if length <= remaining {
                chosen.push(block.clone());
                chosen_sessions.push(*session);
                remaining -= length;
            }
        }
        if chosen.len() == shown {
            break;
        }
        shown = chosen.len();
    }
    let header = header_line(repo, days, &counts, shown, &chosen_sessions);
    let body = chosen.concat();
    let mut lines: Vec<String> = drift
        .iter()
        .map(|source| format!("FORMAT DRIFT: {source}"))
        .collect();
    lines.push(header);
    let text = format!("{}\n{}", lines.join("\n"), body);
    (text, shown, counts, date_range(&chosen_sessions))
}

fn build_evidence(
    repo: &Repo,
    sessions: &[Session],
    days: i64,
    now: f64,
    drift: &[String],
    v1_only: u64,
) -> Value {
    let counts = counts_for(sessions);
    let included: Vec<&Session> = sessions
        .iter()
        .filter(|session| !session.excluded)
        .collect();
    let (start, end) = date_range(&included);
    let entries: Vec<Value> = included
        .iter()
        .map(|session| {
            json!({
                "id": session.id,
                "source": session.source,
                "kind": if session.headless { "headless" } else { "interactive" },
                "date": local_date(session.mtime),
                "group": session.group,
                "human": session
                    .human
                    .iter()
                    .map(|item| json!({
                        "msg": item.msg,
                        "text": item.text,
                        "correction": item.correction,
                    }))
                    .collect::<Vec<_>>(),
                "errors": session.errors,
            })
        })
        .collect();
    json!({
        "version": 1,
        "repo_id": repo.repo_id,
        "generated_at": generated_at(now),
        "window_days": days,
        "counts": {
            "total": counts.total,
            "interactive": counts.interactive,
            "headless": counts.headless,
            "excluded": counts.excluded,
            "shown": included.len(),
            "opencode_v1_only": v1_only,
        },
        "date_range": {"start": start, "end": end},
        "drift": drift,
        "sessions": entries,
    })
}

/// Refuse a path that exists, has no usable parent, or sits inside a worktree.
fn evidence_path_problem(path: &Path) -> Option<&'static str> {
    if std::fs::symlink_metadata(path).is_ok() {
        return Some("path already exists");
    }
    let parent = match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent,
        _ => Path::new("."),
    };
    let parent_real = resolve_lenient(parent);
    if !parent_real.is_dir() {
        return Some("parent directory does not exist");
    }
    if inside_git_worktree(&parent_real) {
        return Some("path is inside a git worktree");
    }
    None
}

/// True when `directory` is a checkout, a worktree member or inside `.git`.
fn inside_git_worktree(directory: &Path) -> bool {
    let mut probe = match std::fs::canonicalize(directory) {
        Ok(real) => real,
        Err(_) => resolve_lenient(directory),
    };
    loop {
        if probe.file_name().is_some_and(|name| name == ".git") {
            return true;
        }
        if probe.join(".git").exists() {
            return true;
        }
        let Some(parent) = probe.parent() else {
            break;
        };
        if parent == probe {
            break;
        }
        let next = parent.to_path_buf();
        probe = next;
    }
    run_git(&["rev-parse", "--show-toplevel"], directory, None).is_some_and(|output| {
        output.status.success() && !String::from_utf8_lossy(&output.stdout).trim().is_empty()
    })
}

/// Write the evidence JSON, refusing existing paths, symlinks and worktrees.
fn write_evidence(path: &Path, data: &Value) -> i32 {
    if let Some(problem) = evidence_path_problem(path) {
        eprintln!(
            "collect_sessions: refusing to write evidence ({problem}): {}",
            path.display()
        );
        return 2;
    }
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(no_follow_flag());
    }
    let mut file = match options.open(path) {
        Ok(file) => file,
        Err(error) => {
            eprintln!(
                "collect_sessions: cannot create evidence file {}: {error}",
                path.display()
            );
            return 2;
        }
    };
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Err(error) = file.set_permissions(std::fs::Permissions::from_mode(0o600)) {
            eprintln!(
                "collect_sessions: cannot write evidence file {}: {error}",
                path.display()
            );
            return 2;
        }
    }
    let mut payload = match serde_json::to_string_pretty(data) {
        Ok(payload) => payload,
        Err(error) => {
            eprintln!(
                "collect_sessions: cannot write evidence file {}: {error}",
                path.display()
            );
            return 2;
        }
    };
    payload.push('\n');
    if let Err(error) = file.write_all(payload.as_bytes()) {
        eprintln!(
            "collect_sessions: cannot write evidence file {}: {error}",
            path.display()
        );
        return 2;
    }
    0
}

/// `O_NOFOLLOW` for the current Unix platform.
///
/// Linux aarch64/arm/powerpc define `O_NOFOLLOW` as `0o400000`, the same value
/// that is `O_DIRECT` there, so the constant must come from libc rather than a
/// hard-coded number.
#[cfg(unix)]
fn no_follow_flag() -> i32 {
    libc::O_NOFOLLOW
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn no_follow_flag_is_o_nofollow_and_refuses_a_symlink() {
        let temp = tempfile::tempdir().expect("tempdir");
        let target = temp.path().join("target.json");
        std::fs::write(&target, "x").expect("target file");
        let link = temp.path().join("link.json");
        std::os::unix::fs::symlink(&target, &link).expect("symlink");

        assert_eq!(no_follow_flag(), libc::O_NOFOLLOW);

        use std::os::unix::fs::OpenOptionsExt;
        let error = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(no_follow_flag())
            .open(&link)
            .expect_err("O_NOFOLLOW must refuse to follow the symlink");
        assert_eq!(error.raw_os_error(), Some(libc::ELOOP), "{error}");

        std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(no_follow_flag())
            .open(&target)
            .expect("a regular file must still open");
    }
}
