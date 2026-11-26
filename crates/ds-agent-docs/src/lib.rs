//! Read-only agent-instruction audit and session-evidence digest.
//!
//! The crate is the Rust port of the `ds-agent-docs` Python helpers:
//! `audit` (instruction/docs survey), `collect` (session digest), with the
//! shared redaction, git and repository-membership core in this module tree.

#![forbid(unsafe_code)]

pub mod audit;
pub mod collect;
pub mod git;
pub mod redact;
pub mod repo;
