//! `collect` command: compact digest of past agent sessions for one repository.

use std::path::PathBuf;

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

/// Run the collector and return its process exit code.
pub fn run_collect(_args: CollectArgs) -> i32 {
    0
}
