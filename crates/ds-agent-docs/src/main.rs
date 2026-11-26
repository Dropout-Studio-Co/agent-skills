//! Command-line entry point for `ds-agent-docs`.

use std::path::PathBuf;

use clap::{Parser, Subcommand};

use ds_agent_docs::audit::{self, AuditArgs};
use ds_agent_docs::collect::{self, CollectArgs};

#[derive(Debug, Parser)]
#[command(
    name = "ds-agent-docs",
    version,
    about = "Read-only agent-instruction audit and session-evidence digest"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Survey a repository's agent instructions and docs (read-only).
    Audit {
        /// Repository root to survey.
        #[arg(long, value_name = "PATH")]
        repo: PathBuf,
        /// Optional scope inside the repository.
        #[arg(long, value_name = "PATH")]
        scope: Option<String>,
        /// Context token budget (validated by the command, not by the parser).
        #[arg(
            long = "budget-tokens",
            value_name = "N",
            default_value_t = 5000,
            allow_negative_numbers = true
        )]
        budget_tokens: i64,
        /// Skills directory inside the repository.
        #[arg(long = "skills-dir", value_name = "DIR")]
        skills_dir: Option<String>,
        /// Print the JSON payload on stdout.
        #[arg(long)]
        json: bool,
    },
    /// Collect a compact digest of past agent sessions for a repository.
    Collect {
        /// Repository root; defaults to the current checkout.
        #[arg(long, value_name = "PATH")]
        repo: Option<PathBuf>,
        /// Only sessions touched within this many days.
        #[arg(long, value_name = "N", default_value_t = 60)]
        days: i64,
        /// Maximum characters of session evidence kept.
        #[arg(long = "max-chars", value_name = "N", default_value_t = 60000)]
        max_chars: usize,
        /// Extra transcript directory to scan (repeatable).
        #[arg(long = "extra-dir", value_name = "DIR")]
        extra_dir: Vec<PathBuf>,
        /// Exit non-zero when a transcript format drifted.
        #[arg(long)]
        strict: bool,
        /// Write the evidence JSON to this path.
        #[arg(long = "evidence-out", value_name = "PATH")]
        evidence_out: Option<PathBuf>,
    },
}

fn main() {
    let code = match Cli::parse().command {
        Commands::Audit {
            repo,
            scope,
            budget_tokens,
            skills_dir,
            json,
        } => audit::run_audit(AuditArgs {
            repo,
            scope,
            budget_tokens,
            skills_dir,
            json,
        }),
        Commands::Collect {
            repo,
            days,
            max_chars,
            extra_dir,
            strict,
            evidence_out,
        } => collect::run_collect(CollectArgs {
            repo,
            days,
            max_chars,
            extra_dirs: extra_dir,
            strict,
            evidence_out,
        }),
    };
    std::process::exit(code);
}
