//! Integration tests for the `collect` subcommand.
//!
//! Every test drives the real binary with an isolated HOME, OpenCode data dir
//! and Claude config dir, mirroring the Python collector's fixtures. A final
//! group runs the Python collector on the same fixtures and diffs the results.

use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use ds_agent_docs::collect::classify::is_correction;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use tempfile::TempDir;

/// Fixtures of record for the correction marker (ten corrections, ten controls).
const CORRECTIONS: [&str; 10] = [
    "No, use bun here, not npm.",
    "Don't edit the generated client by hand.",
    "That's wrong, the config lives in the root folder.",
    "Stop running the full suite for a one-line change.",
    "I told you to keep the migration separate.",
    "Never push directly to the release branch.",
    "You should have run the formatter before committing.",
    "Not like that, put the helper next to its caller.",
    "Use the shared logger instead of console.log.",
    "You forgot to update the lockfile again.",
];

const NON_CORRECTIONS: [&str; 10] = [
    "Should we add a retry to the upload step?",
    "No problem, thanks for the update.",
    "Why does the build never finish on CI?",
    "Add a guard so the job doesn't fail on empty input.",
    "Can you always show the total in the footer?",
    "What should the default timeout be?",
    "Please remember the last filter the user chose.",
    "Write a test that checks the stop button works.",
    "The wrong-password message needs better copy.",
    "Instead of a modal, what would a drawer look like?",
];

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_ds-agent-docs")
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after the epoch")
        .as_secs_f64()
}

fn exit_code(output: &Output) -> i32 {
    output.status.code().expect("collector exited normally")
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn encode_name(path: &Path) -> String {
    path.to_string_lossy()
        .chars()
        .map(|letter| {
            if letter.is_ascii_alphanumeric() {
                letter
            } else {
                '-'
            }
        })
        .collect()
}

fn user_record(text: &str, cwd: &Path) -> Value {
    json!({
        "cwd": cwd,
        "type": "user",
        "message": {"role": "user", "content": text},
    })
}

fn assistant_record(text: &str, cwd: &Path) -> Value {
    json!({
        "cwd": cwd,
        "type": "assistant",
        "message": {"role": "assistant", "content": text},
    })
}

fn set_mtime(path: &Path, seconds: f64) {
    let when = UNIX_EPOCH + Duration::from_secs_f64(seconds.max(0.0));
    let file = fs::OpenOptions::new()
        .write(true)
        .open(path)
        .expect("open fixture file");
    file.set_times(fs::FileTimes::new().set_modified(when))
        .expect("set fixture mtime");
}

fn write_records(path: &Path, records: &[Value], mtime: Option<f64>) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("fixture parent dir");
    }
    let mut body = String::new();
    for record in records {
        body.push_str(&record.to_string());
        body.push('\n');
    }
    fs::write(path, body).expect("write fixture transcript");
    if let Some(seconds) = mtime {
        set_mtime(path, seconds);
    }
}

fn write_raw_lines(path: &Path, lines: &[&str], mtime: Option<f64>) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("fixture parent dir");
    }
    let mut body = lines.join("\n");
    body.push('\n');
    fs::write(path, body).expect("write raw fixture");
    if let Some(seconds) = mtime {
        set_mtime(path, seconds);
    }
}

/// An isolated collector environment: home, data dir, Claude config, repo root.
struct Fixture {
    _tmp: TempDir,
    base: PathBuf,
    home: PathBuf,
    data: PathBuf,
    claude: PathBuf,
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let tmp = tempfile::tempdir().expect("temp dir");
        let base = fs::canonicalize(tmp.path()).expect("canonical temp dir");
        let home = base.join("home");
        let data = base.join("data");
        let claude = base.join("claude");
        let root = base.join("repo");
        for path in [&home, &data, &claude, &root] {
            fs::create_dir_all(path).expect("fixture directory");
        }
        Self {
            _tmp: tmp,
            base,
            home,
            data,
            claude,
            root,
        }
    }

    fn apply_env(&self, command: &mut Command) {
        command
            .env("HOME", &self.home)
            .env("XDG_DATA_HOME", &self.data)
            .env("CLAUDE_CONFIG_DIR", &self.claude);
        for key in [
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        ] {
            command.env_remove(key);
        }
    }

    fn run(&self, args: &[&str]) -> Output {
        let mut command = Command::new(binary());
        self.apply_env(&mut command);
        for value in args {
            command.arg(value);
        }
        command.output().expect("collector runs")
    }

    fn run_collect(&self, extra: &[&str]) -> Output {
        let root = self.root.to_str().expect("utf-8 root");
        let mut args: Vec<&str> = vec!["collect", "--repo", root, "--days", "60"];
        args.extend_from_slice(extra);
        self.run(&args)
    }

    fn project_dir(&self, cwd: &Path) -> PathBuf {
        self.claude.join("projects").join(encode_name(cwd))
    }

    fn write_session(
        &self,
        cwd: &Path,
        name: &str,
        records: &[Value],
        mtime: Option<f64>,
    ) -> PathBuf {
        let path = self.project_dir(cwd).join(name);
        write_records(&path, records, mtime);
        path
    }

    fn write_raw_session(
        &self,
        cwd: &Path,
        name: &str,
        lines: &[&str],
        mtime: Option<f64>,
    ) -> PathBuf {
        let path = self.project_dir(cwd).join(name);
        write_raw_lines(&path, lines, mtime);
        path
    }

    fn write_zstd_session(
        &self,
        cwd: &Path,
        name: &str,
        records: &[Value],
        mtime: Option<f64>,
    ) -> PathBuf {
        let directory = self.project_dir(cwd);
        fs::create_dir_all(&directory).expect("project dir");
        let path = directory.join(name);
        let mut body = String::new();
        for record in records {
            body.push_str(&record.to_string());
            body.push('\n');
        }
        let compressed = zstd::encode_all(body.as_bytes(), 3).expect("compress transcript");
        fs::write(&path, compressed).expect("write compressed transcript");
        if let Some(seconds) = mtime {
            set_mtime(&path, seconds);
        }
        path
    }

    fn write_document_session(
        &self,
        cwd: &Path,
        name: &str,
        records: &[Value],
        mtime: Option<f64>,
    ) -> PathBuf {
        let path = self.project_dir(cwd).join(name);
        write_records(&path, &[Value::Array(records.to_vec())], mtime);
        path
    }

    fn opencode_db(&self) -> PathBuf {
        self.data.join("opencode").join("opencode.db")
    }

    fn database(&self) -> PathBuf {
        let path = self.opencode_db();
        fs::create_dir_all(path.parent().expect("db parent")).expect("db dir");
        path
    }

    fn evidence_path(&self, name: &str) -> PathBuf {
        self.base.join(name)
    }

    fn run_collect_with_evidence(&self, evidence: &Path) -> Output {
        let evidence = evidence.to_str().expect("utf-8 evidence path");
        self.run_collect(&["--evidence-out", evidence])
    }
}

fn create_standard_schema(connection: &Connection) {
    connection
        .execute_batch(
            "CREATE TABLE project (id text PRIMARY KEY);
             INSERT INTO project VALUES ('project-1');
             CREATE TABLE session_v2 (
                 id text PRIMARY KEY, project_id text, slug text, directory text,
                 fork_session_id text, parent_id text, time_created integer,
                 time_updated integer);
             CREATE TABLE session_message (
                 id text PRIMARY KEY, session_id text, type text, seq integer,
                 time_created integer, time_updated integer, data text);",
        )
        .expect("standard schema");
}

fn make_standard_database(fixture: &Fixture) -> Connection {
    let connection = Connection::open(fixture.database()).expect("open sqlite");
    create_standard_schema(&connection);
    connection
}

fn insert_session(connection: &Connection, id: &str, directory: Option<&str>, age_days: f64) {
    let stamp = ((now_secs() - age_days * 86400.0) * 1000.0) as i64;
    connection
        .execute(
            "INSERT INTO session_v2 VALUES (?, 'project-1', ?, ?, NULL, NULL, ?, ?)",
            params![id, id, directory, stamp, stamp],
        )
        .expect("insert session");
}

fn insert_message(connection: &Connection, session: &str, seq: i64, kind: &str, data: &Value) {
    let stamp = (now_secs() * 1000.0) as i64;
    connection
        .execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![
                format!("{session}-{seq}"),
                session,
                kind,
                seq,
                stamp,
                stamp,
                data.to_string()
            ],
        )
        .expect("insert message");
}

fn opencode_user(text: &str) -> Value {
    json!({"text": text})
}

fn read_evidence(path: &Path) -> Value {
    let raw = fs::read_to_string(path).expect("read evidence");
    serde_json::from_str(&raw).expect("parse evidence")
}

fn comparable_evidence(mut value: Value) -> Value {
    if let Some(object) = value.as_object_mut() {
        object.insert("generated_at".to_string(), Value::String(String::new()));
    }
    value
}

fn git(cwd: &Path, args: &[&str]) {
    let output = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .env("GIT_AUTHOR_NAME", "fixture")
        .env("GIT_AUTHOR_EMAIL", "fixture@example.test")
        .env("GIT_COMMITTER_NAME", "fixture")
        .env("GIT_COMMITTER_EMAIL", "fixture@example.test")
        .output()
        .expect("git runs");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn init_git_repo(root: &Path) {
    git(root, &["init", "-q", "-b", "main"]);
    fs::write(root.join("README.md"), "fixture\n").expect("readme");
    git(root, &["add", "."]);
    git(root, &["commit", "-qm", "init"]);
}

fn python_script() -> Option<PathBuf> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let script = manifest
        .parent()?
        .parent()?
        .join("skills")
        .join("ds-agent-docs")
        .join("scripts")
        .join("collect_sessions.py");
    if !script.is_file() {
        return None;
    }
    match Command::new("python3").arg("-c").arg("import sys").output() {
        Ok(output) if output.status.success() => Some(script),
        _ => None,
    }
}

fn run_python(script: &Path, fixture: &Fixture, extra: &[&str]) -> Output {
    let mut command = Command::new("python3");
    command
        .arg(script)
        .env("HOME", &fixture.home)
        .env("XDG_DATA_HOME", &fixture.data)
        .env("CLAUDE_CONFIG_DIR", &fixture.claude)
        .arg("--repo")
        .arg(&fixture.root)
        .arg("--days")
        .arg("60");
    for value in extra {
        command.arg(value);
    }
    command.output().expect("python collector runs")
}

fn digest_labels(output: &Output) -> Vec<String> {
    stdout(output)
        .lines()
        .filter(|line| line.starts_with("## "))
        .map(|line| {
            line.rsplit(" \u{b7} ")
                .next()
                .unwrap_or_default()
                .to_string()
        })
        .collect()
}

#[test]
fn committed_corrections_are_flagged_and_controls_are_not() {
    let flagged: Vec<&str> = CORRECTIONS
        .iter()
        .copied()
        .filter(|text| is_correction(text))
        .collect();
    assert_eq!(
        flagged.len(),
        CORRECTIONS.len(),
        "every committed correction must be flagged: {flagged:?}"
    );
    let false_positives: Vec<&str> = NON_CORRECTIONS
        .iter()
        .copied()
        .filter(|text| is_correction(text))
        .collect();
    assert!(
        false_positives.is_empty(),
        "controls must not be flagged: {false_positives:?}"
    );
}

/// The correction marker is diffed against Python for every fixture string.
#[test]
fn correction_marker_matches_python_for_every_fixture() {
    let Some(script) = python_script() else {
        eprintln!("python3 or the collector script is missing; skipping parity check");
        return;
    };
    let mut texts: Vec<&str> = CORRECTIONS.to_vec();
    texts.extend_from_slice(&NON_CORRECTIONS);
    let payload = serde_json::to_string(&texts).expect("serialize fixtures");
    let program = "import importlib.util, json, sys\n\
        spec = importlib.util.spec_from_file_location('c', sys.argv[1])\n\
        module = importlib.util.module_from_spec(spec)\n\
        spec.loader.exec_module(module)\n\
        texts = json.load(sys.stdin)\n\
        print(json.dumps([module.is_correction(t) for t in texts]))\n";
    let mut child = Command::new("python3")
        .arg("-c")
        .arg(program)
        .arg(script)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("spawn python");
    {
        use std::io::Write as _;
        child
            .stdin
            .as_mut()
            .expect("python stdin")
            .write_all(payload.as_bytes())
            .expect("write fixtures");
    }
    let output = child.wait_with_output().expect("python finishes");
    assert!(output.status.success(), "python failed");
    let expected: Vec<bool> = serde_json::from_slice(&output.stdout).expect("parse python result");
    let actual: Vec<bool> = texts.iter().map(|text| is_correction(text)).collect();
    assert_eq!(actual, expected, "correction marker diverged from Python");
}

#[test]
fn digest_reads_jsonl_zstd_and_document_transcripts() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "one.jsonl",
        &[user_record("typed first", &root)],
        Some(now - 86400.0),
    );
    fixture.write_zstd_session(
        &root,
        "two.jsonl.zst",
        &[user_record("typed compressed", &root)],
        Some(now - 2.0 * 86400.0),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    for needle in [
        "\u{b7} claude-code \u{b7} one.jsonl",
        "\u{b7} claude-code \u{b7} two.jsonl.zst",
        "typed first",
        "typed compressed",
    ] {
        assert!(text.contains(needle), "missing {needle:?} in:\n{text}");
    }
}

#[test]
fn sessions_outside_the_window_are_not_scanned() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "old.jsonl",
        &[user_record("old message that must not appear", &root)],
        Some(now - 400.0 * 86400.0),
    );
    fixture.write_session(
        &root,
        "fresh.jsonl",
        &[user_record("fresh message appears", &root)],
        Some(now - 86400.0),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stdout(&output).contains("fresh message appears"));
    assert!(!stdout(&output).contains("old message that must not appear"));
}

#[test]
fn extra_dirs_are_scanned_recursively_and_filtered_by_cwd() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let elsewhere = fixture.base.join("another-repo");
    fs::create_dir_all(&elsewhere).expect("neighbour");
    let extra = fixture.base.join("extra");
    let now = now_secs();
    write_records(
        &extra.join("nested").join("inside.jsonl"),
        &[user_record("inside extra message", &root)],
        Some(now - 86400.0),
    );
    write_records(
        &extra.join("nested").join("outside.jsonl"),
        &[user_record("outside extra message", &elsewhere)],
        Some(now - 86400.0),
    );
    let body = format!("{}\n", user_record("deep compressed extra message", &root));
    let compressed = zstd::encode_all(body.as_bytes(), 3).expect("compress");
    let deep = extra.join("nested").join("deeper").join("deep.jsonl.zst");
    fs::create_dir_all(deep.parent().expect("deep parent")).expect("deep dir");
    fs::write(&deep, compressed).expect("write deep");
    set_mtime(&deep, now - 2.0 * 86400.0);
    write_records(
        &extra.join("nested").join("whole.json"),
        &[user_record("document form message", &root)],
        Some(now - 3.0 * 86400.0),
    );
    let extra_arg = extra.to_str().expect("utf-8 extra dir");
    let output = fixture.run_collect(&["--extra-dir", extra_arg]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    assert!(text.contains("inside extra message"), "{text}");
    assert!(text.contains("deep compressed extra message"), "{text}");
    assert!(text.contains("document form message"), "{text}");
    assert!(!text.contains("outside extra message"), "{text}");
    assert!(text.contains("\u{b7} extra \u{b7} inside.jsonl"), "{text}");
}

#[test]
fn opencode_immutable_read_leaves_the_store_untouched() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let connection = make_standard_database(&fixture);
    insert_session(
        &connection,
        "inside-session",
        Some(root.to_str().unwrap()),
        0.0,
    );
    insert_message(
        &connection,
        "inside-session",
        1,
        "user",
        &opencode_user("don't do that again; token=SECRET-TOKEN-VALUE"),
    );
    insert_message(
        &connection,
        "inside-session",
        2,
        "assistant",
        &json!({"content": [{"type": "tool", "name": "bash", "state": {
            "status": "error",
            "error": {"type": "permission.rejected", "message": "Permission denied: shell"},
        }}]}),
    );
    insert_session(
        &connection,
        "outside-session",
        Some(fixture.base.join("elsewhere").to_str().unwrap()),
        0.0,
    );
    insert_session(
        &connection,
        "old-session",
        Some(root.to_str().unwrap()),
        400.0,
    );
    insert_session(&connection, "empty-dir", Some(""), 0.0);
    insert_session(&connection, "null-dir", None, 0.0);
    drop(connection);

    let db = fixture.opencode_db();
    let before_bytes = fs::read(&db).expect("read db bytes");
    let before_files = directory_entries(db.parent().expect("db dir"));
    let evidence = fixture.evidence_path("evidence.json");
    let output = fixture.run_collect_with_evidence(&evidence);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert_eq!(fs::read(&db).expect("re-read db"), before_bytes);
    assert_eq!(
        directory_entries(db.parent().expect("db dir")),
        before_files,
        "the read must not create journal or shared-memory files"
    );
    let text = stdout(&output);
    assert!(
        text.contains("\u{b7} opencode \u{b7} inside-session"),
        "{text}"
    );
    assert!(text.contains("\u{2691}"), "{text}");
    assert!(text.contains("\u{2717} error"), "{text}");
    assert!(
        text.contains("permission.rejected: Permission denied: shell"),
        "{text}"
    );
    assert!(text.contains("[REDACTED]"), "{text}");
    assert!(!text.contains("SECRET-TOKEN-VALUE"), "{text}");
    let payload = read_evidence(&evidence);
    assert_eq!(payload["counts"]["opencode_v1_only"], 0);
    let ids: Vec<String> = payload["sessions"]
        .as_array()
        .expect("sessions array")
        .iter()
        .map(|session| session["id"].as_str().unwrap_or_default().to_string())
        .collect();
    assert!(
        ids.contains(&"opencode:inside-session".to_string()),
        "{ids:?}"
    );
    assert!(
        !ids.iter().any(|id| id.contains("outside-session")),
        "{ids:?}"
    );
    assert!(!ids.iter().any(|id| id.contains("empty-dir")), "{ids:?}");
    assert!(!ids.iter().any(|id| id.contains("null-dir")), "{ids:?}");
}

fn directory_entries(directory: &Path) -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(directory)
        .expect("read directory")
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    names
}

#[test]
fn opencode_live_wal_database_with_a_writer_is_read() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let setup = make_standard_database(&fixture);
    drop(setup);
    let path = fixture.opencode_db();
    let writer = Connection::open(&path).expect("writer");
    writer
        .execute_batch("PRAGMA journal_mode=WAL;")
        .expect("wal mode");
    insert_session(&writer, "live-session", Some(root.to_str().unwrap()), 0.0);
    insert_message(
        &writer,
        "live-session",
        1,
        "user",
        &opencode_user("live wal session message"),
    );
    let wal = PathBuf::from(format!("{}-wal", path.display()));
    let shm = PathBuf::from(format!("{}-shm", path.display()));
    assert!(wal.exists(), "the fixture has a pending write-ahead log");
    assert!(shm.exists(), "the writer holds the shared-memory file");
    let before_files = directory_entries(path.parent().expect("db dir"));
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    assert!(
        text.contains("\u{b7} opencode \u{b7} live-session"),
        "{text}"
    );
    assert!(text.contains("live wal session message"), "{text}");
    assert_eq!(
        directory_entries(path.parent().expect("db dir")),
        before_files
    );
    drop(writer);
}

#[test]
fn opencode_wal_without_shared_memory_is_skipped_with_a_note() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "fixture.jsonl",
        &[user_record("hello from claude code", &root)],
        Some(now - 86400.0),
    );
    let connection = make_standard_database(&fixture);
    insert_session(&connection, "wal-only", Some(root.to_str().unwrap()), 0.0);
    insert_message(
        &connection,
        "wal-only",
        1,
        "user",
        &opencode_user("wal only message must not appear"),
    );
    drop(connection);
    let path = fixture.opencode_db();
    fs::write(format!("{}-wal", path.display()), b"").expect("write wal marker");
    assert!(!path.with_extension("db-shm").exists());
    let before_files = directory_entries(path.parent().expect("db dir"));
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stderr(&output).contains("WAL"), "{}", stderr(&output));
    let text = stdout(&output);
    assert!(text.contains("hello from claude code"), "{text}");
    assert!(!text.contains("wal only message"), "{text}");
    assert_eq!(
        directory_entries(path.parent().expect("db dir")),
        before_files
    );
}

#[test]
fn opencode_corrupt_database_still_prints_claude_sessions() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "fixture.jsonl",
        &[user_record("hello from claude code", &root)],
        Some(now - 86400.0),
    );
    let path = fixture.database();
    fs::write(&path, b"this is not a sqlite database").expect("corrupt db");
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stderr(&output).contains("OpenCode"), "{}", stderr(&output));
    assert!(stdout(&output).contains("hello from claude code"));

    fs::remove_file(&path).expect("remove db");
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stderr(&output).contains("no OpenCode database"));
    assert!(stdout(&output).contains("hello from claude code"));
}

#[test]
fn opencode_v1_only_sessions_are_counted_without_reading_message_or_part() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let connection = make_standard_database(&fixture);
    insert_session(&connection, "v2-session", Some(root.to_str().unwrap()), 0.0);
    insert_message(
        &connection,
        "v2-session",
        1,
        "user",
        &opencode_user("v2 session message"),
    );
    connection
        .execute_batch(
            "CREATE TABLE session (id text PRIMARY KEY, directory text, time_updated integer);
             CREATE VIEW message AS SELECT * FROM missing_message_table;
             CREATE VIEW part AS SELECT * FROM missing_part_table;",
        )
        .expect("v1 schema");
    let stamp = (now_secs() * 1000.0) as i64;
    let root_text = root.to_str().expect("utf-8 root");
    let elsewhere = fixture.base.join("elsewhere");
    let elsewhere_text = elsewhere.to_str().expect("utf-8 elsewhere");
    for (id, directory, age) in [
        ("v1-session", root_text, 0.0),
        ("v1-old", root_text, 400.0),
        ("v1-elsewhere", elsewhere_text, 0.0),
    ] {
        let when = stamp - (age * 86400.0 * 1000.0) as i64;
        connection
            .execute(
                "INSERT INTO session VALUES (?, ?, ?)",
                params![id, directory, when],
            )
            .expect("insert v1 session");
    }
    drop(connection);
    let evidence = fixture.evidence_path("evidence.json");
    let output = fixture.run_collect_with_evidence(&evidence);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stdout(&output).contains("v2 session message"));
    let payload = read_evidence(&evidence);
    assert_eq!(payload["counts"]["opencode_v1_only"], 1);
}

#[test]
fn opencode_child_sessions_are_excluded() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let connection = make_standard_database(&fixture);
    for id in ["parent-session", "child-session"] {
        insert_session(&connection, id, Some(root.to_str().unwrap()), 0.0);
        insert_message(
            &connection,
            id,
            1,
            "user",
            &opencode_user(&format!("{id} message")),
        );
    }
    connection
        .execute(
            "UPDATE session_v2 SET parent_id = ? WHERE id = ?",
            params!["parent-session", "child-session"],
        )
        .expect("mark child");
    drop(connection);
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    assert!(text.contains("parent-session message"), "{text}");
    assert!(!text.contains("child-session message"), "{text}");
}

#[test]
fn opencode_forks_share_the_fork_group() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let connection = make_standard_database(&fixture);
    for id in ["origin-session", "branch-session"] {
        insert_session(&connection, id, Some(root.to_str().unwrap()), 0.0);
        insert_message(
            &connection,
            id,
            1,
            "user",
            &opencode_user(&format!("{id} message")),
        );
    }
    connection
        .execute(
            "UPDATE session_v2 SET fork_session_id = ? WHERE id = ?",
            params!["origin-session", "branch-session"],
        )
        .expect("mark fork");
    drop(connection);
    let evidence = fixture.evidence_path("evidence.json");
    let output = fixture.run_collect_with_evidence(&evidence);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let payload = read_evidence(&evidence);
    let groups: std::collections::HashMap<String, String> = payload["sessions"]
        .as_array()
        .expect("sessions")
        .iter()
        .map(|session| {
            (
                session["id"].as_str().unwrap_or_default().to_string(),
                session["group"].as_str().unwrap_or_default().to_string(),
            )
        })
        .collect();
    assert_eq!(
        groups.get("opencode:branch-session"),
        Some(&"origin-session".to_string())
    );
    assert_eq!(
        groups.get("opencode:origin-session"),
        Some(&"origin-session".to_string())
    );
}

#[test]
fn opencode_missing_tables_and_parent_column_are_format_drift() {
    let fixture = Fixture::new();
    let path = fixture.database();
    let connection = Connection::open(&path).expect("open sqlite");
    connection
        .execute_batch("CREATE TABLE project (id text PRIMARY KEY)")
        .expect("project table");
    drop(connection);
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(
        stdout(&output).contains("FORMAT DRIFT: opencode"),
        "{}",
        stdout(&output)
    );
    let strict = fixture.run_collect(&["--strict"]);
    assert_eq!(exit_code(&strict), 3, "{}", stderr(&strict));

    fs::remove_file(&path).expect("remove db");
    let connection = Connection::open(&path).expect("open second sqlite");
    connection
        .execute_batch(
            "CREATE TABLE session_v2 (
                 id text PRIMARY KEY, project_id text, slug text, directory text,
                 fork_session_id text, time_created integer, time_updated integer);
             CREATE TABLE session_message (
                 id text PRIMARY KEY, session_id text, type text, seq integer,
                 time_created integer, time_updated integer, data text);",
        )
        .expect("schema without parent_id");
    let stamp = (now_secs() * 1000.0) as i64;
    connection
        .execute(
            "INSERT INTO session_v2 VALUES (?, 'project-1', ?, ?, NULL, ?, ?)",
            params![
                "orphan-session",
                "orphan-session",
                fixture.root.to_str().expect("utf-8 root"),
                stamp,
                stamp
            ],
        )
        .expect("insert orphan");
    connection
        .execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![
                "orphan-1",
                "orphan-session",
                "user",
                1,
                stamp,
                stamp,
                opencode_user("parentless message").to_string()
            ],
        )
        .expect("insert orphan message");
    drop(connection);
    let output = fixture.run_collect(&[]);
    assert!(stdout(&output).contains("FORMAT DRIFT: opencode"));
    assert!(!stdout(&output).contains("parentless message"));
}

#[test]
fn equal_mtime_sessions_keep_a_deterministic_order_across_runs() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let names = ["delta", "alpha", "charlie", "bravo", "echo"];
    for name in names {
        fixture.write_session(
            &root,
            &format!("{name}.jsonl"),
            &[user_record(&format!("body of {name}"), &root)],
            Some(now),
        );
    }
    let mut orders: Vec<Vec<String>> = Vec::new();
    for index in 0..3 {
        let evidence = fixture.evidence_path(&format!("evidence-{index}.json"));
        let output = fixture.run_collect_with_evidence(&evidence);
        assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
        let payload = read_evidence(&evidence);
        let ids: Vec<String> = payload["sessions"]
            .as_array()
            .expect("sessions")
            .iter()
            .map(|session| session["id"].as_str().unwrap_or_default().to_string())
            .collect();
        orders.push(ids);
    }
    let mut sorted = names;
    sorted.sort_unstable();
    let expected: Vec<String> = sorted
        .iter()
        .map(|name| format!("claude-code:{name}.jsonl"))
        .collect();
    assert_eq!(orders[0], expected);
    assert_eq!(orders[1], orders[0]);
    assert_eq!(orders[2], orders[0]);
}

#[test]
fn weekly_round_robin_interleaves_one_session_per_bucket() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    for (age, name) in [
        (0.0, "week0-a"),
        (1.0, "week0-b"),
        (8.0, "week1-a"),
        (9.0, "week1-b"),
        (15.0, "week2-a"),
    ] {
        fixture.write_session(
            &root,
            &format!("{name}.jsonl"),
            &[user_record(&format!("body {name}"), &root)],
            Some(now - age * 86400.0),
        );
    }
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let labels = digest_labels(&output);
    assert_eq!(
        labels,
        vec![
            "week0-a.jsonl".to_string(),
            "week1-a.jsonl".to_string(),
            "week2-a.jsonl".to_string(),
            "week0-b.jsonl".to_string(),
            "week1-b.jsonl".to_string(),
        ],
        "{labels:?}"
    );
}

#[test]
fn interactive_sessions_come_before_headless_ones() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "headless.jsonl",
        &[
            user_record("headless body", &root),
            json!({
                "cwd": root,
                "type": "user",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "boot"},
            }),
        ],
        Some(now),
    );
    fixture.write_session(
        &root,
        "interactive.jsonl",
        &[user_record("interactive body", &root)],
        Some(now - 10.0),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let labels = digest_labels(&output);
    assert_eq!(
        labels.first().map(String::as_str),
        Some("interactive.jsonl")
    );
}

#[test]
fn machine_authored_and_self_sessions_are_excluded() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let record = |text: &str, fields: Value| {
        let mut value = user_record(text, &root);
        value
            .as_object_mut()
            .expect("object record")
            .extend(fields.as_object().expect("field object").clone());
        value
    };
    let cases = [
        (
            "meta.jsonl",
            json!({"isMeta": true}),
            "machine text via meta",
        ),
        (
            "origin.jsonl",
            json!({"origin": {"kind": "hook"}}),
            "machine text via origin",
        ),
        (
            "entrypoint.jsonl",
            json!({"entrypoint": "sdk-cli"}),
            "machine text via entrypoint",
        ),
        (
            "prompt.jsonl",
            json!({"promptSource": "suggestion"}),
            "machine text via prompt",
        ),
        (
            "kind.jsonl",
            json!({"sessionKind": "bg"}),
            "machine text via kind",
        ),
    ];
    for (name, fields, text) in cases {
        let records = [
            record(text, fields),
            user_record("typed message survives", &root),
        ];
        fixture.write_session(&root, name, &records, Some(now));
    }
    fixture.write_session(
        &root,
        "hook.jsonl",
        &[
            user_record("Stop hook feedback: machine text from a hook", &root),
            user_record("typed message survives", &root),
        ],
        Some(now),
    );
    fixture.write_session(
        &root,
        "pasted.jsonl",
        &[user_record(
            "keep before <pasted_content>hidden paste content</pasted_content> keep after",
            &root,
        )],
        Some(now),
    );
    fixture.write_session(
        &root,
        "self.jsonl",
        &[
            user_record(
                "<!-- backpass:self-session --> typed in self session",
                &root,
            ),
            user_record("self session tail must not appear", &root),
        ],
        Some(now),
    );
    fixture.write_session(
        &root,
        "tool.jsonl",
        &[
            json!({
                "cwd": root,
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "text", "text": "machine text beside a tool result"},
                    {"type": "tool_result", "content": "ok"},
                ]},
            }),
            user_record("typed message survives", &root),
        ],
        Some(now),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    for excluded in [
        "machine text via meta",
        "machine text via origin",
        "machine text via entrypoint",
        "machine text via prompt",
        "machine text via kind",
        "machine text from a hook",
        "machine text beside a tool result",
        "hidden paste content",
        "typed in self session",
        "self session tail must not appear",
    ] {
        assert!(!text.contains(excluded), "leaked {excluded:?}:\n{text}");
    }
    assert!(text.contains("keep before"), "{text}");
    assert!(text.contains("keep after"), "{text}");
    assert!(text.contains("typed message survives"), "{text}");
}

#[test]
fn format_drift_needs_twenty_records_and_strict_exits_three() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let nineteen: Vec<String> = (0..19).map(|index| format!("not json {index}")).collect();
    let lines: Vec<&str> = nineteen.iter().map(String::as_str).collect();
    let path = fixture.write_raw_session(&root, "junk.jsonl", &lines, Some(now));
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(!stdout(&output).contains("FORMAT DRIFT"));

    let mut more = lines.clone();
    more.push("not json 19");
    write_raw_lines(&path, &more, Some(now));
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stdout(&output).contains("FORMAT DRIFT: claude-code"));
    let strict = fixture.run_collect(&["--strict"]);
    assert_eq!(exit_code(&strict), 3, "{}", stderr(&strict));
    assert!(stdout(&strict).contains("FORMAT DRIFT: claude-code"));
}

#[test]
fn blank_lines_are_not_counted_and_malformed_lines_are() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let mut lines: Vec<String> = (0..10)
        .map(|index| user_record(&format!("typed body {index}"), &root).to_string())
        .collect();
    for _ in 0..10 {
        lines.push(String::new());
        lines.push("   ".to_string());
    }
    let refs: Vec<&str> = lines.iter().map(String::as_str).collect();
    let path = fixture.write_raw_session(&root, "mixed.jsonl", &refs, Some(now));
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(!stdout(&output).contains("FORMAT DRIFT"));

    let mut with_junk: Vec<String> = (0..11).map(|index| format!("not json {index}")).collect();
    with_junk.extend(lines);
    let refs: Vec<&str> = with_junk.iter().map(String::as_str).collect();
    write_raw_lines(&path, &refs, Some(now));
    let output = fixture.run_collect(&[]);
    assert!(stdout(&output).contains("FORMAT DRIFT: claude-code"));
}

#[test]
fn evidence_schema_and_mode_under_a_permissive_umask() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let long_text = format!("long evidence message {}", "y".repeat(400));
    fixture.write_session(
        &root,
        "evidence.jsonl",
        &[
            user_record("short typed message", &root),
            user_record(&long_text, &root),
        ],
        Some(now),
    );
    let evidence = fixture.evidence_path("evidence.json");
    let script = "umask 0; exec \"$@\"";
    let root_text = fixture.root.to_str().expect("utf-8 root");
    let evidence_text = evidence.to_str().expect("utf-8 evidence");
    let mut command = Command::new("sh");
    fixture.apply_env(&mut command);
    let output = command
        .arg("-c")
        .arg(script)
        .arg("sh")
        .arg(binary())
        .arg("collect")
        .arg("--repo")
        .arg(root_text)
        .arg("--days")
        .arg("60")
        .arg("--evidence-out")
        .arg(evidence_text)
        .output()
        .expect("collector under a permissive umask");
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(&evidence)
            .expect("evidence metadata")
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(mode, 0o600, "evidence file mode {mode:o}");
    }
    let payload = read_evidence(&evidence);
    assert_eq!(payload["version"], 1);
    let repo_id = payload["repo_id"].as_str().expect("repo id");
    assert_eq!(repo_id.len(), 64);
    assert!(repo_id.chars().all(|letter| letter.is_ascii_hexdigit()));
    let counts = payload["counts"].as_object().expect("counts");
    let keys: std::collections::HashSet<&str> = counts.keys().map(String::as_str).collect();
    assert_eq!(
        keys,
        std::collections::HashSet::from([
            "total",
            "interactive",
            "headless",
            "excluded",
            "shown",
            "digest_shown",
            "opencode_v1_only",
        ])
    );
    assert_eq!(payload["counts"]["shown"], 1);
    assert!(payload.get("date_range").is_some());
    assert!(payload.get("drift").is_some());
    let session = &payload["sessions"][0];
    assert_eq!(session["id"], "claude-code:evidence.jsonl");
    assert_eq!(session["source"], "claude-code");
    assert_eq!(session["kind"], "interactive");
    assert_eq!(session["group"], "evidence.jsonl");
    let texts: Vec<&str> = session["human"]
        .as_array()
        .expect("human items")
        .iter()
        .filter_map(|item| item["text"].as_str())
        .collect();
    assert!(texts.contains(&long_text.as_str()), "{texts:?}");
    for item in session["human"].as_array().expect("human items") {
        assert!(item.get("correction").is_some());
        assert!(item.get("msg").is_some());
    }
    assert!(session.get("errors").is_some());
}

#[test]
fn evidence_shown_matches_sessions_when_the_digest_truncates() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    for index in 0..3 {
        fixture.write_session(
            &root,
            &format!("long-{index}.jsonl"),
            &[user_record(
                &format!("long evidence message {index} {}", "z".repeat(300)),
                &root,
            )],
            Some(now - index as f64),
        );
    }
    let evidence = fixture.evidence_path("evidence.json");
    let output = fixture.run_collect(&[
        "--evidence-out",
        evidence.to_str().expect("utf-8 evidence"),
        "--max-chars",
        "200",
    ]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let payload = read_evidence(&evidence);
    let shown = payload["counts"]["shown"].as_u64().expect("shown");
    let digest_shown = payload["counts"]["digest_shown"]
        .as_u64()
        .expect("digest shown");
    assert_eq!(
        payload["sessions"].as_array().expect("sessions").len() as u64,
        shown
    );
    assert_eq!(shown, 3);
    assert!(digest_shown < shown, "{digest_shown} < {shown}");
}

#[test]
fn a_block_too_large_for_the_budget_is_skipped() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let big: Vec<Value> = (0..15)
        .map(|index| {
            user_record(
                &format!("BIGSTART message {index} {}", "x".repeat(400)),
                &root,
            )
        })
        .collect();
    fixture.write_session(&root, "big.jsonl", &big, Some(now));
    fixture.write_session(
        &root,
        "small.jsonl",
        &[user_record("small message survives", &root)],
        Some(now - 10.0),
    );
    let output = fixture.run_collect(&["--max-chars", "1500"]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    assert!(text.contains("small message survives"), "{text}");
    assert!(!text.contains("BIGSTART"), "{text}");
}

#[test]
fn counts_and_date_range_are_reported() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "interactive.jsonl",
        &[user_record("interactive body", &root)],
        Some(now),
    );
    fixture.write_session(
        &root,
        "headless.jsonl",
        &[
            user_record("headless body", &root),
            json!({
                "cwd": root,
                "type": "user",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "boot"},
            }),
        ],
        Some(now - 86400.0),
    );
    fixture.write_session(
        &root,
        "excluded.jsonl",
        &[assistant_record("assistant only", &root)],
        Some(now - 172800.0),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    assert!(
        text.contains(
            "3 sessions in last 60 days: 1 interactive, 1 headless, 1 excluded, 2 shown."
        ),
        "{text}"
    );
}

#[test]
fn evidence_refuses_existing_symlinked_and_worktree_paths() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    init_git_repo(&root);
    let now = now_secs();
    fixture.write_session(
        &root,
        "evidence.jsonl",
        &[user_record("typed message survives", &root)],
        Some(now),
    );
    let targets = [
        root.join("evidence.json"),
        root.join(".git").join("evidence.json"),
    ];
    let bridge = fixture.base.join("bridge");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&root, &bridge).expect("bridge symlink");
    for target in &targets {
        let output = fixture.run_collect(&["--evidence-out", target.to_str().expect("utf-8")]);
        assert_eq!(exit_code(&output), 2, "{}", stderr(&output));
        assert!(!target.exists(), "refused target must not appear");
    }
    #[cfg(unix)]
    {
        let target = bridge.join("evidence.json");
        let output = fixture.run_collect(&["--evidence-out", target.to_str().expect("utf-8")]);
        assert_eq!(exit_code(&output), 2, "{}", stderr(&output));
        assert!(!target.exists());
    }

    let existing = fixture.base.join("existing.json");
    fs::write(&existing, "keep me").expect("existing file");
    let output = fixture.run_collect(&["--evidence-out", existing.to_str().expect("utf-8")]);
    assert_eq!(exit_code(&output), 2);
    assert_eq!(
        fs::read_to_string(&existing).expect("read existing"),
        "keep me"
    );

    #[cfg(unix)]
    {
        let link = fixture.base.join("link.json");
        std::os::unix::fs::symlink(fixture.base.join("nowhere.json"), &link)
            .expect("dangling link");
        let output = fixture.run_collect(&["--evidence-out", link.to_str().expect("utf-8")]);
        assert_eq!(exit_code(&output), 2);
        assert!(fs::symlink_metadata(&link).is_ok(), "the link must survive");
    }

    let missing = fixture.base.join("missing-dir").join("evidence.json");
    let output = fixture.run_collect(&["--evidence-out", missing.to_str().expect("utf-8")]);
    assert_eq!(exit_code(&output), 2);
    assert!(stderr(&output).contains("parent directory does not exist"));
    assert!(!missing.exists());
}

#[test]
fn secrets_and_home_paths_are_redacted_in_digest_and_evidence() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    let email = format!("{}{}", "alice", "@example.test");
    let jwt = format!(
        "{}.{}.{}",
        "eyJ".to_string() + &"a".repeat(10),
        "b".repeat(10),
        "c".repeat(10)
    );
    let pem = format!(
        "{}{}\n{}\n{}{}",
        "-----BEGIN ",
        "RSA PRIVATE KEY-----",
        "MIIB".to_string() + &"x".repeat(40),
        "-----END ",
        "RSA PRIVATE KEY-----"
    );
    let home_path = format!("{}{}/alice/private/file.txt", "/", "Users");
    let token = format!("{}={}", "token", "SECRET-TOKEN-VALUE");
    let github_tail = "a".repeat(36);
    let github = format!("{}{}{}", "gh", "p_", github_tail);
    let url = format!("{}user:pw@git.example.test/repo.git", "https://");
    fixture.write_session(
        &root,
        "secrets.jsonl",
        &[
            user_record(&format!("reach me at {email}"), &root),
            user_record(&format!("session {jwt}"), &root),
            user_record(&format!("key {pem}"), &root),
            user_record(&format!("clone {url}"), &root),
            user_record(&format!("path {home_path}"), &root),
            user_record(&token, &root),
            user_record(&format!("push {github}"), &root),
            json!({
                "cwd": root,
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "is_error": true,
                     "content": format!("failed at {home_path} for {email}")},
                ]},
            }),
        ],
        Some(now),
    );
    let evidence = fixture.evidence_path("evidence.json");
    let output = fixture.run_collect_with_evidence(&evidence);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    let payload = read_evidence(&evidence);
    let blob = format!("{text}{payload}");
    assert!(blob.contains("[REDACTED]"), "{blob}");
    for secret in [
        email.as_str(),
        jwt.as_str(),
        "MIIBxxxxxxxx",
        "user:pw",
        "SECRET-TOKEN-VALUE",
        github_tail.as_str(),
        "alice",
    ] {
        assert!(!blob.contains(secret), "leaked {secret:?}:\n{blob}");
    }
}

#[test]
fn non_git_root_keeps_path_inside_matching() {
    let fixture = Fixture::new();
    let inside = fixture.root.join("sub");
    fs::create_dir_all(&inside).expect("inside");
    let elsewhere = fixture.base.join("repo-other");
    fs::create_dir_all(&elsewhere).expect("elsewhere");
    let now = now_secs();
    fixture.write_session(
        &inside,
        "inside.jsonl",
        &[user_record("inside non git message", &inside)],
        Some(now),
    );
    let path = fixture.project_dir(&elsewhere).join("outside.jsonl");
    write_records(
        &path,
        &[user_record("outside non git message", &elsewhere)],
        Some(now),
    );
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    assert!(stdout(&output).contains("inside non git message"));
    assert!(!stdout(&output).contains("outside non git message"));
}

#[test]
fn git_worktrees_are_members_and_siblings_nested_clones_are_not() {
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    init_git_repo(&root);
    let worktree = fixture.base.join("linked");
    git(
        &root,
        &[
            "worktree",
            "add",
            "-q",
            "-b",
            "fixture",
            worktree.to_str().unwrap(),
        ],
    );
    let nested = fixture.base.join("nested");
    git(
        &fixture.base,
        &[
            "clone",
            "-q",
            root.to_str().unwrap(),
            nested.to_str().unwrap(),
        ],
    );
    let deleted = fixture.base.join("deleted");
    git(
        &root,
        &[
            "worktree",
            "add",
            "-q",
            "-b",
            "gone",
            deleted.to_str().unwrap(),
        ],
    );
    git(
        &root,
        &["worktree", "remove", "--force", deleted.to_str().unwrap()],
    );
    let sibling = fixture.base.join("repo-2");
    fs::create_dir_all(&sibling).expect("sibling");
    let now = now_secs();
    let docs = root.join("docs");
    fs::create_dir_all(&docs).expect("docs");
    for (project, cwd, text) in [
        (root.clone(), root.clone(), "message from the main checkout"),
        (
            root.clone(),
            docs.clone(),
            "message from a main subdirectory",
        ),
        (
            worktree.clone(),
            worktree.clone(),
            "message from a linked worktree",
        ),
        (nested.clone(), nested.clone(), "nested clone message"),
        (deleted.clone(), deleted.clone(), "deleted worktree message"),
        (sibling.clone(), sibling.clone(), "prefix sibling message"),
    ] {
        fixture.write_session(
            &project,
            &format!("{}.jsonl", text.replace(' ', "-")),
            &[user_record(text, &cwd)],
            Some(now),
        );
    }
    let output = fixture.run_collect(&[]);
    assert_eq!(exit_code(&output), 0, "{}", stderr(&output));
    let text = stdout(&output);
    for included in [
        "message from the main checkout",
        "message from a main subdirectory",
        "message from a linked worktree",
    ] {
        assert!(text.contains(included), "missing {included:?}:\n{text}");
    }
    for excluded in [
        "nested clone message",
        "deleted worktree message",
        "prefix sibling message",
    ] {
        assert!(!text.contains(excluded), "leaked {excluded:?}:\n{text}");
    }
}

/// Full differential parity: identical fixtures, both collectors, exact diff.
#[test]
fn differential_parity_with_the_python_collector() {
    let Some(script) = python_script() else {
        eprintln!("python3 or the collector script is missing; skipping parity check");
        return;
    };
    let fixture = Fixture::new();
    let root = fixture.root.clone();
    let now = now_secs();
    fixture.write_session(
        &root,
        "week0.jsonl",
        &[
            user_record("typed first message", &root),
            user_record("No, use bun here, not npm.", &root),
            json!({
                "cwd": root,
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "is_error": true, "content": "boom"},
                ]},
            }),
        ],
        Some(now - 3600.0),
    );
    fixture.write_zstd_session(
        &root,
        "week1.jsonl.zst",
        &[user_record("compressed typed message", &root)],
        Some(now - 9.0 * 86400.0),
    );
    fixture.write_document_session(
        &root,
        "document.json",
        &[user_record("document typed message", &root)],
        Some(now - 16.0 * 86400.0),
    );
    fixture.write_session(
        &root,
        "self.jsonl",
        &[user_record(
            "<!-- ds-agent-docs:self-session --> marker",
            &root,
        )],
        Some(now - 2.0 * 86400.0),
    );
    let extra = fixture.base.join("extra");
    write_records(
        &extra.join("nested").join("extra.jsonl"),
        &[user_record("extra typed message", &root)],
        Some(now - 3.0 * 86400.0),
    );

    let connection = make_standard_database(&fixture);
    insert_session(
        &connection,
        "opencode-parent",
        Some(root.to_str().unwrap()),
        0.0,
    );
    insert_message(
        &connection,
        "opencode-parent",
        1,
        "user",
        &opencode_user("opencode typed message with token=SECRET-TOKEN-VALUE"),
    );
    insert_message(
        &connection,
        "opencode-parent",
        2,
        "assistant",
        &json!({"content": [{"type": "tool", "name": "bash", "state": {
            "status": "error",
            "error": {"type": "permission.rejected", "message": "Permission denied"},
        }}]}),
    );
    insert_session(
        &connection,
        "opencode-child",
        Some(root.to_str().unwrap()),
        0.0,
    );
    insert_message(
        &connection,
        "opencode-child",
        1,
        "user",
        &opencode_user("child message must not show"),
    );
    connection
        .execute(
            "UPDATE session_v2 SET parent_id = ? WHERE id = ?",
            params!["opencode-parent", "opencode-child"],
        )
        .expect("mark child");
    connection
        .execute(
            "UPDATE session_v2 SET fork_session_id = ? WHERE id = ?",
            params!["opencode-parent", "opencode-child"],
        )
        .expect("mark fork");
    drop(connection);

    let python_evidence = fixture.base.join("python-evidence.json");
    let rust_evidence = fixture.base.join("rust-evidence.json");
    let extra_arg = extra.to_str().expect("utf-8 extra");
    let python_output = run_python(
        &script,
        &fixture,
        &[
            "--extra-dir",
            extra_arg,
            "--evidence-out",
            python_evidence.to_str().expect("utf-8"),
        ],
    );
    let rust_output = fixture.run_collect(&[
        "--extra-dir",
        extra_arg,
        "--evidence-out",
        rust_evidence.to_str().expect("utf-8"),
    ]);
    assert_eq!(
        exit_code(&python_output),
        exit_code(&rust_output),
        "python stderr: {}\nrust stderr: {}",
        stderr(&python_output),
        stderr(&rust_output)
    );
    assert_eq!(
        stdout(&python_output),
        stdout(&rust_output),
        "digest diverged from Python"
    );
    assert_eq!(
        comparable_evidence(read_evidence(&python_evidence)),
        comparable_evidence(read_evidence(&rust_evidence)),
        "evidence JSON diverged from Python"
    );

    // Format drift with `--strict`: same exit code and same digest.
    let junk: Vec<String> = (0..21).map(|index| format!("not json {index}")).collect();
    let refs: Vec<&str> = junk.iter().map(String::as_str).collect();
    fixture.write_raw_session(&root, "junk.jsonl", &refs, Some(now));
    let python_strict = run_python(&script, &fixture, &["--strict"]);
    let rust_strict = fixture.run_collect(&["--strict"]);
    assert_eq!(exit_code(&python_strict), 3);
    assert_eq!(exit_code(&rust_strict), 3);
    assert_eq!(
        stdout(&python_strict),
        stdout(&rust_strict),
        "strict digest diverged from Python"
    );
}

/// Guard: the implementation never carries raw credential prefixes.
#[test]
fn collector_sources_carry_no_raw_credential_literals() {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let sources = manifest.join("src").join("collect");
    let mut files: Vec<PathBuf> = fs::read_dir(&sources)
        .expect("collect sources")
        .flatten()
        .map(|entry| entry.path())
        .collect();
    files.sort();
    let token_prefix = ["gh", "p_"].concat();
    let home_root = ["/", "Users"].concat();
    for file in files {
        if file.extension().and_then(OsStr::to_str) != Some("rs") {
            continue;
        }
        let text = fs::read_to_string(&file).expect("read source");
        assert!(
            !text.contains(&token_prefix),
            "{} embeds a raw token prefix",
            file.display()
        );
        assert!(
            !text.contains(&home_root),
            "{} embeds a raw home root",
            file.display()
        );
    }
}
