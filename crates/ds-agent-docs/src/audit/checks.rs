//! Audit checks: delivery mode, context budget, imports, structure, hygiene and
//! documentation coverage.
//!
//! Port of the Python helpers' `delivery()`, `context_load()`, `check_imports()`,
//! `structure()`, `hygiene()` and `docs()`.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{Value, json};

use crate::git::run_git;
use crate::redact::{has_hygiene_hit, redact};
use crate::repo::{self, RepoInfo};

use super::discover::{
    FileData, INSTRUCTION, Item, Sources, frontmatter, join_python, lexical_norm, splitlines, tok,
};
use super::refs::{outside_fences, url_pattern};

/// Root files that can carry a written pull-request rule.
const PR_RULE_FILES: [&str; 3] = ["AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"];

/// Manifests reported by the documentation coverage check.
const MANIFESTS: [&str; 12] = [
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Gemfile",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
];

/// Root memory docs that agents always load.
const RECOMMENDED_DOCS: [&str; 2] = ["AGENTS.md", "README.md"];

/// Always-loaded line count above which a file is flagged as oversized.
const OVERSIZED_LINES: usize = 300;

/// Always-loaded token count above which a file is flagged as oversized.
const OVERSIZED_TOKENS: u64 = 3000;

/// Maximum number of duplicated paragraphs and hygiene hits reported.
const REPORT_CAP: usize = 50;

/// Minimum length of a line that can count as a duplicated paragraph.
const DUPLICATE_MIN: usize = 40;

/// Filesystem identity of a file: `(dev, ino)` on Unix, the real path elsewhere.
#[cfg(unix)]
type FileId = (u64, u64);
#[cfg(not(unix))]
type FileId = std::path::PathBuf;

#[cfg(unix)]
fn file_id(_path: &Path, metadata: &fs::Metadata) -> Option<FileId> {
    use std::os::unix::fs::MetadataExt;
    Some((metadata.dev(), metadata.ino()))
}

#[cfg(not(unix))]
fn file_id(path: &Path, _metadata: &fs::Metadata) -> Option<FileId> {
    Some(repo::resolve_lenient(path))
}

/// Identity and size of `rel`, matching Python's `inode()`.
fn inode(root: &Path, rel: &str) -> (Option<FileId>, u64) {
    let path = root.join(rel);
    match fs::metadata(&path) {
        Ok(metadata) => (file_id(&path, &metadata), metadata.len()),
        Err(_) => (None, 0),
    }
}

fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
}

/// True when the path exists or is a (possibly broken) symlink.
fn present(path: &Path) -> bool {
    path.exists() || is_symlink(path)
}

/// True when `path` exists and resolves inside `root`.
fn inside_repo(path: &Path, root: &Path) -> bool {
    path.exists() && repo::inside(path, root)
}

fn pr_yes() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(
            r"(?i)(\bmust\b|\brequires?\b|\brequired\b|\balways\b|\bonly\b|\buse\b|\bthrough\b|\bvia\b|\bopen\b|\bgo through\b).{0,60}\b(pull request|PR)\b",
        )
        .expect("pull-request pattern must compile")
    })
}

fn pr_no() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(
            r"(?i)(\bno\b|\bnever\b|\bnot\b|\bdon'?t\b|\bdo not\b|\bforbid\w*\b|\bmust not\b).{0,60}\b(direct(?:ly)?\s+)?(push|commit)",
        )
        .expect("no-push pattern must compile")
    })
}

fn at_import() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r#"^\s*@([^\s`"'<>]+)\s*$"#).expect("@import pattern must compile")
    })
}

fn at_target() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|[/.][A-Za-z0-9._-]+$")
            .expect("@target pattern must compile")
    })
}

fn backticked_import() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"`\s*@AGENTS\.md\s*`").expect("backticked import pattern must compile")
    })
}

fn command_fence() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"(?m)^```+\s*(?:sh|bash|zsh|shell|console)")
            .expect("command fence pattern must compile")
    })
}

/// Paths whose working-tree state the delivery check refuses to mix with.
fn is_surface(category: &str) -> bool {
    INSTRUCTION.contains(&category) || category == "output_styles" || category == "docs"
}

/// Paths reported by `git status --porcelain`, stripped to repository paths.
fn status_paths(root: &Path) -> HashSet<String> {
    let mut paths = HashSet::new();
    let Some(output) = run_git(&["status", "--porcelain"], root, None) else {
        return paths;
    };
    if !output.status.success() {
        return paths;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    for line in splitlines(&text) {
        if line.chars().count() < 4 {
            continue;
        }
        let Some(rest) = line.get(3..) else {
            continue;
        };
        let tail = rest.rsplit(" -> ").next().unwrap_or(rest);
        paths.insert(tail.trim().trim_matches('"').to_string());
    }
    paths
}

/// Quote one shell word the way Python's `shlex.quote()` does.
fn shlex_quote(value: &str) -> String {
    if value.is_empty() {
        return "''".to_string();
    }
    let safe = value
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || "_@%+=:,./-".contains(character));
    if safe {
        value.to_string()
    } else {
        format!("'{}'", value.replace('\'', "'\"'\"'"))
    }
}

fn worktree_commands(info: &RepoInfo) -> Vec<String> {
    let Some(default) = info.default.as_deref() else {
        return Vec::new();
    };
    if !repo::good_branch(default) {
        return Vec::new();
    }
    let stamp = chrono::Utc::now().format("%Y%m%dT%H%M%SZ").to_string();
    let raw = info
        .root
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut name: String = raw
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || "._-".contains(character) {
                character
            } else {
                '-'
            }
        })
        .collect();
    if name.is_empty() {
        name = "repo".to_string();
    }
    let folder = format!("/.local/state/ds-agent-docs/worktrees/{name}-{stamp}");
    let spot = format!("\"$HOME\"{}", shlex_quote(&folder));
    vec![
        format!("git fetch origin -- {}", shlex_quote(default)),
        format!(
            "git worktree add -b {} -- {spot} {}",
            shlex_quote(&format!("docs/ds-sync-{stamp}")),
            shlex_quote(&format!("origin/{default}"))
        ),
    ]
}

fn has_pr_rule(sources: &Sources) -> bool {
    for name in PR_RULE_FILES {
        let Some(data) = sources.load(name) else {
            continue;
        };
        if data.text.is_empty() {
            continue;
        }
        if splitlines(&data.text)
            .iter()
            .any(|line| pr_yes().is_match(line) || pr_no().is_match(line))
        {
            return true;
        }
    }
    false
}

/// How the audit's changes should be delivered for this checkout.
pub(crate) fn delivery(info: &RepoInfo, items: &[Item], sources: &Sources) -> Value {
    let surfaces: HashSet<&str> = items
        .iter()
        .filter(|item| is_surface(&item.category))
        .map(|item| item.path.as_str())
        .collect();
    let dirty = status_paths(&info.root)
        .iter()
        .any(|path| surfaces.contains(path.as_str()));
    let mut commands: Vec<String> = Vec::new();
    let (action, reason) = if dirty {
        ("patch_only", "dirty memory file")
    } else if !info.is_git {
        ("in_place", "not a git repository")
    } else if info.default.is_none() {
        ("patch_only", "unknown default branch")
    } else if info.current == "HEAD" {
        commands = worktree_commands(info);
        ("worktree", "detached HEAD")
    } else if Some(info.current.as_str()) != info.default.as_deref() {
        ("in_place", "task branch")
    } else if has_pr_rule(sources) {
        commands = worktree_commands(info);
        ("worktree", "default branch with a written PR rule")
    } else {
        ("in_place", "default branch without a written PR rule")
    };
    json!({
        "action": action,
        "reason": reason,
        "dirty": dirty,
        "commands": commands,
    })
}

/// Always-loaded token accounting against `cap`.
pub(crate) fn context_load(root: &Path, items: &[Item], cap: i64, sources: &Sources) -> Value {
    let mut seen: HashSet<FileId> = HashSet::new();
    let mut file_tokens: u64 = 0;
    let mut oversized: Vec<Value> = Vec::new();
    for item in items.iter().filter(|item| item.always_loaded) {
        let (key, size) = inode(root, &item.path);
        let Some(key) = key else {
            continue;
        };
        if !seen.insert(key) {
            continue;
        }
        let count = tok(size);
        file_tokens += count;
        let mut lines = item.lines;
        if item.link.is_some()
            && let Some(data) = sources.load(&item.path)
        {
            lines = splitlines(&data.text).len();
        }
        if lines > OVERSIZED_LINES || count > OVERSIZED_TOKENS {
            oversized.push(json!({"path": item.path, "lines": lines, "tokens": count}));
        }
    }
    let mut described: u64 = 0;
    let mut seen: HashSet<FileId> = HashSet::new();
    for item in items.iter().filter(|item| item.category == "skills") {
        let (key, _size) = inode(root, &item.path);
        let Some(key) = key else {
            continue;
        };
        if !seen.insert(key) {
            continue;
        }
        if item.link.is_some() {
            let Some(data) = sources.load(&item.path) else {
                continue;
            };
            let meta = frontmatter(&data.text);
            if !meta.disable_model_invocation {
                described += tok(meta.description.len() as u64);
            }
        } else if !item.disable_model_invocation {
            described += item.description_tokens.unwrap_or(0);
        }
    }
    let total = file_tokens + described;
    json!({
        "always_loaded_tokens": total,
        "always_loaded_file_tokens": file_tokens,
        "skill_description_tokens": described,
        "budget_cap": cap,
        "over_budget": (total as i64) > cap,
        "oversized": oversized,
    })
}

/// First non-empty line outside code fences and outside HTML comments.
fn first_outside_comment(text: &str) -> Option<String> {
    let mut in_comment = false;
    for line in outside_fences(text) {
        if line.fence.is_some() {
            continue;
        }
        let stripped = line.stripped;
        if in_comment {
            if stripped.contains("-->") {
                in_comment = false;
            }
            continue;
        }
        if stripped.is_empty() {
            continue;
        }
        if stripped.starts_with("<!--") {
            in_comment = !stripped.contains("-->");
            continue;
        }
        return Some(stripped.to_string());
    }
    None
}

fn import_errors(rel_c: &str, text: Option<&FileData>, agents: Option<&FileData>) -> Vec<Value> {
    let Some(text) = text else {
        return vec![json!({"file": rel_c, "error": "unreadable CLAUDE.md"})];
    };
    let mut errors: Vec<Value> = Vec::new();
    if backticked_import().is_match(&text.text) {
        errors.push(json!({"file": rel_c, "error": "backticked import"}));
    }
    if first_outside_comment(&text.text).as_deref() != Some("@AGENTS.md") {
        errors.push(json!({"file": rel_c, "error": "missing @AGENTS.md import"}));
    }
    let agents_text = agents.map(|data| data.text.as_str()).unwrap_or("");
    let shared: HashSet<&str> = outside_fences(agents_text)
        .iter()
        .map(|line| line.stripped)
        .filter(|line| line.chars().count() >= 4)
        .collect();
    for line in outside_fences(&text.text) {
        let stripped = line.stripped;
        if stripped != "@AGENTS.md"
            && stripped.chars().count() >= 4
            && shared.contains(stripped)
            && !stripped.starts_with('#')
            && !stripped.starts_with("<!--")
        {
            errors.push(json!({
                "file": rel_c,
                "line": line.number,
                "error": "line duplicated from AGENTS.md",
            }));
        }
    }
    errors
}

/// Whether each directory's `CLAUDE.md` bridges to its `AGENTS.md`.
pub(crate) fn check_imports(root: &Path, items: &[Item], sources: &Sources) -> Value {
    let has_claude =
        root.join(".claude").is_dir() || items.iter().any(|item| item.agent == "claude");
    let mut directories: HashSet<String> = HashSet::new();
    for item in items {
        if item.category != "memory" {
            continue;
        }
        let name = item.path.rsplit('/').next().unwrap_or(&item.path);
        if name != "AGENTS.md" && name != "CLAUDE.md" {
            continue;
        }
        let parent = match item.path.rsplit_once('/') {
            Some((directory, _)) => directory.to_string(),
            None => String::new(),
        };
        directories.insert(parent);
    }
    let mut sorted: Vec<String> = directories.into_iter().collect();
    sorted.sort();
    let mut errors: Vec<Value> = Vec::new();
    let mut warnings: Vec<Value> = Vec::new();
    for directory in sorted {
        let base = if directory.is_empty() {
            root.to_path_buf()
        } else {
            root.join(&directory)
        };
        let rel_a = if directory.is_empty() {
            "AGENTS.md".to_string()
        } else {
            format!("{directory}/AGENTS.md")
        };
        let rel_c = if directory.is_empty() {
            "CLAUDE.md".to_string()
        } else {
            format!("{directory}/CLAUDE.md")
        };
        let agents = base.join("AGENTS.md");
        let claude = base.join("CLAUDE.md");
        let a_on = present(&agents);
        let c_on = present(&claude);
        if c_on && !a_on {
            errors.push(json!({"file": rel_a, "error": "missing AGENTS.md"}));
        } else if a_on && !c_on {
            let entry = json!({"file": rel_c, "error": "missing CLAUDE.md import"});
            if has_claude {
                errors.push(entry);
            } else {
                warnings.push(entry);
            }
        } else if a_on && c_on && is_symlink(&claude) {
            let target = fs::read_link(&claude)
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default();
            let candidate = lexical_norm(&base.join(target));
            if repo::resolve_lenient(&candidate) != repo::resolve_lenient(&agents) {
                errors.push(json!({"file": rel_c, "error": "symlink points elsewhere"}));
            }
        } else if a_on && c_on {
            let claude_data = sources.load(&rel_c);
            let agents_data = sources.load(&rel_a);
            errors.extend(import_errors(
                &rel_c,
                claude_data.as_deref(),
                agents_data.as_deref(),
            ));
        }
    }
    json!({"ok": errors.is_empty(), "errors": errors, "warnings": warnings})
}

/// Dangling `@` imports, skill frontmatter problems, duplicated paragraphs and
/// legacy/modern rule overlaps.
pub(crate) fn structure(root: &Path, items: &[Item], sources: &Sources) -> Value {
    let mut dangling: Vec<Value> = Vec::new();
    let mut issues: Vec<Value> = Vec::new();
    for item in items {
        if item.link.is_some() || !INSTRUCTION.contains(&item.category.as_str()) {
            continue;
        }
        let Some(data) = sources.load(&item.path) else {
            continue;
        };
        for line in outside_fences(&data.text) {
            if line.fence.is_some() {
                continue;
            }
            let Some(hit) = at_import().captures(line.stripped) else {
                continue;
            };
            let target = hit[1].trim();
            if url_pattern().is_match(target)
                || target.starts_with("~/")
                || target.starts_with('/')
                || !at_target().is_match(target)
            {
                continue;
            }
            let local = root
                .join(&item.path)
                .parent()
                .map(|parent| join_python(parent, target))
                .unwrap_or_else(|| join_python(root, target));
            if inside_repo(&local, root) || inside_repo(&join_python(root, target), root) {
                continue;
            }
            dangling.push(json!({
                "file": item.path,
                "line": line.number,
                "import": format!("@{target}"),
            }));
        }
        if item.category != "skills" {
            continue;
        }
        let meta = frontmatter(&data.text);
        let folder = Path::new(&item.path)
            .parent()
            .and_then(Path::file_name)
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_default();
        if !meta.has {
            issues.push(json!({"file": item.path, "error": "missing YAML frontmatter"}));
        } else if meta.name.is_empty() {
            issues.push(json!({"file": item.path, "error": "missing frontmatter name"}));
        } else if meta.name != folder {
            issues.push(json!({
                "file": item.path,
                "error": format!(
                    "frontmatter name does not match folder ({} != {})",
                    meta.name, folder
                ),
            }));
        }
        if meta.has && meta.description.is_empty() {
            issues.push(json!({"file": item.path, "error": "missing frontmatter description"}));
        }
    }
    let mut seen: HashSet<FileId> = HashSet::new();
    let mut locations: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for item in items {
        if item.link.is_some()
            || !matches!(item.category.as_str(), "memory" | "rules" | "ide_rules")
        {
            continue;
        }
        let path = root.join(&item.path);
        let Ok(metadata) = fs::metadata(&path) else {
            continue;
        };
        let Some(key) = file_id(&path, &metadata) else {
            continue;
        };
        if !seen.insert(key) {
            continue;
        }
        let Some(data) = sources.load(&item.path) else {
            continue;
        };
        let mut local: HashSet<String> = HashSet::new();
        for line in outside_fences(&data.text) {
            let stripped = line.stripped;
            if line.fence.is_some()
                || stripped.chars().count() < DUPLICATE_MIN
                || stripped.starts_with('#')
                || stripped.starts_with("<!--")
                || stripped.starts_with('@')
                || stripped.starts_with('|')
            {
                continue;
            }
            let clean = stripped.split_whitespace().collect::<Vec<&str>>().join(" ");
            if local.insert(clean.clone()) {
                locations
                    .entry(clean)
                    .or_default()
                    .push(json!({"file": item.path, "line": line.number}));
            }
        }
    }
    let mut duplicates: Vec<Value> = Vec::new();
    for (clean, spots) in locations {
        if spots.len() < 2 {
            continue;
        }
        let head: String = clean.chars().take(140).collect();
        duplicates.push(json!({"text": redact(&head), "locations": spots}));
        if duplicates.len() >= REPORT_CAP {
            break;
        }
    }
    let paths: HashSet<&str> = items.iter().map(|item| item.path.as_str()).collect();
    let mut overlaps: Vec<Value> = Vec::new();
    for (old, new) in [
        (".cursorrules", ".cursor/rules/"),
        (".windsurfrules", ".windsurf/rules/"),
    ] {
        if paths.contains(old) && paths.iter().any(|path| path.starts_with(new)) {
            overlaps.push(json!({
                "legacy": old,
                "modern": new,
                "note": format!("legacy {old} present alongside {new}"),
            }));
        }
    }
    json!({
        "dangling_imports": dangling,
        "skill_frontmatter": issues,
        "duplicates": duplicates,
        "legacy_overlaps": overlaps,
    })
}

/// Instruction files that carry home paths or secret-shaped strings.
pub(crate) fn hygiene(items: &[Item], sources: &Sources) -> Value {
    let mut hits: Vec<Value> = Vec::new();
    for item in items {
        if item.link.is_some() || !INSTRUCTION.contains(&item.category.as_str()) {
            continue;
        }
        let Some(data) = sources.load(&item.path) else {
            continue;
        };
        for (index, line) in splitlines(&data.text).iter().enumerate() {
            if !has_hygiene_hit(line) {
                continue;
            }
            let redacted: String = redact(line.trim()).chars().take(200).collect();
            hits.push(json!({
                "file": item.path,
                "line": index + 1,
                "redacted": redacted,
            }));
            if hits.len() >= REPORT_CAP {
                return json!({"redaction_hits": hits});
            }
        }
    }
    json!({"redaction_hits": hits})
}

/// Manifests, present docs and missing recommended docs.
pub(crate) fn docs_coverage(root: &Path, items: &[Item], sources: &Sources) -> Value {
    let mut names: Vec<&str> = vec!["AGENTS.md"];
    names.extend(super::discover::ROOT_DOCS);
    let present: Vec<&str> = names
        .into_iter()
        .filter(|name| root.join(*name).is_file())
        .collect();
    let has_commands = RECOMMENDED_DOCS
        .iter()
        .filter(|name| root.join(**name).is_file())
        .any(|name| {
            sources
                .load(name)
                .map(|data| command_fence().is_match(&data.text))
                .unwrap_or(false)
        });
    let manifests: Vec<&str> = MANIFESTS
        .iter()
        .copied()
        .filter(|name| root.join(*name).is_file())
        .collect();
    let missing: Vec<&str> = RECOMMENDED_DOCS
        .iter()
        .copied()
        .filter(|name| !present.contains(name))
        .collect();
    json!({
        "manifests": manifests,
        "present_docs": present,
        "missing_recommended_docs": missing,
        "has_command_examples": has_commands,
        "docs_file_count": items.iter().filter(|item| item.category == "docs").count(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shlex_quote_matches_python() {
        assert_eq!(shlex_quote(""), "''");
        assert_eq!(shlex_quote("main"), "main");
        assert_eq!(shlex_quote("origin/main"), "origin/main");
        assert_eq!(shlex_quote("a b"), "'a b'");
        assert_eq!(shlex_quote("it's"), "'it'\"'\"'s'");
        assert_eq!(shlex_quote("/.local/state/x-1"), "/.local/state/x-1");
    }

    #[test]
    fn first_outside_comment_skips_fences_and_html_comments() {
        assert_eq!(
            first_outside_comment("<!-- bridge -->\n@AGENTS.md\n").as_deref(),
            Some("@AGENTS.md")
        );
        assert_eq!(
            first_outside_comment("<!--\nline 2\n-->\n@AGENTS.md\n").as_deref(),
            Some("@AGENTS.md")
        );
        assert_eq!(
            first_outside_comment("```md\n@AGENTS.md\n```\ntext\n").as_deref(),
            Some("text")
        );
        assert_eq!(first_outside_comment(""), None);
        assert_eq!(first_outside_comment("<!-- open\n").map(|_| ()), None);
    }

    #[test]
    fn pr_rules_recognise_written_policies() {
        assert!(pr_yes().is_match("Always open a pull request before merging."));
        assert!(pr_yes().is_match("Open a PR first."));
        assert!(pr_no().is_match("Never push directly to main."));
        assert!(pr_no().is_match("Do not commit to the default branch."));
        assert!(pr_no().is_match("No direct commits to main."));
        assert!(pr_no().is_match("Never pushing directly to main."));
        assert!(!pr_yes().is_match("Use the documented commands."));
        assert!(!pr_no().is_match("Use the documented commands."));
    }

    #[test]
    fn at_imports_require_a_whole_line() {
        assert!(at_import().is_match("@docs/missing.md"));
        assert!(at_import().is_match("  @AGENTS.md  "));
        assert!(!at_import().is_match("see @AGENTS.md"));
        assert!(at_target().is_match("docs/AGENTS.md"));
        assert!(at_target().is_match("notes.md"));
        assert!(!at_target().is_match("docs"));
    }

    #[test]
    fn status_paths_reads_porcelain_output() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path();
        let status = std::process::Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(root)
            .status()
            .expect("git init");
        assert!(status.success());
        fs::write(root.join("a.md"), "one\n").expect("write");
        let paths = status_paths(root);
        assert!(paths.contains("a.md"), "{paths:?}");
    }
}
