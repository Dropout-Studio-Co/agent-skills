//! Surface discovery for the audit.
//!
//! Port of the Python helpers' `PRUNED`/`PRUNED_PATHS` walk, `classify()`,
//! `skill_roots_for()` and `frontmatter()`. Every candidate file is read exactly
//! once: [`Sources`] is the single read-through cache the rest of the audit
//! consults, so a file is never re-read per check.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::rc::Rc;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{Map, Value, json};

/// Directory names never descended into, at any depth.
pub(crate) const PRUNED: [&str; 14] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "graft",
    ".mypy_cache",
    ".pytest_cache",
    ".worktrees",
    "dist",
    "build",
    ".next",
    ".svelte-kit",
    "target",
    "vendor",
];

/// `(parent, child)` directory pairs never descended into.
pub(crate) const PRUNED_PATHS: [(&str, &str); 2] = [(".trail", "cache"), (".claude", "worktrees")];

/// Root documents that count as shared docs.
pub(crate) const ROOT_DOCS: [&str; 4] = [
    "README.md",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "DEVELOPMENT.md",
];

/// Instruction categories: surfaces the agent actually loads.
pub(crate) const INSTRUCTION: [&str; 6] = [
    "memory",
    "rules",
    "ide_rules",
    "skills",
    "commands",
    "subagents",
];

/// Token estimate for a byte count: `(bytes + 3) / 4`.
pub(crate) fn tok(bytes: u64) -> u64 {
    bytes.div_ceil(4)
}

/// Collapse `.` and `..` lexically, without touching the filesystem.
pub(crate) fn lexical_norm(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                if !out.pop() {
                    out.push("..");
                }
            }
            Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// Join `rel` onto `base` the way Python's `Path(base) / rel` does: empty and
/// `.` components are dropped and a trailing separator is normalised away, so a
/// reference like `.git/` probes `.git` rather than a non-directory.
pub(crate) fn join_python(base: &Path, rel: &str) -> PathBuf {
    let mut out = base.to_path_buf();
    for part in rel.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        out.push(part);
    }
    out
}

/// One decoded file: its raw bytes and its lossy UTF-8 text.
#[derive(Debug)]
pub(crate) struct FileData {
    /// Raw bytes, as read from disk.
    pub bytes: Vec<u8>,
    /// UTF-8 with invalid sequences replaced, matching Python's `errors="replace"`.
    pub text: String,
}

/// Read-through cache for repository files, keyed by repository-relative path.
///
/// Discovery, reference scanning, structure, hygiene and docs coverage all ask
/// this cache, so each file is read once per audit run.
#[derive(Debug)]
pub(crate) struct Sources {
    root: PathBuf,
    cache: RefCell<HashMap<String, Option<Rc<FileData>>>>,
}

impl Sources {
    /// A cache rooted at `root`.
    pub fn new(root: &Path) -> Self {
        Self {
            root: root.to_path_buf(),
            cache: RefCell::new(HashMap::new()),
        }
    }

    /// Load `rel` once; `None` when the file cannot be read.
    pub fn load(&self, rel: &str) -> Option<Rc<FileData>> {
        if let Some(hit) = self.cache.borrow().get(rel) {
            return hit.clone();
        }
        let path = if rel.is_empty() {
            self.root.clone()
        } else {
            self.root.join(rel)
        };
        let loaded = fs::read(&path).ok().map(|bytes| {
            Rc::new(FileData {
                text: String::from_utf8_lossy(&bytes).into_owned(),
                bytes,
            })
        });
        self.cache
            .borrow_mut()
            .insert(rel.to_string(), loaded.clone());
        loaded
    }
}

/// Split `text` exactly like Python's `str.splitlines()`.
pub(crate) fn splitlines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let bytes = text.as_bytes();
    let mut start = 0usize;
    let mut index = 0usize;
    while index < bytes.len() {
        let byte = bytes[index];
        let mut width = 1usize;
        let boundary = match byte {
            b'\n' | 0x0b | 0x0c | 0x1c | 0x1d | 0x1e => true,
            b'\r' => {
                if bytes.get(index + 1) == Some(&b'\n') {
                    width = 2;
                }
                true
            }
            0xc2 if bytes.get(index + 1) == Some(&0x85) => {
                width = 2;
                true
            }
            0xe2 if bytes.get(index + 1) == Some(&0x80)
                && matches!(bytes.get(index + 2), Some(&0xa8) | Some(&0xa9)) =>
            {
                width = 3;
                true
            }
            _ => false,
        };
        if boundary {
            out.push(&text[start..index]);
            index += width;
            start = index;
        } else {
            index += 1;
        }
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

/// Parsed YAML frontmatter fields the audit cares about.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Frontmatter {
    /// Whether a closed `---` block opened the file.
    pub has: bool,
    /// `name:` value.
    pub name: String,
    /// `description:` value, with block scalars folded to one line.
    pub description: String,
    /// Whether a `paths`/`globs`/`applyTo` key scopes the file.
    pub scope: bool,
    /// `alwaysApply:` value when it is a boolean.
    pub always_apply: Option<bool>,
    /// `disable-model-invocation: true`.
    pub disable_model_invocation: bool,
}

impl Frontmatter {
    fn blank() -> Self {
        Self {
            has: false,
            name: String::new(),
            description: String::new(),
            scope: false,
            always_apply: None,
            disable_model_invocation: false,
        }
    }
}

fn name_line() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"^name:\s*(.*)$").expect("name pattern must compile"))
}

fn description_line() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"^description:\s*(.*)$").expect("description pattern"))
}

fn always_apply_line() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"(?i)^alwaysApply:\s*(true|false)\s*$").expect("alwaysApply pattern")
    })
}

fn disable_model_line() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"(?i)^disable-model-invocation:\s*(true|false)\s*$").expect("disable pattern")
    })
}

fn scope_line() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"^(?:paths|globs|applyTo):\s*").expect("scope pattern must compile")
    })
}

/// Strip one layer of matching single or double quotes from both ends.
fn unquote(value: &str) -> &str {
    value.trim_matches(|character| character == '"' || character == '\'')
}

/// Parse the leading YAML frontmatter block of `text`.
pub(crate) fn frontmatter(text: &str) -> Frontmatter {
    let lines = splitlines(text);
    let Some(first) = lines.first() else {
        return Frontmatter::blank();
    };
    if first.trim() != "---" {
        return Frontmatter::blank();
    }
    let mut body: Vec<&str> = Vec::new();
    let mut closed = false;
    for line in lines.iter().skip(1) {
        if line.trim() == "---" {
            closed = true;
            break;
        }
        body.push(line);
    }
    if !closed {
        return Frontmatter::blank();
    }
    let mut parsed = Frontmatter::blank();
    parsed.has = true;
    for (index, line) in body.iter().enumerate() {
        if let Some(hit) = name_line().captures(line) {
            parsed.name = unquote(hit[1].trim()).to_string();
        }
        if let Some(hit) = description_line().captures(line) {
            let mut desc = hit[1].trim().to_string();
            if matches!(desc.as_str(), "|" | ">" | "|-" | ">-") {
                // Block scalar: only indented continuation lines belong to the
                // description; a later top-level key (for example `metadata:`)
                // ends it.
                let mut parts: Vec<&str> = Vec::new();
                for follow in body.iter().skip(index + 1) {
                    if follow.trim().is_empty() {
                        continue;
                    }
                    if !follow.starts_with(' ') && !follow.starts_with('\t') {
                        break;
                    }
                    parts.push(follow.trim());
                }
                desc = parts.join(" ");
            }
            parsed.description = unquote(&desc).to_string();
        }
        if let Some(hit) = always_apply_line().captures(line) {
            parsed.always_apply = Some(hit[1].eq_ignore_ascii_case("true"));
        }
        if let Some(hit) = disable_model_line().captures(line) {
            parsed.disable_model_invocation = hit[1].eq_ignore_ascii_case("true");
        }
        parsed.scope = parsed.scope || scope_line().is_match(line);
    }
    parsed
}

/// Which skills directories the audit recognises, most specific first.
pub(crate) fn skill_roots_for(skills_rel: &str) -> Vec<(String, &'static str)> {
    let candidates = [
        (
            format!("{}/", skills_rel.trim_end_matches('/')),
            "cross-agent",
        ),
        (".agents/skills/".to_string(), "cross-agent"),
        (".claude/skills/".to_string(), "claude"),
        (".codex/skills/".to_string(), "codex"),
        (".gemini/skills/".to_string(), "gemini"),
    ];
    let mut roots: Vec<(String, &'static str)> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for (prefix, agent) in candidates {
        if seen.insert(prefix.clone()) {
            roots.push((prefix, agent));
        }
    }
    roots
}

/// One discovered instruction surface.
#[derive(Debug, Clone)]
pub(crate) struct Item {
    /// Repository-relative path.
    pub path: String,
    /// `memory`, `rules`, `ide_rules`, `skills`, `commands`, `subagents`, ….
    pub category: String,
    /// Owning agent family.
    pub agent: String,
    /// Whether the file (or its description) is loaded on every run.
    pub always_loaded: bool,
    /// Symlink target when the surface is a symlink.
    pub link: Option<String>,
    /// Size in bytes; `0` for a symlink.
    pub bytes: u64,
    /// Line count; `0` for a symlink.
    pub lines: usize,
    /// Token estimate of the size; `0` for a symlink.
    pub tokens: u64,
    /// Token estimate of a skill's frontmatter description.
    pub description_tokens: Option<u64>,
    /// `disable-model-invocation: true` in a skill's frontmatter.
    pub disable_model_invocation: bool,
}

impl Item {
    /// JSON form used by the `inventory` array.
    pub fn to_json(&self) -> Value {
        let mut map = Map::new();
        map.insert("path".to_string(), json!(self.path));
        map.insert("category".to_string(), json!(self.category));
        map.insert("agent".to_string(), json!(self.agent));
        map.insert("always_loaded".to_string(), json!(self.always_loaded));
        map.insert("bytes".to_string(), json!(self.bytes));
        map.insert("lines".to_string(), json!(self.lines));
        map.insert("tokens".to_string(), json!(self.tokens));
        if let Some(link) = &self.link {
            map.insert("link".to_string(), json!(link));
        }
        if let Some(tokens) = self.description_tokens {
            map.insert("description_tokens".to_string(), json!(tokens));
        }
        if self.disable_model_invocation {
            map.insert("disable_model_invocation".to_string(), json!(true));
        }
        Value::Object(map)
    }
}

/// Classify a repository-relative path as an agent surface.
pub(crate) fn classify(
    rel: &str,
    roots: &[(String, &'static str)],
) -> Option<(&'static str, &'static str, bool)> {
    let name = rel.rsplit('/').next().unwrap_or(rel);
    let depth = rel.matches('/').count() + 1;
    let memory = match name {
        "AGENTS.md" | "AGENTS.override.md" => Some("cross-agent"),
        "CLAUDE.md" | "CLAUDE.local.md" => Some("claude"),
        "GEMINI.md" => Some("gemini"),
        _ => None,
    };
    if let Some(agent) = memory {
        return Some(("memory", agent, depth == 1));
    }
    if rel == ".github/copilot-instructions.md" {
        return Some(("memory", "copilot", true));
    }
    if rel.starts_with(".github/instructions/") && rel.ends_with(".instructions.md") {
        return Some(("rules", "copilot", false));
    }
    for (prefix, kind, agent, always) in [
        (".claude/rules/", "rules", "claude", true),
        (".agents/rules/", "rules", "cross-agent", true),
        (".claude/commands/", "commands", "claude", false),
        (".agents/commands/", "commands", "cross-agent", false),
        (".claude/agents/", "subagents", "claude", false),
        (".agents/agents/", "subagents", "cross-agent", false),
        (".claude/output-styles/", "output_styles", "claude", false),
    ] {
        if rel.starts_with(prefix) && rel.ends_with(".md") {
            return Some((kind, agent, always));
        }
    }
    if rel == ".cursorrules" || rel == ".windsurfrules" {
        let agent = if rel == ".cursorrules" {
            "cursor"
        } else {
            "windsurf"
        };
        return Some(("ide_rules", agent, true));
    }
    if rel.starts_with(".cursor/rules/") && (rel.ends_with(".mdc") || rel.ends_with(".md")) {
        return Some(("ide_rules", "cursor", false));
    }
    if rel.starts_with(".windsurf/rules/") && rel.ends_with(".md") {
        return Some(("ide_rules", "windsurf", false));
    }
    if rel == ".clinerules" || (rel.starts_with(".clinerules/") && rel.ends_with(".md")) {
        return Some(("ide_rules", "cline", true));
    }
    for (prefix, agent) in roots {
        if rel.starts_with(prefix.as_str())
            && name == "SKILL.md"
            && rel[prefix.len()..].matches('/').count() == 1
        {
            return Some(("skills", *agent, false));
        }
    }
    if rel.starts_with(".trail/learnings/") && rel.ends_with(".md") && depth == 3 {
        return Some(("learnings", "cross-agent", false));
    }
    if ROOT_DOCS.contains(&rel) || (rel.starts_with("docs/") && rel.ends_with(".md")) {
        return Some(("docs", "shared", false));
    }
    None
}

fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
}

fn has_git_marker(directory: &Path) -> bool {
    let dot = directory.join(".git");
    dot.exists() || is_symlink(&dot)
}

fn keep_directory(directory: &Path, here: &str, name: &str) -> bool {
    if PRUNED.contains(&name) {
        return false;
    }
    if PRUNED_PATHS
        .iter()
        .any(|(parent, child)| *parent == here && *child == name)
    {
        return false;
    }
    !is_symlink(directory) && !has_git_marker(directory)
}

/// Discover every instruction surface under `root`, sorted by path.
pub(crate) fn discover(
    root: &Path,
    sources: &Sources,
    scope: Option<&str>,
    skills_rel: &str,
) -> Vec<Item> {
    let roots = skill_roots_for(skills_rel);
    let mut items = Vec::new();
    walk(root, "", sources, scope, &roots, &mut items);
    items.sort_by(|left, right| left.path.cmp(&right.path));
    items
}

fn walk(
    directory: &Path,
    here: &str,
    sources: &Sources,
    scope: Option<&str>,
    roots: &[(String, &'static str)],
    items: &mut Vec<Item>,
) {
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    let mut dirs: Vec<String> = Vec::new();
    let mut files: Vec<String> = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let path = entry.path();
        match fs::metadata(&path) {
            Ok(metadata) if metadata.is_dir() => dirs.push(name),
            _ => files.push(name),
        }
    }
    dirs.sort();
    files.sort();
    for name in &files {
        let rel = if here.is_empty() {
            name.clone()
        } else {
            format!("{here}/{name}")
        };
        if let Some(anchor) = scope
            && rel != anchor
            && !rel.starts_with(&format!("{anchor}/"))
        {
            continue;
        }
        let Some(found) = classify(&rel, roots) else {
            continue;
        };
        collect_item(directory, name, rel, found, sources, items);
    }
    for name in &dirs {
        let child = directory.join(name);
        if !keep_directory(&child, here, name) {
            continue;
        }
        let child_rel = if here.is_empty() {
            name.clone()
        } else {
            format!("{here}/{name}")
        };
        walk(&child, &child_rel, sources, scope, roots, items);
    }
}

fn collect_item(
    directory: &Path,
    name: &str,
    rel: String,
    found: (&'static str, &'static str, bool),
    sources: &Sources,
    items: &mut Vec<Item>,
) {
    let (category, agent, mut always) = found;
    let path = directory.join(name);
    let mut item = Item {
        path: rel.clone(),
        category: category.to_string(),
        agent: agent.to_string(),
        always_loaded: always,
        link: None,
        bytes: 0,
        lines: 0,
        tokens: 0,
        description_tokens: None,
        disable_model_invocation: false,
    };
    if is_symlink(&path) {
        item.link = Some(
            fs::read_link(&path)
                .map(|target| target.to_string_lossy().into_owned())
                .unwrap_or_default(),
        );
        items.push(item);
        return;
    }
    let Some(data) = sources.load(&rel) else {
        return;
    };
    let meta = frontmatter(&data.text);
    if category == "rules" && meta.scope {
        always = false;
    } else if category == "ide_rules"
        && let Some(value) = meta.always_apply
    {
        always = value;
    }
    item.always_loaded = always;
    item.bytes = data.bytes.len() as u64;
    item.lines = splitlines(&data.text).len();
    item.tokens = tok(data.bytes.len() as u64);
    if category == "skills" {
        item.description_tokens = Some(tok(meta.description.len() as u64));
        if meta.disable_model_invocation {
            item.disable_model_invocation = true;
        }
    }
    items.push(item);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tok_rounds_up_in_quarters() {
        assert_eq!(tok(0), 0);
        assert_eq!(tok(1), 1);
        assert_eq!(tok(4), 1);
        assert_eq!(tok(5), 2);
        assert_eq!(tok(3999), 1000);
    }

    #[test]
    fn splitlines_matches_python_boundaries() {
        assert!(splitlines("").is_empty());
        assert_eq!(splitlines("a"), ["a"]);
        assert_eq!(splitlines("a\n"), ["a"]);
        assert_eq!(splitlines("a\n\n"), ["a", ""]);
        assert_eq!(splitlines("a\r\nb"), ["a", "b"]);
        assert_eq!(splitlines("a\rb"), ["a", "b"]);
        assert_eq!(splitlines("a\x0bb\x0cc"), ["a", "b", "c"]);
        assert_eq!(splitlines("a\u{2028}b\u{2029}c"), ["a", "b", "c"]);
        assert_eq!(splitlines("a\u{85}b"), ["a", "b"]);
    }

    #[test]
    fn frontmatter_reads_scalars_and_scope() {
        let meta = frontmatter(
            "---\nname: \"demo\"\ndescription: 'Demo skill.'\npaths:\n  - \"src/**\"\n---\nBody.\n",
        );
        assert!(meta.has);
        assert_eq!(meta.name, "demo");
        assert_eq!(meta.description, "Demo skill.");
        assert!(meta.scope);
        assert_eq!(meta.always_apply, None);
        assert!(!meta.disable_model_invocation);
    }

    #[test]
    fn frontmatter_folds_block_descriptions_and_stops_at_the_next_key() {
        for marker in ["|", ">", "|-", ">-"] {
            let text = format!(
                "---\nname: demo\ndescription: {marker}\n  First line.\n  Second line.\nmetadata:\n  version: \"1.0\"\n---\nBody.\n"
            );
            let meta = frontmatter(&text);
            assert_eq!(meta.description, "First line. Second line.", "{marker}");
        }
    }

    #[test]
    fn frontmatter_requires_a_closed_block() {
        assert!(!frontmatter("").has);
        assert!(!frontmatter("name: demo\n").has);
        assert!(!frontmatter("---\nname: demo\n").has);
        assert!(frontmatter("---\nname: demo\n---\n").has);
    }

    #[test]
    fn frontmatter_reads_boolean_flags() {
        let meta =
            frontmatter("---\nname: x\nalwaysApply: TRUE\ndisable-model-invocation: true\n---\n");
        assert_eq!(meta.always_apply, Some(true));
        assert!(meta.disable_model_invocation);
        let meta = frontmatter("---\nname: x\nalwaysApply: false\n---\n");
        assert_eq!(meta.always_apply, Some(false));
    }

    #[test]
    fn classify_covers_every_surface_family() {
        let roots = skill_roots_for(".agents/skills");
        let cases = [
            ("AGENTS.md", "memory", "cross-agent", true),
            ("CLAUDE.local.md", "memory", "claude", true),
            ("nested/AGENTS.md", "memory", "cross-agent", false),
            ("GEMINI.md", "memory", "gemini", true),
            (".github/copilot-instructions.md", "memory", "copilot", true),
            (
                ".github/instructions/ts.instructions.md",
                "rules",
                "copilot",
                false,
            ),
            (".claude/rules/api.md", "rules", "claude", true),
            (".agents/rules/shared.md", "rules", "cross-agent", true),
            (".claude/commands/release.md", "commands", "claude", false),
            (
                ".agents/agents/helper.md",
                "subagents",
                "cross-agent",
                false,
            ),
            (
                ".claude/output-styles/tone.md",
                "output_styles",
                "claude",
                false,
            ),
            (".cursorrules", "ide_rules", "cursor", true),
            (".windsurfrules", "ide_rules", "windsurf", true),
            (".cursor/rules/style.mdc", "ide_rules", "cursor", false),
            (".windsurf/rules/w.md", "ide_rules", "windsurf", false),
            (".clinerules", "ide_rules", "cline", true),
            (
                ".agents/skills/demo/SKILL.md",
                "skills",
                "cross-agent",
                false,
            ),
            (".claude/skills/tool/SKILL.md", "skills", "claude", false),
            (
                ".trail/learnings/note.md",
                "learnings",
                "cross-agent",
                false,
            ),
            ("README.md", "docs", "shared", false),
            ("docs/guide.md", "docs", "shared", false),
        ];
        for (rel, category, agent, always) in cases {
            assert_eq!(
                classify(rel, &roots),
                Some((category, agent, always)),
                "{rel}"
            );
        }
        for rel in [
            "src/main.rs",
            ".trail/learnings/deep/note.md",
            ".agents/skills/deep/nested/SKILL.md",
            "docs/notes.txt",
        ] {
            assert_eq!(classify(rel, &roots), None, "{rel}");
        }
    }

    #[test]
    fn skill_roots_deduplicate_the_configured_prefix() {
        let roots = skill_roots_for(".agents/skills/");
        assert_eq!(roots.len(), 4);
        assert_eq!(roots[0], (".agents/skills/".to_string(), "cross-agent"));
        let custom = skill_roots_for("custom/skills");
        assert_eq!(custom[0], ("custom/skills/".to_string(), "cross-agent"));
        assert_eq!(custom.len(), 5);
    }

    #[test]
    fn lexical_norm_collapses_dot_segments() {
        assert_eq!(lexical_norm(Path::new("./a//b")), PathBuf::from("a/b"));
        assert_eq!(lexical_norm(Path::new("a/../b")), PathBuf::from("b"));
        assert_eq!(lexical_norm(Path::new("a/../../b")), PathBuf::from("../b"));
    }
}
