//! Reference extraction and classification for the audit.
//!
//! Port of the Python helpers' `outside_fences()`, `strip_ref()`, `suffix_of()`,
//! `tracked()`, `batch_ignored()` and `classify_ref()`.
//!
//! Only one batched `git check-ignore --stdin -z` call resolves every path the
//! classification could not decide; a pathspec failure falls back to one probe
//! per candidate. Tracked-file lookups go through a suffix index so a reference
//! never costs a scan over every tracked path.

use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{Value, json};

use crate::git::run_git;
use crate::redact::redact;

use super::discover::{Sources, join_python, splitlines};

/// Fence languages whose bodies are shell commands.
const SHELLS: [&str; 5] = ["sh", "bash", "zsh", "shell", "console"];

/// Extensions that make a bare path look like a real file reference.
const KNOWN_EXT: [&str; 26] = [
    ".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc", ".yaml", ".yml",
    ".toml", ".sh", ".bash", ".zsh", ".svelte", ".css", ".html", ".rs", ".go", ".rb", ".php",
    ".sql", ".xml", ".txt",
];

/// Package-manager subcommands that are not user scripts.
const PKG_BUILTINS: [&str; 45] = [
    "install",
    "i",
    "add",
    "remove",
    "rm",
    "update",
    "up",
    "upgrade",
    "init",
    "dlx",
    "exec",
    "x",
    "run",
    "create",
    "link",
    "unlink",
    "publish",
    "pack",
    "login",
    "logout",
    "whoami",
    "config",
    "cache",
    "store",
    "audit",
    "outdated",
    "list",
    "ls",
    "why",
    "info",
    "view",
    "search",
    "version",
    "help",
    "patch",
    "prune",
    "dedupe",
    "import",
    "rebuild",
    "env",
    "setup",
    "pm",
    "ci",
    "completions",
    "upgrade-interactive",
];

/// Bun subcommands that are built in rather than manifest scripts.
const BUN_BUILTINS: [&str; 3] = ["test", "build", "repl"];

/// Interpreters whose first file argument is a script reference.
const SCRIPT_RUNNERS: [&str; 11] = [
    "bash", "sh", "zsh", "python", "python3", "node", "tsx", "bun", "deno", "ruby", "perl",
];

/// Extensions that end a script-runner argument.
const SCRIPT_EXT: [&str; 8] = [".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl"];

/// One analysed line of a file: its number, trimmed text and fence language.
#[derive(Debug)]
pub(crate) struct Line<'a> {
    /// 1-based line number.
    pub number: usize,
    /// Whitespace-trimmed line.
    pub stripped: &'a str,
    /// Language of the enclosing code fence, `None` outside any fence.
    pub fence: Option<String>,
}

/// Split `text` into lines, tagging each as inside or outside a code fence.
pub(crate) fn outside_fences(text: &str) -> Vec<Line<'_>> {
    let mut out = Vec::new();
    let mut in_fence = false;
    let mut language = String::new();
    for (index, line) in splitlines(text).into_iter().enumerate() {
        let stripped = line.trim();
        if stripped.starts_with("```") || stripped.starts_with("~~~") {
            if in_fence {
                language.clear();
            } else {
                language = stripped
                    .trim_start_matches(['`', '~'])
                    .trim()
                    .to_lowercase();
            }
            in_fence = !in_fence;
            continue;
        }
        out.push(Line {
            number: index + 1,
            stripped,
            fence: if in_fence {
                Some(language.clone())
            } else {
                None
            },
        });
    }
    out
}

fn line_number_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r":\d+(?::\d+)?$").expect("line-number pattern"))
}

fn fragment_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"#.*$").expect("fragment pattern must compile"))
}

/// Drop a `:12`/`:12:34` suffix and a `#fragment`, then trailing punctuation.
pub(crate) fn strip_ref(value: &str) -> String {
    let without_lines = line_number_pattern().replace(value.trim(), "");
    let without_fragment = fragment_pattern().replace(&without_lines, "");
    without_fragment
        .trim_end_matches(['.', ',', ';', ':', '!', '?', ')', ']', '}', '"', '\''])
        .trim()
        .to_string()
}

/// Extension of the leaf component, with its leading dot, or an empty string.
pub(crate) fn suffix_of(value: &str) -> String {
    let leaf = value.rsplit('/').next().unwrap_or(value);
    match leaf.rsplit_once('.') {
        Some((_, extension)) => format!(".{extension}"),
        None => String::new(),
    }
}

/// The files git tracks in one repository, with O(1) suffix lookups.
#[derive(Debug)]
pub(crate) struct Tracked {
    /// Tracked paths, in git order.
    pub files: Vec<String>,
    /// Exact-path membership.
    paths: HashSet<String>,
    /// Every `/`-boundary suffix of every tracked path.
    suffixes: HashSet<String>,
    /// Whether any tracked path is a `package.json`.
    manifests: bool,
}

impl Tracked {
    fn new(root: &Path) -> Self {
        let files = tracked(root);
        let mut paths = HashSet::with_capacity(files.len());
        let mut suffixes = HashSet::new();
        let mut manifests = false;
        for path in &files {
            paths.insert(path.clone());
            for (index, character) in path.char_indices() {
                if character == '/' {
                    suffixes.insert(path[index + 1..].to_string());
                }
            }
            if path.ends_with("package.json") {
                manifests = true;
            }
        }
        Self {
            files,
            paths,
            suffixes,
            manifests,
        }
    }

    fn contains(&self, value: &str) -> bool {
        self.paths.contains(value)
    }

    fn under_slash(&self, value: &str) -> bool {
        self.suffixes.contains(value)
    }

    fn has_manifest(&self) -> bool {
        self.manifests
    }
}

fn tracked(root: &Path) -> Vec<String> {
    let Some(output) = run_git(&["ls-files", "-z"], root, None) else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    String::from_utf8_lossy(&output.stdout)
        .split('\0')
        .filter(|path| !path.is_empty())
        .map(str::to_string)
        .collect()
}

#[cfg(test)]
static CHECK_IGNORE_CALLS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn note_check_ignore_call() {
    #[cfg(test)]
    CHECK_IGNORE_CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
}

fn check_ignore_one(root: &Path, value: &str, cache: &mut HashMap<String, bool>) -> bool {
    if let Some(hit) = cache.get(value) {
        return *hit;
    }
    note_check_ignore_call();
    let ignored = run_git(&["check-ignore", "-q", "--", value], root, None)
        .is_some_and(|output| output.status.success());
    cache.insert(value.to_string(), ignored);
    ignored
}

/// Upper bound on the stdin a single `check-ignore` batch may receive.
///
/// The batch shares one pipe with git; keeping a chunk well under the 64 KiB
/// pipe buffer means a caller can never deadlock against a full stdout pipe.
const BATCH_BYTES: usize = 48 * 1024;

/// Candidates worth asking git about: relative, non-empty, inside the root.
fn ignore_candidates(refs: &[String]) -> Vec<&str> {
    let mut wanted: Vec<&str> = Vec::new();
    let mut seen: HashSet<&str> = HashSet::new();
    for value in refs {
        if value.is_empty() || value.contains('\0') || Path::new(value).is_absolute() {
            continue;
        }
        let normalized = super::discover::lexical_norm(Path::new(value));
        let text = normalized.to_string_lossy();
        if text == ".." || text.starts_with("../") {
            continue;
        }
        if seen.insert(value.as_str()) {
            wanted.push(value.as_str());
        }
    }
    wanted
}

/// The subset of `refs` that git ignores.
///
/// One `git check-ignore --stdin -z` call resolves every candidate; only a
/// pathologically large reference set is split into additional equally-sized
/// batches, and only a pathspec failure falls back to one probe per candidate.
pub(crate) fn batch_ignored(root: &Path, refs: &[String]) -> HashSet<String> {
    let wanted = ignore_candidates(refs);
    if wanted.is_empty() {
        return HashSet::new();
    }
    let mut ignored = HashSet::new();
    let mut start = 0usize;
    let mut bytes = 0usize;
    for (index, value) in wanted.iter().enumerate() {
        let width = value.len() + 1;
        if index > start && bytes + width > BATCH_BYTES {
            ignored.extend(run_ignore_batch(root, &wanted[start..index]));
            start = index;
            bytes = 0;
        }
        bytes += width;
    }
    ignored.extend(run_ignore_batch(root, &wanted[start..]));
    ignored
}

fn run_ignore_batch(root: &Path, wanted: &[&str]) -> HashSet<String> {
    if wanted.is_empty() {
        return HashSet::new();
    }
    let input = format!("{}\0", wanted.join("\0"));
    note_check_ignore_call();
    let Some(output) = run_git(&["check-ignore", "--stdin", "-z"], root, Some(&input)) else {
        return HashSet::new();
    };
    match output.status.code() {
        Some(0) | Some(1) => String::from_utf8_lossy(&output.stdout)
            .split('\0')
            .filter(|token| !token.is_empty())
            .map(str::to_string)
            .collect(),
        _ => {
            let stderr = String::from_utf8_lossy(&output.stderr).to_lowercase();
            if stderr.contains("not a git repository") {
                return HashSet::new();
            }
            // A single symlink or pathspec error aborts the whole batch; probe
            // each candidate so the valid ignored references survive.
            let mut cache = HashMap::new();
            wanted
                .iter()
                .filter(|value| check_ignore_one(root, value, &mut cache))
                .map(|value| (*value).to_string())
                .collect()
        }
    }
}

/// Which construct a reference was found in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RefKind {
    /// A line inside a shell code fence.
    Fence,
    /// A markdown link target.
    Link,
    /// A backticked inline value.
    Inline,
}

/// One classified reference.
#[derive(Debug, Clone)]
pub(crate) struct RefItem {
    /// File the reference appears in.
    pub file: String,
    /// 1-based line number.
    pub line: usize,
    /// Redacted reference text.
    pub value: String,
    /// `ok`, `ignored`, `stale`, `scoped`, `external` or `unverified`.
    pub class: &'static str,
}

impl RefItem {
    /// JSON form used by the `references.items`/`references.stale` arrays.
    pub fn to_json(&self) -> Value {
        json!({
            "file": self.file,
            "line": self.line,
            "ref": self.value,
            "class": self.class,
        })
    }
}

/// Cache of the "is this reference ignored?" answers for one scan pass.
pub(crate) struct RefCache {
    order: Vec<String>,
    seen: HashSet<String>,
    known: Option<HashSet<String>>,
}

impl RefCache {
    /// Collecting pass: every candidate is recorded and reported as not ignored.
    fn collecting() -> Self {
        Self {
            order: Vec::new(),
            seen: HashSet::new(),
            known: None,
        }
    }

    /// Deciding pass: answers come from the batched `check-ignore` result.
    fn deciding(ignored: HashSet<String>) -> Self {
        Self {
            order: Vec::new(),
            seen: HashSet::new(),
            known: Some(ignored),
        }
    }

    fn ignored(&mut self, value: &str) -> bool {
        match &self.known {
            Some(known) => known.contains(value),
            None => {
                if self.seen.insert(value.to_string()) {
                    self.order.push(value.to_string());
                }
                false
            }
        }
    }
}

fn package_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"^\s*(?:npm|pnpm|bun|yarn)\s+run\s+([^\s;&|]+)").expect("package run pattern")
    })
}

fn package_short_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"^\s*(pnpm|bun|yarn)\s+([^\s;&|]+)").expect("short package pattern")
    })
}

fn make_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"^\s*make\s+([^\s;&|]+)").expect("make pattern"))
}

/// Absolute-URL pattern shared with the structure check.
pub(crate) fn url_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"(?i)^[a-z][a-z0-9+.\-]*://").expect("url pattern"))
}

fn placeholder_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"[<>{}*?\[\]]").expect("placeholder pattern"))
}

fn link_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN
        .get_or_init(|| Regex::new(r#"]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)"#).expect("link pattern"))
}

fn backtick_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new("`([^`\\n]+)`").expect("backtick pattern"))
}

/// Shared inputs to reference classification.
struct Classify<'a> {
    root: &'a Path,
    tracked: &'a Tracked,
    sources: &'a Sources,
}

impl Classify<'_> {
    fn classify(
        &self,
        value: &str,
        file_rel: &str,
        kind: RefKind,
        cache: &mut RefCache,
        shell: bool,
    ) -> Option<&'static str> {
        let value = strip_ref(value);
        if value.is_empty() || value.starts_with('#') || value.starts_with('-') {
            return None;
        }
        if shell {
            return self.classify_shell(&value, file_rel, kind, cache);
        }
        if url_pattern().is_match(&value)
            || value.starts_with("mailto:")
            || value.starts_with('~')
            || value.starts_with('/')
            || value.starts_with('$')
        {
            return Some("external");
        }
        if placeholder_pattern().is_match(&value) {
            return Some("scoped");
        }
        let mut bases: Vec<std::path::PathBuf> = vec![self.root.to_path_buf()];
        if !file_rel.is_empty()
            && let Some(parent) = self.root.join(file_rel).parent()
        {
            bases.push(parent.to_path_buf());
        }
        for base in bases {
            let candidate = join_python(&base, &value);
            if candidate.exists() && crate::repo::inside(&candidate, self.root) {
                return Some("ok");
            }
        }
        if cache.ignored(&value) {
            return Some("ignored");
        }
        if kind == RefKind::Link {
            return Some("stale");
        }
        if !value.contains('/') {
            return Some(
                if self.tracked.contains(&value) || self.tracked.under_slash(&value) {
                    "ok"
                } else {
                    "scoped"
                },
            );
        }
        if self.tracked.under_slash(&value) {
            return Some("ok");
        }
        if value.starts_with("../") {
            return Some("external");
        }
        let first = value.split('/').next().unwrap_or(&value);
        let looks_like_file = value.starts_with("./")
            || self.root.join(first).is_dir()
            || KNOWN_EXT.contains(&suffix_of(&value).as_str());
        Some(if looks_like_file { "stale" } else { "scoped" })
    }

    fn classify_shell(
        &self,
        value: &str,
        file_rel: &str,
        kind: RefKind,
        cache: &mut RefCache,
    ) -> Option<&'static str> {
        if let Some(hit) = package_pattern().captures(value) {
            let token = &hit[1];
            if token.starts_with('-') {
                return None;
            }
            return Some(if placeholder_pattern().is_match(token) {
                "scoped"
            } else {
                self.package(token)
            });
        }
        if let Some(hit) = make_pattern().captures(value) {
            let token = &hit[1];
            if token.starts_with('-') {
                return None;
            }
            return Some(if placeholder_pattern().is_match(token) {
                "scoped"
            } else {
                self.make(token)
            });
        }
        let parts: Vec<&str> = value.split_whitespace().collect();
        if parts.len() >= 2 && SCRIPT_RUNNERS.contains(&parts[0]) {
            for raw in parts.iter().skip(1) {
                if ["-m", "-c", "-e", "--eval"].contains(raw) {
                    break;
                }
                if raw.starts_with('-') {
                    continue;
                }
                let argument = raw.trim_matches(|character| character == '"' || character == '\'');
                if !argument.is_empty()
                    && !argument.starts_with(['-', '$', '<', '~', '/'])
                    && !argument.starts_with("http")
                    && (argument.contains('/')
                        || SCRIPT_EXT.iter().any(|ext| argument.ends_with(ext)))
                {
                    return self.classify(argument, file_rel, kind, cache, false);
                }
                break;
            }
        }
        if let Some(hit) = package_short_pattern().captures(value) {
            let manager = &hit[1];
            let token = &hit[2];
            let known = PKG_BUILTINS.contains(&token)
                || (manager == "bun" && BUN_BUILTINS.contains(&token));
            if token.starts_with('-')
                || known
                || token.contains('/')
                || !(self.root.join("package.json").is_file() || self.tracked.has_manifest())
            {
                return None;
            }
            return Some(if placeholder_pattern().is_match(token) {
                "scoped"
            } else {
                self.package(token)
            });
        }
        None
    }

    fn package(&self, name: &str) -> &'static str {
        let mut manifests: Vec<(String, &'static str)> = Vec::new();
        if self.root.join("package.json").is_file() {
            manifests.push(("package.json".to_string(), "ok"));
        }
        for rel in &self.tracked.files {
            if rel.ends_with("package.json") && rel != "package.json" {
                manifests.push((rel.clone(), "scoped"));
            }
        }
        for (rel, class) in &manifests {
            let Some(data) = self.sources.load(rel) else {
                continue;
            };
            let Ok(value) = serde_json::from_str::<Value>(&data.text) else {
                continue;
            };
            if let Some(scripts) = value.get("scripts")
                && scripts.is_object()
                && scripts.get(name).is_some()
            {
                return class;
            }
        }
        if manifests.is_empty() {
            "unverified"
        } else {
            "stale"
        }
    }

    fn make(&self, target: &str) -> &'static str {
        if !self.root.join("Makefile").is_file() {
            return "unverified";
        }
        let Some(data) = self.sources.load("Makefile") else {
            return "unverified";
        };
        let pattern = format!("(?m)^{}\\s*:", regex::escape(target));
        match Regex::new(&pattern) {
            Ok(compiled) if compiled.is_match(&data.text) => "ok",
            _ => "stale",
        }
    }
}

fn reference(file_rel: &str, line: usize, value: &str, class: &'static str) -> RefItem {
    RefItem {
        file: file_rel.to_string(),
        line,
        value: redact(value.trim()),
        class,
    }
}

fn scan(
    classify: &Classify<'_>,
    items: &[super::discover::Item],
    cache: &mut RefCache,
) -> Vec<RefItem> {
    let mut found = Vec::new();
    for item in items {
        if item.link.is_some() {
            continue;
        }
        let Some(data) = classify.sources.load(&item.path) else {
            continue;
        };
        for line in outside_fences(&data.text) {
            if let Some(language) = line.fence.as_deref() {
                if SHELLS.contains(&language)
                    && !line.stripped.is_empty()
                    && !line.stripped.starts_with('#')
                    && let Some(class) =
                        classify.classify(line.stripped, &item.path, RefKind::Fence, cache, true)
                {
                    found.push(reference(&item.path, line.number, line.stripped, class));
                }
                continue;
            }
            for hit in link_pattern().captures_iter(line.stripped) {
                if let Some(class) =
                    classify.classify(&hit[1], &item.path, RefKind::Link, cache, false)
                {
                    found.push(reference(&item.path, line.number, &hit[1], class));
                }
            }
            for hit in backtick_pattern().captures_iter(line.stripped) {
                let value = &hit[1];
                let mut class = classify.classify(value, &item.path, RefKind::Inline, cache, true);
                if class.is_none() && !value.trim().contains(' ') {
                    class = classify.classify(value, &item.path, RefKind::Inline, cache, false);
                }
                if let Some(class) = class {
                    found.push(reference(&item.path, line.number, value, class));
                }
            }
        }
    }
    found
}

/// Every reference in `items`, with gitignored targets recognised.
pub(crate) fn collect_references(
    root: &Path,
    sources: &Sources,
    items: &[super::discover::Item],
) -> Vec<RefItem> {
    let tracked = Tracked::new(root);
    let classify = Classify {
        root,
        tracked: &tracked,
        sources,
    };
    let mut probe = RefCache::collecting();
    let found = scan(&classify, items, &mut probe);
    let ignored = batch_ignored(root, &probe.order);
    if ignored.is_empty() {
        return found;
    }
    let mut deciding = RefCache::deciding(ignored);
    scan(&classify, items, &mut deciding)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outside_fences_tags_shell_bodies_and_skips_markers() {
        let text = "# Title\n\n```sh\nnpm run build\n```\n\n`inline`\n";
        let lines = outside_fences(text);
        let numbers: Vec<usize> = lines.iter().map(|line| line.number).collect();
        assert_eq!(numbers, [1, 2, 4, 6, 7]);
        assert_eq!(lines[0].fence, None);
        assert_eq!(lines[2].fence.as_deref(), Some("sh"));
        assert_eq!(lines[4].fence, None);
    }

    #[test]
    fn outside_fences_clears_the_language_after_closing() {
        let text = "```SH\ncmd\n```\nprose\n```\nplain\n```\n";
        let lines = outside_fences(text);
        assert_eq!(lines[0].fence.as_deref(), Some("sh"));
        assert_eq!(lines[1].fence, None);
        assert_eq!(lines[2].fence.as_deref(), Some(""));
    }

    #[test]
    fn strip_ref_removes_lines_fragments_and_trailing_punctuation() {
        assert_eq!(strip_ref(" docs/guide.md "), "docs/guide.md");
        assert_eq!(strip_ref("src/main.rs:12"), "src/main.rs");
        assert_eq!(strip_ref("src/main.rs:12:4"), "src/main.rs");
        assert_eq!(strip_ref("docs/guide.md#section"), "docs/guide.md");
        assert_eq!(strip_ref("(see: README.md),"), "(see: README.md");
        assert_eq!(strip_ref("'quoted.py'"), "'quoted.py");
        assert_eq!(strip_ref("[link](./a.md)"), "[link](./a.md");
        assert_eq!(strip_ref(".git/"), ".git/");
        assert_eq!(strip_ref("--"), "--");
    }

    #[test]
    fn suffix_of_returns_the_extension_of_the_leaf() {
        assert_eq!(suffix_of("docs/guide.md"), ".md");
        assert_eq!(suffix_of("Makefile"), "");
        assert_eq!(suffix_of("a.b/c"), "");
        assert_eq!(suffix_of("archive.tar.gz"), ".gz");
    }

    #[test]
    fn batched_ignore_uses_one_call_for_many_references() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path();
        let status = std::process::Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(root)
            .status()
            .expect("git init");
        assert!(status.success());
        std::fs::write(root.join(".gitignore"), "generated/\ncache/\n").expect("gitignore");
        let refs: Vec<String> = (0..6)
            .map(|index| {
                let folder = if index % 2 == 0 { "generated" } else { "cache" };
                format!("{folder}/file-{index}.md")
            })
            .collect();
        CHECK_IGNORE_CALLS.store(0, std::sync::atomic::Ordering::Relaxed);
        let ignored = batch_ignored(root, &refs);
        assert_eq!(ignored.len(), 6, "{ignored:?}");
        assert_eq!(
            CHECK_IGNORE_CALLS.load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }

    #[test]
    fn batched_ignore_skips_traversal_and_non_git_roots() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path();
        let refs = vec![
            "../outside.md".to_string(),
            "./../outside.md".to_string(),
            String::new(),
        ];
        CHECK_IGNORE_CALLS.store(0, std::sync::atomic::Ordering::Relaxed);
        assert!(batch_ignored(root, &refs).is_empty());
        assert_eq!(
            CHECK_IGNORE_CALLS.load(std::sync::atomic::Ordering::Relaxed),
            0
        );
    }
}
