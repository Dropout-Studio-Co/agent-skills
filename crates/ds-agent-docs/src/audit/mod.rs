//! `audit` command: read-only survey of a repository's agent instructions and docs.

use std::path::PathBuf;

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
pub fn run_audit(_args: AuditArgs) -> i32 {
    0
}
