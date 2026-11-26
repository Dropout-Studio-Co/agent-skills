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
    match input {
        Some(data) => {
            let Some(mut stdin) = child.stdin.take() else {
                return child.wait_with_output().ok();
            };
            let data = data.as_bytes().to_vec();
            // Feed stdin from another thread so this thread drains stdout and
            // stderr at the same time: a caller that fills the stdin pipe with
            // more than one buffer while git refills stdout would otherwise
            // deadlock. A git process that stops reading is reported by its
            // exit status, and the pipe is closed when the thread returns.
            std::thread::scope(|scope| {
                scope.spawn(move || {
                    let _ = stdin.write_all(&data);
                });
                child.wait_with_output().ok()
            })
        }
        None => child.wait_with_output().ok(),
    }
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

    /// A stdin payload larger than a pipe buffer must not deadlock against a
    /// stdout payload larger than a pipe buffer.
    #[test]
    fn large_stdin_is_written_while_stdout_is_drained() {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path();
        let status = std::process::Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(root)
            .status()
            .expect("git init must run");
        assert!(status.success(), "git init failed");
        std::fs::write(root.join(".gitignore"), "ignored/\n").expect("gitignore");
        let names: Vec<String> = (0..6000)
            .map(|index| format!("ignored/some-rather-long-transcript-name-{index:05}.md"))
            .collect();
        let input = format!("{}\0", names.join("\0"));
        assert!(
            input.len() > 64 * 1024,
            "stdin fixture is {} bytes",
            input.len()
        );

        let output =
            run_git(&["check-ignore", "--stdin", "-z"], root, Some(&input)).expect("git must run");
        assert!(
            output.status.success(),
            "git check-ignore failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.len() > 32 * 1024, "stdout stayed small");
        let reported = String::from_utf8_lossy(&output.stdout)
            .split('\0')
            .filter(|token| !token.is_empty())
            .count();
        assert_eq!(reported, names.len());
    }
}
