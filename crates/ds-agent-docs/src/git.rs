//! Thin `git` runner that never inherits repository-selecting variables.

use std::io::Write;
use std::path::Path;
use std::process::{Command, Output, Stdio};

/// Environment variables that would redirect `git` at another repository.
pub const GIT_STRIP: [&str; 4] = [
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
];

/// Run `git` with `args` in `cwd`, optionally feeding `input` on stdin.
///
/// Repository-selecting variables are removed from the child environment.
/// Returns `None` when git cannot be spawned or waited on.
pub fn run_git(args: &[&str], cwd: &Path, input: Option<&str>) -> Option<Output> {
    let mut command = Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for key in GIT_STRIP {
        command.env_remove(key);
    }
    let mut child = command.spawn().ok()?;
    if let Some(data) = input
        && let Some(mut stdin) = child.stdin.take()
    {
        // A git process that stops reading is reported by its exit status.
        let _ = stdin.write_all(data.as_bytes());
    }
    child.wait_with_output().ok()
}

/// Trimmed stdout of a successful `git` invocation, or an empty string.
pub fn git_stdout(cwd: &Path, args: &[&str]) -> String {
    match run_git(args, cwd, None) {
        Some(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_string()
        }
        _ => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reports_a_successful_invocation() {
        let cwd = std::env::temp_dir();
        let output = run_git(&["--version"], &cwd, None).expect("git must run");
        assert!(output.status.success());
        assert!(String::from_utf8_lossy(&output.stdout).starts_with("git version"));
    }

    #[test]
    fn missing_repository_yields_empty_stdout() {
        let cwd = std::env::temp_dir();
        assert_eq!(git_stdout(&cwd, &["rev-parse", "--git-dir"]), "");
    }

    #[test]
    fn strips_every_repository_selecting_variable() {
        assert_eq!(
            GIT_STRIP,
            [
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_INDEX_FILE",
                "GIT_COMMON_DIR"
            ]
        );
    }
}
