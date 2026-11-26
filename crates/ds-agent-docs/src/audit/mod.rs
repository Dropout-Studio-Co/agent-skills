//! `audit` command: read-only survey of a repository's agent instructions and docs.
//!
//! Rust port of `skills/ds-agent-docs/scripts/check_instructions.py audit`. The
//! JSON payload, its key set and the exit codes (`0` ok, `2` invalid or unsafe
//! input) are byte-for-byte comparable with the Python helper: every object is a
//! `serde_json::Value` whose default map sorts keys, and it is printed with two
//! spaces of indentation.

mod checks;
mod discover;
mod refs;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

use crate::repo::{self, RepoInfo, repo_info};

use discover::{Item, Sources};
use refs::RefItem;

/// Default skills directory, relative to the repository root.
const DEFAULT_SKILLS: &str = ".agents/skills";

/// Exit code for a successful audit.
const OK: i32 = 0;

/// Exit code for invalid or unsafe input.
const BAD: i32 = 2;

/// Arguments accepted by the `audit` subcommand.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditArgs {
    /// Repository root to survey.
    pub repo: PathBuf,
    /// Optional scope relative to the repository root.
    pub scope: Option<String>,
    /// Context token budget; validated by `run_audit` so invalid values exit 2.
    pub budget_tokens: i64,
    /// Skills directory relative to the repository root.
    pub skills_dir: Option<String>,
    /// Emit the JSON payload on stdout.
    pub json: bool,
}

/// Run the audit and return its process exit code.
pub fn run_audit(args: AuditArgs) -> i32 {
    let (code, payload) = audit_command(
        &args.repo,
        args.scope.as_deref(),
        args.budget_tokens,
        args.skills_dir.as_deref(),
    );
    // `--json` is accepted for CLI parity with the Python helper: the audit
    // always prints exactly one JSON object on stdout.
    let _ = args.json;
    match serde_json::to_string_pretty(&payload) {
        Ok(text) => println!("{text}"),
        Err(_) => println!("{{\"status\": \"invalid\"}}"),
    }
    code
}

/// Build the audit payload for `repo`; the second value is the exit code.
pub fn audit_command(
    repo: &Path,
    scope: Option<&str>,
    budget: i64,
    skills: Option<&str>,
) -> (i32, Value) {
    if budget <= 0 {
        return (BAD, invalid("budget tokens must be a positive integer"));
    }
    let info = match repo_info(repo) {
        Ok(info) => info,
        Err(error) => return (BAD, invalid(&error)),
    };
    let scope_rel = match resolve(&info.root, scope, "scope", false) {
        Ok(value) => value,
        Err(error) => return (BAD, invalid(&error)),
    };
    let skills_rel = match resolve(&info.root, skills, "skills", true) {
        Ok(value) => value.unwrap_or_else(|| DEFAULT_SKILLS.to_string()),
        Err(error) => return (BAD, invalid(&error)),
    };
    let sources = Sources::new(&info.root);
    let items = discover::discover(&info.root, &sources, scope_rel.as_deref(), &skills_rel);
    let references = refs::collect_references(&info.root, &sources, &items);
    (
        OK,
        payload(
            &info,
            scope_rel.as_deref(),
            budget,
            &items,
            &references,
            &sources,
        ),
    )
}

fn invalid(error: &str) -> Value {
    json!({
        "version": 1,
        "command": "audit",
        "status": "invalid",
        "error": error,
    })
}

/// Resolve `--scope`/`--skills-dir` to a repository-relative path.
///
/// Rejects absolute paths, `..` climbs and symlink escapes, exactly like the
/// Python helper's `resolve()`.
fn resolve(
    root: &Path,
    value: Option<&str>,
    label: &str,
    want_dir: bool,
) -> Result<Option<String>, String> {
    let Some(raw_value) = value else {
        return Ok(if label == "skills" {
            Some(DEFAULT_SKILLS.to_string())
        } else {
            None
        });
    };
    let raw = raw_value.trim();
    if label == "scope" && (raw.is_empty() || raw == "." || raw == "./") {
        return Ok(None);
    }
    let mut rel = if raw.is_empty() || raw == "." {
        String::new()
    } else {
        repo::norm_rel(raw)
    };
    if !rel.is_empty() && repo::escapes(root, &rel, true) {
        return Err(format!("{label} escapes repository root"));
    }
    if rel.is_empty() && label == "skills" {
        // An empty skills value means "the default", never the whole checkout.
        rel = DEFAULT_SKILLS.to_string();
    }
    let target = if rel.is_empty() {
        root.to_path_buf()
    } else {
        root.join(&rel)
    };
    if want_dir && !target.is_dir() {
        return Err(format!("{label} does not exist"));
    }
    if !want_dir && (rel.is_empty() || !target.exists() || !repo::inside(&target, root)) {
        return Err(format!("{label} does not exist"));
    }
    Ok(if rel.is_empty() { None } else { Some(rel) })
}

fn payload(
    info: &RepoInfo,
    scope: Option<&str>,
    budget: i64,
    items: &[Item],
    references: &[RefItem],
    sources: &Sources,
) -> Value {
    let mut repo = Map::new();
    repo.insert("id".to_string(), json!(info.id));
    repo.insert(
        "kind".to_string(),
        json!(if info.is_git { "git" } else { "dir" }),
    );
    repo.insert("head".to_string(), json!(info.head));
    repo.insert(
        "current_branch".to_string(),
        json!(if info.current == "HEAD" {
            ""
        } else {
            info.current.as_str()
        }),
    );
    repo.insert("default_branch".to_string(), json!(info.default));
    let mut root = Map::new();
    root.insert("version".to_string(), json!(1));
    root.insert("command".to_string(), json!("audit"));
    root.insert("status".to_string(), json!("ok"));
    root.insert("repo".to_string(), Value::Object(repo));
    root.insert("scope".to_string(), json!(scope));
    root.insert(
        "delivery".to_string(),
        checks::delivery(info, items, sources),
    );
    root.insert(
        "inventory".to_string(),
        Value::Array(items.iter().map(Item::to_json).collect()),
    );
    root.insert(
        "context_load".to_string(),
        checks::context_load(&info.root, items, budget, sources),
    );
    root.insert(
        "import".to_string(),
        checks::check_imports(&info.root, items, sources),
    );
    root.insert("references".to_string(), references_payload(references));
    root.insert(
        "structure".to_string(),
        checks::structure(&info.root, items, sources),
    );
    root.insert("hygiene".to_string(), checks::hygiene(items, sources));
    root.insert(
        "docs_coverage".to_string(),
        checks::docs_coverage(&info.root, items, sources),
    );
    Value::Object(root)
}

fn references_payload(references: &[RefItem]) -> Value {
    let mut counts: BTreeMap<&str, u64> = BTreeMap::new();
    for item in references {
        *counts.entry(item.class).or_insert(0) += 1;
    }
    let stale: Vec<Value> = references
        .iter()
        .filter(|item| item.class == "stale")
        .map(RefItem::to_json)
        .collect();
    json!({
        "total": references.len(),
        "counts": counts,
        "stale": stale,
        "items": references.iter().map(RefItem::to_json).collect::<Vec<Value>>(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_payload_keeps_the_python_shape() {
        let value = invalid("scope does not exist");
        assert_eq!(value["version"], json!(1));
        assert_eq!(value["command"], json!("audit"));
        assert_eq!(value["status"], json!("invalid"));
        assert_eq!(value["error"], json!("scope does not exist"));
    }

    #[test]
    fn non_positive_budgets_are_rejected_before_any_work() {
        let temp = tempfile::tempdir().expect("tempdir");
        for budget in [0, -1, -5000] {
            let (code, value) = audit_command(temp.path(), None, budget, None);
            assert_eq!(code, BAD);
            assert_eq!(value["status"], json!("invalid"));
            assert_eq!(
                value["error"],
                json!("budget tokens must be a positive integer")
            );
        }
    }
}
