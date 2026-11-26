//! Repository identification and membership tests.
//!
//! Port of the Python helpers' path/repository helpers (`norm`, `inside`,
//! `escapes`, `good_branch`, `branch_exists`, `repo_info`) and of the `Repo`
//! membership model used by the session collector: a session belongs to a
//! repository when its working directory sits in any live worktree that shares
//! the same git common directory.

use std::collections::{HashMap, HashSet};
use std::ffi::OsString;
use std::fmt::Write as _;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::{OnceLock, RwLock};

use regex::Regex;
use sha2::{Digest, Sha256};

use crate::git::{git_stdout, run_git};

/// Lower-case hex SHA-256 of `value`.
pub fn sha256_hex(value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    let mut hex = String::with_capacity(digest.len() * 2);
    for byte in digest {
        let _ = write!(hex, "{byte:02x}");
    }
    hex
}

/// Repository-relative form of `value`: forward slashes, no leading `./`.
pub fn norm_rel(value: &str) -> String {
    let normalized = value.replace(std::path::MAIN_SEPARATOR, "/");
    match normalized.strip_prefix("./") {
        Some(rest) => rest.to_string(),
        None => normalized,
    }
}

/// Absolute path with every existing symlink resolved, tolerating a missing
/// tail (equivalent to Python's `Path.resolve()` / `os.path.realpath`).
pub fn resolve_lenient(path: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(path))
            .unwrap_or_else(|_| path.to_path_buf())
    };
    let mut tail: Vec<OsString> = Vec::new();
    let mut current = absolute.as_path();
    loop {
        if let Ok(real) = fs::canonicalize(current) {
            let mut resolved = real;
            for part in tail.iter().rev() {
                resolved.push(part);
            }
            return resolved;
        }
        match (current.parent(), current.file_name()) {
            (Some(parent), Some(name)) => {
                tail.push(name.to_os_string());
                current = parent;
            }
            _ => return absolute,
        }
    }
}

/// True when `path` resolves to `root` or a descendant of it.
pub fn inside(path: &Path, root: &Path) -> bool {
    resolve_lenient(path).starts_with(resolve_lenient(root))
}

/// Nearest ancestor of `value` that exists on disk.
pub fn nearest_existing(value: &Path) -> Option<PathBuf> {
    let mut path = resolve_lenient(value);
    while !path.exists() {
        match path.parent() {
            Some(parent) if parent != path => path = parent.to_path_buf(),
            _ => return None,
        }
    }
    Some(path)
}

/// Absolute real path of the git common directory for `path`, when it is a git
/// checkout or worktree member.
pub fn common_dir(path: &Path) -> Option<String> {
    let reported = git_stdout(path, &["rev-parse", "--git-common-dir"]);
    if reported.is_empty() {
        return None;
    }
    let common = PathBuf::from(&reported);
    let absolute = if common.is_absolute() {
        common
    } else {
        path.join(common)
    };
    Some(resolve_lenient(&absolute).to_string_lossy().into_owned())
}

/// True when `rel` is absolute, climbs out of `root`, or crosses a symlink.
///
/// With `leaf`, the final component is checked too (used for files); without
/// it, only the directories leading to the leaf are checked (used for
/// directories that may not exist yet).
pub fn escapes(root: &Path, rel: &str, leaf: bool) -> bool {
    let normalized = norm_rel(rel);
    let path = Path::new(&normalized);
    let mut parts: Vec<&std::ffi::OsStr> = Vec::new();
    for component in path.components() {
        match component {
            Component::Normal(name) => parts.push(name),
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => return true,
        }
    }
    if parts.is_empty() {
        return true;
    }
    let walked = if leaf {
        parts.len()
    } else {
        parts.len().saturating_sub(1)
    };
    let mut current = root.to_path_buf();
    for part in parts.iter().take(walked) {
        current.push(part);
        let is_symlink = fs::symlink_metadata(&current)
            .map(|metadata| metadata.file_type().is_symlink())
            .unwrap_or(false);
        if is_symlink || !inside(&current, root) {
            return true;
        }
    }
    false
}

fn branch_pattern() -> &'static Regex {
    static BRANCH: OnceLock<Regex> = OnceLock::new();
    BRANCH.get_or_init(|| Regex::new(r"^[A-Za-z0-9._/-]+$").expect("branch pattern must compile"))
}

/// True when `name` is a safe, plausible git branch name.
pub fn good_branch(name: &str) -> bool {
    branch_pattern().is_match(name)
        && !name.starts_with('-')
        && !name.contains("..")
        && !name.contains("//")
}

/// True when `refs/heads/<name>` exists in the repository at `root`.
pub fn branch_exists(root: &Path, name: &str) -> bool {
    let reference = format!("refs/heads/{name}");
    run_git(&["show-ref", "--verify", "--quiet", &reference], root, None)
        .is_some_and(|output| output.status.success())
}

/// Facts about a repository root that the audit reports.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RepoInfo {
    /// Resolved repository root.
    pub root: PathBuf,
    /// Whether the root is inside a git checkout or worktree.
    pub is_git: bool,
    /// `HEAD` commit, empty when there is none.
    pub head: String,
    /// Current branch name, empty when detached or unborn.
    pub current: String,
    /// Default branch when one can be determined.
    pub default: Option<String>,
    /// Stable repository identity: SHA-256 of the common dir, else of the root.
    pub id: String,
}

/// Survey `root`, or explain why it is not a usable repository path.
pub fn repo_info(root: &Path) -> Result<RepoInfo, String> {
    let root = resolve_lenient(root);
    if !root.is_dir() {
        return Err("repository path is not a directory".to_string());
    }
    let Some(common) = common_dir(&root) else {
        return Ok(RepoInfo {
            id: sha256_hex(&root.to_string_lossy()),
            root,
            is_git: false,
            head: String::new(),
            current: String::new(),
            default: None,
        });
    };
    let symbolic = git_stdout(
        &root,
        &["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
    );
    let mut default = symbolic.find('/').map_or_else(
        || symbolic.clone(),
        |index| symbolic[index + 1..].to_string(),
    );
    if !good_branch(&default) {
        default = ["main", "master"]
            .iter()
            .find(|name| branch_exists(&root, name))
            .map(|name| (*name).to_string())
            .unwrap_or_default();
    }
    if default.is_empty() {
        let configured = git_stdout(&root, &["config", "--get", "init.defaultBranch"]);
        if good_branch(&configured) && branch_exists(&root, &configured) {
            default = configured;
        }
    }
    let head = git_stdout(&root, &["rev-parse", "HEAD"]);
    let current = git_stdout(&root, &["rev-parse", "--abbrev-ref", "HEAD"]);
    Ok(RepoInfo {
        root,
        is_git: true,
        head,
        current,
        default: if default.is_empty() {
            None
        } else {
            Some(default)
        },
        id: sha256_hex(&common),
    })
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

/// What counts as "inside this repository": live worktrees sharing a common dir.
#[derive(Debug)]
pub struct Repo {
    /// Resolved repository root.
    pub root: PathBuf,
    /// Whether the root is inside a git checkout or worktree.
    pub is_git: bool,
    /// Absolute git common directory, when there is one.
    pub common: Option<String>,
    /// Every live worktree path, including the root.
    pub worktrees: Vec<PathBuf>,
    /// Stable identity: SHA-256 of `common`, else of the root.
    pub repo_id: String,
    member_cache: RwLock<HashMap<String, bool>>,
}

impl Repo {
    /// Resolve `root` and the worktrees that share its common directory.
    pub fn new(root: &Path) -> Self {
        let root = resolve_lenient(root);
        let mut worktrees = vec![root.clone()];
        let mut common = None;
        let mut is_git = false;
        if let Some(found) = common_dir(&root) {
            common = Some(found);
            is_git = true;
            if let Some(output) = run_git(&["worktree", "list", "--porcelain"], &root, None)
                && output.status.success()
            {
                let text = String::from_utf8_lossy(&output.stdout);
                let found: Vec<PathBuf> = text
                    .lines()
                    .filter_map(|line| line.strip_prefix("worktree "))
                    .map(|path| resolve_lenient(Path::new(path.trim())))
                    .collect();
                if !found.is_empty() {
                    worktrees = found;
                }
            }
        }
        let basis = common
            .clone()
            .unwrap_or_else(|| root.to_string_lossy().into_owned());
        Self {
            repo_id: sha256_hex(&basis),
            root,
            is_git,
            common,
            worktrees,
            member_cache: RwLock::new(HashMap::new()),
        }
    }

    /// Every harness-encoded directory name this repository can appear under.
    pub fn encoded_names(&self) -> HashSet<String> {
        let mut names = HashSet::new();
        let mut worktrees = vec![self.root.clone()];
        worktrees.extend(self.worktrees.iter().cloned());
        for worktree in worktrees {
            names.insert(encode_name(&worktree));
            let real = fs::canonicalize(&worktree).unwrap_or_else(|_| resolve_lenient(&worktree));
            names.insert(encode_name(&real));
        }
        names
    }

    /// True when `cwd` belongs to this repository; lookups are cached.
    pub fn member(&self, cwd: &str) -> bool {
        if let Ok(cache) = self.member_cache.read()
            && let Some(known) = cache.get(cwd)
        {
            return *known;
        }
        let member = self.compute_member(cwd);
        if let Ok(mut cache) = self.member_cache.write() {
            cache.insert(cwd.to_string(), member);
        }
        member
    }

    fn compute_member(&self, cwd: &str) -> bool {
        if cwd.trim().is_empty() {
            return false;
        }
        if !self.is_git {
            return inside(Path::new(cwd), &self.root);
        }
        let Some(anchor) = nearest_existing(Path::new(cwd)) else {
            return false;
        };
        if !self
            .worktrees
            .iter()
            .any(|worktree| inside(&anchor, worktree))
        {
            return false;
        }
        common_dir(&anchor).is_some_and(|common| Some(common) == self.common)
    }
}

/// Repository root for a CLI argument, defaulting to the current checkout.
pub fn resolve_repo_root(arg: Option<&Path>) -> PathBuf {
    if let Some(value) = arg {
        return resolve_lenient(value);
    }
    let cwd = std::env::current_dir()
        .map(|path| resolve_lenient(&path))
        .unwrap_or_else(|_| PathBuf::from("."));
    if let Some(output) = run_git(&["rev-parse", "--show-toplevel"], &cwd, None)
        && output.status.success()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        let top = text.trim();
        if !top.is_empty() {
            return resolve_lenient(Path::new(top));
        }
    }
    cwd
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn init_repo(directory: &Path) {
        let output = run_git(&["init", "--quiet"], directory, None).expect("git init must run");
        assert!(output.status.success(), "git init failed");
    }

    fn commit_empty(directory: &Path) {
        let output = run_git(
            &[
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "--quiet",
                "-m",
                "init",
            ],
            directory,
            None,
        )
        .expect("git commit must run");
        assert!(output.status.success(), "git commit failed");
    }

    #[test]
    fn norm_rel_strips_a_leading_dot_slash() {
        assert_eq!(norm_rel("./a/b"), "a/b");
        assert_eq!(norm_rel("a/b"), "a/b");
        assert_eq!(norm_rel("."), ".");
        assert_eq!(norm_rel("a//b"), "a//b");
        assert_eq!(norm_rel("a/./b"), "a/./b");
    }

    #[test]
    fn good_branch_rejects_unsafe_names() {
        assert!(good_branch("main"));
        assert!(good_branch("feature/some-thing_1"));
        assert!(!good_branch(""));
        assert!(!good_branch("-force"));
        assert!(!good_branch("a..b"));
        assert!(!good_branch("a//b"));
        assert!(!good_branch("a b"));
        assert!(!good_branch("a~b"));
    }

    #[test]
    fn escapes_rejects_absolute_climbing_and_empty_paths() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path();
        assert!(!escapes(root, "a/b", false));
        assert!(!escapes(root, "./a/b", false));
        assert!(!escapes(root, "missing.md", true));
        assert!(escapes(root, "", false));
        assert!(escapes(root, ".", false));
        assert!(escapes(root, "..", false));
        assert!(escapes(root, "a/../../b", false));
        assert!(escapes(root, "/etc/passwd", false));
    }

    #[cfg(unix)]
    #[test]
    fn escapes_rejects_symlinked_segments() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("root");
        let outside = temp.path().join("outside");
        fs::create_dir_all(&root).expect("root");
        fs::create_dir_all(&outside).expect("outside");
        std::os::unix::fs::symlink(&outside, root.join("link")).expect("symlink");
        assert!(escapes(&root, "link/file.md", false));
        assert!(escapes(&root, "link", true));
        assert!(!escapes(&root, "plain/file.md", false));
    }

    #[test]
    fn encoded_names_replace_every_non_alphanumeric_character() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("my repo");
        fs::create_dir_all(&root).expect("root");
        let repo = Repo::new(&root);
        let encoded = encode_name(&resolve_lenient(&root));
        assert!(repo.encoded_names().contains(&encoded));
        assert!(encoded.contains("-repo"));
        assert_eq!(encode_name(Path::new("/a/b c_d.rs")), "-a-b-c-d-rs");
    }

    #[test]
    fn member_covers_the_checkout_and_rejects_neighbours() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("repo");
        let neighbour = temp.path().join("neighbour");
        fs::create_dir_all(root.join("sub")).expect("sub");
        fs::create_dir_all(&neighbour).expect("neighbour");
        init_repo(&root);
        let repo = Repo::new(&root);
        assert!(repo.is_git, "a git checkout must be detected");
        assert!(
            repo.member(&root.join("sub").to_string_lossy()),
            "a subdirectory of the checkout is a member"
        );
        assert!(!repo.member(&neighbour.to_string_lossy()));
        assert!(!repo.member(""));
        // Cached second lookup returns the same answer.
        assert!(!repo.member(&neighbour.to_string_lossy()));
    }

    #[test]
    fn member_uses_path_containment_outside_git() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("plain");
        fs::create_dir_all(root.join("deep")).expect("deep");
        let repo = Repo::new(&root);
        assert!(!repo.is_git);
        assert!(repo.member(&root.join("deep").to_string_lossy()));
        assert!(!repo.member(&temp.path().join("other").to_string_lossy()));
    }

    #[test]
    fn repo_info_reports_git_identity() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("repo");
        fs::create_dir_all(&root).expect("repo");
        init_repo(&root);
        commit_empty(&root);
        let info = repo_info(&root).expect("git repo info");
        assert!(info.is_git);
        assert_eq!(info.id.len(), 64);
        assert_eq!(info.head.len(), 40);
        assert!(!info.current.is_empty());
        assert!(matches!(
            info.default.as_deref(),
            None | Some("main") | Some("master")
        ));
        assert_eq!(info.root, resolve_lenient(&root));
    }

    #[test]
    fn repo_info_reports_a_plain_directory() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("plain");
        fs::create_dir_all(&root).expect("plain");
        let info = repo_info(&root).expect("plain dir info");
        assert!(!info.is_git);
        assert_eq!(info.default, None);
        assert_eq!(
            info.id,
            sha256_hex(&resolve_lenient(&root).to_string_lossy())
        );
    }

    #[test]
    fn repo_info_rejects_a_missing_directory() {
        let temp = tempdir().expect("tempdir");
        let error = repo_info(&temp.path().join("nowhere")).expect_err("missing dir");
        assert_eq!(error, "repository path is not a directory");
    }

    #[test]
    fn resolve_repo_root_prefers_the_argument() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("repo");
        fs::create_dir_all(&root).expect("repo");
        assert_eq!(resolve_repo_root(Some(&root)), resolve_lenient(&root));
    }
}
