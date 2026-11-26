//! Integration tests for `ds-agent-docs audit`.
//!
//! Ports every scenario from `skills/ds-agent-docs/tests/test_check_instructions.py`
//! and adds a differential test that compares the Rust payload with the Python
//! reference helper on the same tree.

#![cfg(unix)]

use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;
use tempfile::TempDir;

/// The compiled binary under test.
const BIN: &str = env!("CARGO_BIN_EXE_ds-agent-docs");

/// `AGENTS.md` used by most fixtures.
const DEFAULT_AGENTS: &str = "# Fixture memory\n\nUse the documented commands.\n";

/// `README.md` used by most fixtures.
const DEFAULT_README: &str = "# Fixture\n\n```sh\npython3 -m unittest\n```\n";

struct Fixture {
    tmp: TempDir,
    repo: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let tmp = tempfile::tempdir().expect("tempdir");
        let repo = tmp.path().join("repo");
        fs::create_dir_all(&repo).expect("repo dir");
        let fixture = Self { tmp, repo };
        fixture.write("AGENTS.md", DEFAULT_AGENTS);
        fixture.write("CLAUDE.md", "@AGENTS.md\n");
        fixture.write("README.md", DEFAULT_README);
        fixture.git(&["init", "-q", "-b", "main"], Some(&fixture.repo));
        fixture.commit();
        fixture
    }

    /// Deterministic git environment for both the fixtures and the audit.
    fn env(&self) -> Vec<(&'static str, String)> {
        vec![
            ("GIT_CONFIG_GLOBAL", "/dev/null".to_string()),
            ("GIT_CONFIG_SYSTEM", "/dev/null".to_string()),
            ("GIT_AUTHOR_NAME", "fixture".to_string()),
            ("GIT_AUTHOR_EMAIL", "fixture@example.test".to_string()),
            ("GIT_COMMITTER_NAME", "fixture".to_string()),
            ("GIT_COMMITTER_EMAIL", "fixture@example.test".to_string()),
        ]
    }

    fn git(&self, args: &[&str], cwd: Option<&Path>) -> String {
        let output = Command::new("git")
            .args(args)
            .current_dir(cwd.unwrap_or(&self.repo))
            .envs(self.env())
            .output()
            .expect("git must run");
        assert!(
            output.status.success(),
            "git {args:?} failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8_lossy(&output.stdout).into_owned()
    }

    fn commit(&self) {
        self.commit_at(&self.repo);
    }

    fn commit_at(&self, repo: &Path) {
        self.git(&["add", "-A"], Some(repo));
        self.git(
            &[
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            ],
            Some(repo),
        );
    }

    fn init_repo(&self, repo: &Path, branch: &str) {
        fs::create_dir_all(repo).expect("repo dir");
        self.git(&["init", "-q", "-b", branch], Some(repo));
    }

    fn write_at(&self, repo: &Path, rel: &str, text: &str) -> PathBuf {
        let path = repo.join(rel);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("parent directories");
        }
        fs::write(&path, text).expect("fixture write");
        path
    }

    fn write(&self, rel: &str, text: &str) -> PathBuf {
        self.write_at(&self.repo, rel, text)
    }

    fn remove(&self, rel: &str) {
        fs::remove_file(self.repo.join(rel)).expect("fixture remove");
    }

    fn link(&self, rel: &str, target: &str) {
        let path = self.repo.join(rel);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("parent directories");
        }
        let _ = fs::remove_file(&path);
        symlink(target, path).expect("symlink");
    }

    fn audit_at(&self, repo: &Path, extra: &[&str]) -> (i32, Option<Value>) {
        let output = Command::new(BIN)
            .arg("audit")
            .arg("--repo")
            .arg(repo)
            .arg("--json")
            .args(extra)
            .envs(self.env())
            .output()
            .expect("the audit binary must run");
        let code = output.status.code().unwrap_or(-1);
        let value = serde_json::from_slice(&output.stdout).ok();
        (code, value)
    }

    fn audit(&self, extra: &[&str]) -> (i32, Option<Value>) {
        self.audit_at(&self.repo, extra)
    }

    fn ok_audit_at(&self, repo: &Path, extra: &[&str]) -> Value {
        let (code, value) = self.audit_at(repo, extra);
        assert_eq!(code, 0, "{value:?}");
        let value = value.expect("the audit must print a JSON payload");
        assert_eq!(value["status"], "ok", "{value}");
        value
    }

    fn ok_audit(&self, extra: &[&str]) -> Value {
        self.ok_audit_at(&self.repo, extra)
    }

    fn invalid(&self, extra: &[&str]) -> Value {
        let (code, value) = self.audit(extra);
        assert_eq!(code, 2, "{value:?}");
        let value = value.expect("invalid input must still print JSON");
        assert_eq!(value["status"], "invalid", "{value}");
        value
    }
}

fn by_path(data: &Value) -> std::collections::HashMap<String, Value> {
    let mut found = std::collections::HashMap::new();
    for item in data["inventory"].as_array().expect("inventory array") {
        let path = item["path"].as_str().expect("item path").to_string();
        found.insert(path, item.clone());
    }
    found
}

fn stale_refs(data: &Value) -> Vec<String> {
    data["references"]["stale"]
        .as_array()
        .expect("stale array")
        .iter()
        .map(|item| item["ref"].as_str().expect("ref text").to_string())
        .collect()
}

fn all_refs(data: &Value) -> Vec<String> {
    data["references"]["items"]
        .as_array()
        .expect("items array")
        .iter()
        .map(|item| item["ref"].as_str().expect("ref text").to_string())
        .collect()
}

fn count_of(data: &Value, class: &str) -> Option<u64> {
    data["references"]["counts"]
        .get(class)
        .and_then(Value::as_u64)
}

fn errors_of(section: &Value) -> Vec<(String, String)> {
    section["errors"]
        .as_array()
        .expect("errors array")
        .iter()
        .map(|item| {
            (
                item["file"].as_str().unwrap_or_default().to_string(),
                item["error"].as_str().unwrap_or_default().to_string(),
            )
        })
        .collect()
}

#[test]
fn non_git_repository_is_in_place() {
    let fixture = Fixture::new();
    let plain = fixture.tmp.path().join("plain");
    fs::create_dir_all(&plain).expect("plain dir");
    fixture.write_at(&plain, "AGENTS.md", DEFAULT_AGENTS);
    fixture.write_at(&plain, "CLAUDE.md", "@AGENTS.md\n");
    let data = fixture.ok_audit_at(&plain, &[]);
    assert_eq!(data["delivery"]["action"], "in_place");
    assert_eq!(data["delivery"]["reason"], "not a git repository");
    assert_eq!(data["delivery"]["dirty"], false);
    assert_eq!(data["repo"]["kind"], "dir");
}

#[test]
fn task_branch_is_in_place() {
    let fixture = Fixture::new();
    fixture.git(&["checkout", "-q", "-b", "feature"], None);
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "in_place");
    assert_eq!(data["delivery"]["reason"], "task branch");
}

#[test]
fn default_branch_without_a_pr_rule_is_in_place() {
    let fixture = Fixture::new();
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["repo"]["default_branch"], "main");
    assert_eq!(data["repo"]["current_branch"], "main");
    assert_eq!(data["delivery"]["action"], "in_place");
    assert_eq!(
        data["delivery"]["reason"],
        "default branch without a written PR rule"
    );
    assert_eq!(data["delivery"]["commands"], serde_json::json!([]));
}

#[test]
fn default_branch_with_a_pr_rule_uses_a_worktree() {
    let fixture = Fixture::new();
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\nAlways open a pull request before merging.\n"),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "worktree");
    let reason = data["delivery"]["reason"].as_str().expect("reason");
    assert!(reason.contains("written PR rule"), "{reason}");
    let commands = data["delivery"]["commands"]
        .as_array()
        .expect("commands")
        .iter()
        .map(|value| value.as_str().expect("command").to_string())
        .collect::<Vec<String>>();
    assert_eq!(commands.len(), 2);
    assert!(
        commands[0].starts_with("git fetch origin -- "),
        "{}",
        commands[0]
    );
    assert!(
        commands[1].starts_with("git worktree add -b docs/ds-sync-"),
        "{}",
        commands[1]
    );
    assert!(commands[1].contains("\"$HOME\""), "{}", commands[1]);
}

#[test]
fn detached_head_uses_a_worktree() {
    let fixture = Fixture::new();
    fixture.git(&["checkout", "-q", "--detach", "HEAD"], None);
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "worktree");
    assert_eq!(data["delivery"]["reason"], "detached HEAD");
    assert_eq!(data["repo"]["current_branch"], "");
    assert_eq!(
        data["delivery"]["commands"]
            .as_array()
            .expect("commands")
            .len(),
        2
    );
}

#[test]
fn dirty_memory_file_is_patch_only() {
    let fixture = Fixture::new();
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\nUncommitted edit.\n"),
    );
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "patch_only");
    assert_eq!(data["delivery"]["reason"], "dirty memory file");
    assert_eq!(data["delivery"]["dirty"], true);
}

#[test]
fn dirty_gemini_or_readme_is_patch_only() {
    let fixture = Fixture::new();
    fixture.write("GEMINI.md", "@AGENTS.md\n");
    fixture.commit();
    fixture.write("GEMINI.md", "@AGENTS.md\nDirty edit.\n");
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "patch_only");
    assert_eq!(data["delivery"]["dirty"], true);
    fixture.commit();
    fixture.write(
        "README.md",
        &format!("{DEFAULT_README}\nDirty readme edit.\n"),
    );
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["delivery"]["action"], "patch_only");
    assert_eq!(data["delivery"]["dirty"], true);
}

#[test]
fn unknown_default_branch_is_patch_only() {
    let fixture = Fixture::new();
    let trunk = fixture.tmp.path().join("trunk");
    fixture.init_repo(&trunk, "trunk");
    fixture.write_at(&trunk, "AGENTS.md", DEFAULT_AGENTS);
    fixture.write_at(&trunk, "CLAUDE.md", "@AGENTS.md\n");
    fixture.commit_at(&trunk);
    let data = fixture.ok_audit_at(&trunk, &[]);
    assert_eq!(data["repo"]["default_branch"], Value::Null);
    assert_eq!(data["delivery"]["action"], "patch_only");
    assert_eq!(data["delivery"]["reason"], "unknown default branch");
}

#[test]
fn discovers_cross_agent_surfaces() {
    let fixture = Fixture::new();
    let files: [(&str, &str); 27] = [
        ("AGENTS.override.md", "Override.\n"),
        ("CLAUDE.local.md", "Local notes.\n"),
        ("GEMINI.md", "@AGENTS.md\n"),
        (".github/copilot-instructions.md", "Read `AGENTS.md`.\n"),
        (
            ".github/instructions/ts.instructions.md",
            "---\napplyTo: \"**/*.ts\"\n---\nStrict.\n",
        ),
        (".claude/rules/api.md", "Validate inputs.\n"),
        (
            ".claude/rules/scoped.md",
            "---\npaths:\n  - \"src/**\"\n---\nScoped.\n",
        ),
        (".agents/rules/shared.md", "Shared rule.\n"),
        (
            ".cursor/rules/style.mdc",
            "---\nalwaysApply: true\n---\nTabs.\n",
        ),
        (
            ".cursor/rules/ui.mdc",
            "---\nglobs: \"*.tsx\"\nalwaysApply: false\n---\nUI.\n",
        ),
        (".cursorrules", "Legacy cursor.\n"),
        (".windsurf/rules/w.md", "Windsurf rule.\n"),
        (".clinerules", "Cline rule.\n"),
        (".claude/commands/release.md", "Release checklist.\n"),
        (".agents/commands/run.md", "Run command.\n"),
        (".claude/agents/reviewer.md", "Review.\n"),
        (".agents/agents/helper.md", "Help.\n"),
        (".claude/output-styles/tone.md", "Tone.\n"),
        (
            ".agents/skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo.\n---\nBody.\n",
        ),
        (
            ".claude/skills/tool/SKILL.md",
            "---\nname: tool\ndescription: Tool.\n---\nBody.\n",
        ),
        (
            ".codex/skills/codex-helper/SKILL.md",
            "---\nname: codex-helper\ndescription: Codex.\n---\nBody.\n",
        ),
        (
            ".gemini/skills/helper/SKILL.md",
            "---\nname: helper\ndescription: Help.\n---\nBody.\n",
        ),
        (
            ".trail/learnings/note.md",
            "---\nstatus: active\n---\nNote.\n",
        ),
        ("CONTRIBUTING.md", "Contribute.\n"),
        ("ARCHITECTURE.md", "Architecture.\n"),
        ("DEVELOPMENT.md", "Development.\n"),
        ("docs/guide.md", "Guide.\n"),
    ];
    for (rel, text) in files {
        fixture.write(rel, text);
    }
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let found = by_path(&data);
    for (rel, _text) in files {
        assert!(found.contains_key(rel), "{rel} was not discovered");
    }
    assert_eq!(found["AGENTS.md"]["category"], "memory");
    assert_eq!(found["AGENTS.md"]["agent"], "cross-agent");
    assert_eq!(found["AGENTS.md"]["always_loaded"], true);
    assert_eq!(found["CLAUDE.local.md"]["always_loaded"], true);
    assert_eq!(found["GEMINI.md"]["agent"], "gemini");
    assert_eq!(found[".github/copilot-instructions.md"]["agent"], "copilot");
    assert_eq!(
        found[".github/instructions/ts.instructions.md"]["category"],
        "rules"
    );
    assert_eq!(found[".claude/rules/api.md"]["always_loaded"], true);
    assert_eq!(found[".claude/rules/scoped.md"]["always_loaded"], false);
    assert_eq!(found[".cursor/rules/style.mdc"]["always_loaded"], true);
    assert_eq!(found[".cursor/rules/ui.mdc"]["always_loaded"], false);
    assert_eq!(found[".cursorrules"]["always_loaded"], true);
    assert_eq!(found[".claude/commands/release.md"]["category"], "commands");
    assert_eq!(found[".claude/agents/reviewer.md"]["category"], "subagents");
    assert_eq!(
        found[".claude/output-styles/tone.md"]["category"],
        "output_styles"
    );
    assert_eq!(found[".agents/skills/demo/SKILL.md"]["category"], "skills");
    assert_eq!(
        found[".codex/skills/codex-helper/SKILL.md"]["category"],
        "skills"
    );
    assert_eq!(
        found[".codex/skills/codex-helper/SKILL.md"]["agent"],
        "codex"
    );
    assert_eq!(found[".gemini/skills/helper/SKILL.md"]["agent"], "gemini");
    assert_eq!(found[".trail/learnings/note.md"]["category"], "learnings");
    assert_eq!(found["docs/guide.md"]["category"], "docs");
}

#[test]
fn scope_filters_and_refuses_escape_or_missing() {
    let fixture = Fixture::new();
    fixture.write(".claude/rules/a.md", "Rule A.\n");
    fixture.write(".claude/rules/b.md", "Rule B.\n");
    fixture.write("docs/guide.md", "Guide.\n");
    fixture.commit();
    let data = fixture.ok_audit(&["--scope", ".claude/rules"]);
    assert_eq!(data["scope"], ".claude/rules");
    let paths: Vec<String> = data["inventory"]
        .as_array()
        .expect("inventory")
        .iter()
        .map(|item| item["path"].as_str().expect("path").to_string())
        .collect();
    assert_eq!(paths, [".claude/rules/a.md", ".claude/rules/b.md"]);
    let data = fixture.ok_audit(&["--scope", "docs/guide.md"]);
    assert_eq!(
        data["inventory"]
            .as_array()
            .expect("inventory")
            .iter()
            .map(|item| item["path"].as_str().expect("path").to_string())
            .collect::<Vec<String>>(),
        ["docs/guide.md"]
    );
    for bad in ["../outside", "does/not/exist"] {
        fixture.invalid(&["--scope", bad]);
    }
    symlink(fixture.tmp.path(), fixture.repo.join("linkout")).expect("symlink");
    fixture.invalid(&["--scope", "linkout"]);
}

#[test]
fn dot_scope_means_the_whole_repository() {
    let fixture = Fixture::new();
    fixture.write(".claude/rules/a.md", "Rule A.\n");
    fixture.commit();
    for value in [".", "./"] {
        let data = fixture.ok_audit(&["--scope", value]);
        assert_eq!(data["scope"], Value::Null, "{value}");
        assert!(by_path(&data).contains_key(".claude/rules/a.md"), "{value}");
    }
}

#[test]
fn skills_dir_custom_and_escape_refusal() {
    let fixture = Fixture::new();
    fixture.write(
        "custom/skills/demo/SKILL.md",
        "---\nname: demo\ndescription: Demo.\n---\nBody.\n",
    );
    fixture.commit();
    let data = fixture.ok_audit(&["--skills-dir", "custom/skills"]);
    assert_eq!(
        by_path(&data)["custom/skills/demo/SKILL.md"]["category"],
        "skills"
    );
    for bad in ["../outside", "does/not/exist"] {
        fixture.invalid(&["--skills-dir", bad]);
    }
}

#[test]
fn prunes_symlinked_dirs_nested_repos_and_caches() {
    let fixture = Fixture::new();
    fixture.write("node_modules/pkg/AGENTS.md", "Ignored.\n");
    fixture.write("graft/cache/AGENTS.md", "Ignored.\n");
    fixture.write(".trail/cache/AGENTS.md", "Ignored.\n");
    let external = fixture.tmp.path().join("external");
    fs::create_dir_all(&external).expect("external");
    fixture.write_at(&external, "AGENTS.md", DEFAULT_AGENTS);
    symlink(&external, fixture.repo.join("linked")).expect("symlink");
    let nested = fixture.repo.join("nested");
    fs::create_dir_all(nested.join(".git")).expect("nested git");
    fixture.write_at(&nested, "AGENTS.md", DEFAULT_AGENTS);
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let paths = by_path(&data);
    for hidden in [
        "node_modules/pkg/AGENTS.md",
        "graft/cache/AGENTS.md",
        ".trail/cache/AGENTS.md",
        "linked/AGENTS.md",
        "nested/AGENTS.md",
    ] {
        assert!(!paths.contains_key(hidden), "{hidden} was not pruned");
    }
}

#[test]
fn single_budget_block_and_inode_dedup() {
    let fixture = Fixture::new();
    fixture.remove("CLAUDE.md");
    fixture.link("CLAUDE.md", "AGENTS.md");
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert!(data.get("budget").is_none());
    let expected = (DEFAULT_AGENTS.len() as u64).div_ceil(4);
    assert_eq!(data["context_load"]["always_loaded_file_tokens"], expected);
    assert_eq!(data["context_load"]["always_loaded_tokens"], expected);
    assert_eq!(data["context_load"]["budget_cap"], 5000);
    assert_eq!(data["context_load"]["over_budget"], false);
}

#[test]
fn oversized_always_loaded_file_and_budget_override() {
    let fixture = Fixture::new();
    let rules: Vec<String> = (0..320)
        .map(|index| format!("Rule line {index} for the oversized fixture."))
        .collect();
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n{}\n", rules.join("\n")),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let oversized: Vec<String> = data["context_load"]["oversized"]
        .as_array()
        .expect("oversized")
        .iter()
        .map(|item| item["path"].as_str().expect("path").to_string())
        .collect();
    assert!(
        oversized.contains(&"AGENTS.md".to_string()),
        "{oversized:?}"
    );
    let data = fixture.ok_audit(&["--budget-tokens", "10"]);
    assert_eq!(data["context_load"]["budget_cap"], 10);
    assert_eq!(data["context_load"]["over_budget"], true);
    fixture.invalid(&["--budget-tokens", "0"]);
}

#[test]
fn skill_descriptions_add_to_the_budget() {
    let fixture = Fixture::new();
    let description = "Demo skill for a fixture repository.";
    fixture.write(
        ".agents/skills/demo/SKILL.md",
        &format!("---\nname: demo\ndescription: {description}\n---\nBody.\n"),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let expected = (description.len() as u64).div_ceil(4);
    assert_eq!(data["context_load"]["skill_description_tokens"], expected);
    assert_eq!(
        data["context_load"]["always_loaded_tokens"].as_u64(),
        Some(
            data["context_load"]["always_loaded_file_tokens"]
                .as_u64()
                .expect("file tokens")
                + expected
        )
    );
}

#[test]
fn block_description_stops_at_the_next_top_level_key() {
    let fixture = Fixture::new();
    fixture.write(
        ".agents/skills/demo/SKILL.md",
        "---\nname: demo\ndescription: |\n  First line.\n  Second line.\nmetadata:\n  version: \"1.0\"\n---\nBody.\n",
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let expected = ("First line. Second line.".len() as u64).div_ceil(4);
    assert_eq!(data["context_load"]["skill_description_tokens"], expected);
}

#[test]
fn symlinked_agents_counts_resolved_lines_for_oversized() {
    let fixture = Fixture::new();
    let big: Vec<String> = (0..320).map(|index| format!("Rule {index}")).collect();
    fixture.write("docs/shared-agents.md", &format!("{}\n", big.join("\n")));
    fixture.remove("AGENTS.md");
    fixture.link("AGENTS.md", "docs/shared-agents.md");
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let oversized = data["context_load"]["oversized"]
        .as_array()
        .expect("oversized")
        .iter()
        .find(|item| item["path"] == "AGENTS.md")
        .expect("AGENTS.md must be oversized");
    assert_eq!(oversized["lines"], 320);
}

#[test]
fn disable_model_invocation_skill_has_zero_description_tokens() {
    let fixture = Fixture::new();
    fixture.write(
        ".agents/skills/manual/SKILL.md",
        "---\nname: manual\ndescription: Manual-only workflow.\ndisable-model-invocation: true\n---\nBody.\n",
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(data["context_load"]["skill_description_tokens"], 0);
    assert_eq!(
        by_path(&data)[".agents/skills/manual/SKILL.md"]["disable_model_invocation"],
        true
    );
}

#[test]
fn first_non_comment_line_passes() {
    let fixture = Fixture::new();
    fixture.write("CLAUDE.md", "<!-- bridge -->\n@AGENTS.md\n");
    fixture.commit();
    assert_eq!(fixture.ok_audit(&[])["import"]["ok"], true);
}

#[test]
fn multi_line_html_comment_before_the_import_passes() {
    let fixture = Fixture::new();
    fixture.write("CLAUDE.md", "<!--\nline 2\n-->\n@AGENTS.md\n");
    fixture.commit();
    assert_eq!(fixture.ok_audit(&[])["import"]["ok"], true);
}

#[test]
fn symlink_to_sibling_agents_passes() {
    let fixture = Fixture::new();
    fixture.remove("CLAUDE.md");
    fixture.link("CLAUDE.md", "AGENTS.md");
    fixture.commit();
    assert_eq!(fixture.ok_audit(&[])["import"]["ok"], true);
}

#[test]
fn backticked_import_fails() {
    let fixture = Fixture::new();
    fixture.write("CLAUDE.md", "`@AGENTS.md`\n");
    fixture.commit();
    let errors = errors_of(&fixture.ok_audit(&[])["import"]);
    assert!(errors.contains(&("CLAUDE.md".to_string(), "backticked import".to_string())));
}

#[test]
fn missing_claude_warns_without_claude_surfaces_and_errors_with_them() {
    let fixture = Fixture::new();
    fixture.remove("CLAUDE.md");
    fixture.commit();
    let report = fixture.ok_audit(&[]);
    let import = &report["import"];
    assert_eq!(import["ok"], true);
    assert_eq!(import["errors"], serde_json::json!([]));
    let warnings = import["warnings"].as_array().expect("warnings");
    assert!(warnings.contains(&serde_json::json!({
        "file": "CLAUDE.md",
        "error": "missing CLAUDE.md import",
    })));
    fixture.write(".claude/rules/api.md", "Validate inputs.\n");
    fixture.commit();
    let import = fixture.ok_audit(&[])["import"].clone();
    assert_eq!(import["ok"], false);
    assert!(errors_of(&import).contains(&(
        "CLAUDE.md".to_string(),
        "missing CLAUDE.md import".to_string()
    )));
    fixture.write("CLAUDE.md", "@AGENTS.md\n");
    fixture.remove("AGENTS.md");
    fixture.commit();
    let import = fixture.ok_audit(&[])["import"].clone();
    assert!(
        errors_of(&import).contains(&("AGENTS.md".to_string(), "missing AGENTS.md".to_string()))
    );
}

#[test]
fn wrong_symlink_fails() {
    let fixture = Fixture::new();
    fixture.remove("CLAUDE.md");
    fixture.link("CLAUDE.md", "README.md");
    fixture.commit();
    let errors = errors_of(&fixture.ok_audit(&[])["import"]);
    assert!(errors.contains(&(
        "CLAUDE.md".to_string(),
        "symlink points elsewhere".to_string()
    )));
}

#[test]
fn duplicated_agents_line_fails() {
    let fixture = Fixture::new();
    let line = "Run the full integration suite before merging any release branch.";
    fixture.write("AGENTS.md", &format!("{DEFAULT_AGENTS}\n{line}\n"));
    fixture.write("CLAUDE.md", &format!("@AGENTS.md\n{line}\n"));
    fixture.commit();
    let errors = errors_of(&fixture.ok_audit(&[])["import"]);
    assert!(
        errors
            .iter()
            .any(|(_file, error)| error == "line duplicated from AGENTS.md"),
        "{errors:?}"
    );
}

#[test]
fn nested_memory_files_are_checked() {
    let fixture = Fixture::new();
    fixture.write("nested/AGENTS.md", DEFAULT_AGENTS);
    fixture.write("nested/CLAUDE.md", "@AGENTS.md\n");
    fixture.commit();
    assert_eq!(fixture.ok_audit(&[])["import"]["ok"], true);
    fixture.write("nested/CLAUDE.md", "See nested rules.\n");
    fixture.commit();
    let errors = errors_of(&fixture.ok_audit(&[])["import"]);
    assert!(errors.contains(&(
        "nested/CLAUDE.md".to_string(),
        "missing @AGENTS.md import".to_string()
    )));
}

fn base_manifest(fixture: &Fixture) {
    fixture.write(
        "package.json",
        "{\"name\": \"fixture\", \"scripts\": {\"build\": \"echo ok\"}}\n",
    );
    fixture.write("Makefile", "test:\n\techo ok\n");
    fixture.commit();
}

#[test]
fn catches_broken_links_paths_and_manifest_targets() {
    let fixture = Fixture::new();
    base_manifest(&fixture);
    fixture.write(
        "AGENTS.md",
        &format!(
            "{DEFAULT_AGENTS}\n- [bad](missing.md)\n- `./missing/file.py`\n- `npm run nope`\n- `make nope`\n- `npm run build`\n- `make test`\n"
        ),
    );
    fixture.commit();
    let stale = stale_refs(&fixture.ok_audit(&[]));
    for bad in [
        "missing.md",
        "./missing/file.py",
        "npm run nope",
        "make nope",
    ] {
        assert!(
            stale.contains(&bad.to_string()),
            "{bad} missing from {stale:?}"
        );
    }
    for good in ["npm run build", "make test"] {
        assert!(!stale.contains(&good.to_string()), "{good} in {stale:?}");
    }
}

#[test]
fn mdc_cfg_ini_and_env_references_classify_as_stale() {
    let fixture = Fixture::new();
    fixture.write(
        "AGENTS.md",
        &format!(
            "{DEFAULT_AGENTS}\n- [style](rules/style.mdc)\n- [config](config/app.env)\n- `settings/app.cfg`\n- `settings/app.ini`\n"
        ),
    );
    fixture.commit();
    let stale = stale_refs(&fixture.ok_audit(&[]));
    for bad in [
        "rules/style.mdc",
        "config/app.env",
        "settings/app.cfg",
        "settings/app.ini",
    ] {
        assert!(
            stale.contains(&bad.to_string()),
            "{bad} missing from {stale:?}"
        );
    }
}

#[test]
fn stated_no_push_rules_use_a_worktree() {
    let fixture = Fixture::new();
    for rule in [
        "No direct commits to main",
        "Never pushing directly to main",
    ] {
        fixture.write("AGENTS.md", &format!("{DEFAULT_AGENTS}\n{rule}.\n"));
        fixture.commit();
        let data = fixture.ok_audit(&[]);
        assert_eq!(
            data["delivery"]["action"], "worktree",
            "{rule} must use a worktree: {data}"
        );
        assert_eq!(
            data["delivery"]["reason"], "default branch with a written PR rule",
            "{rule}"
        );
    }
}

#[test]
fn high_precision_avoids_common_false_positives() {
    let fixture = Fixture::new();
    base_manifest(&fixture);
    for rel in ["SKILL.md", "task-profile.json", "docs/guide.md"] {
        fixture.write(rel, "placeholder\n");
    }
    fixture.write(".gitignore", ".env.local\n");
    fixture.write(
        "AGENTS.md",
        &format!(
            "{DEFAULT_AGENTS}\n- `SKILL.md` and `task-profile.json`\n- `docs/guide.md`\n- `Move.target`\n- `Dropout-Studio-Co/ds-agent-skills`\n- `skills/<name>`\n- `https://example.dev/path`\n- [site](https://example.dev/docs)\n- `.env.local`\n- `npm run build` and `make test`\n"
        ),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(stale_refs(&data), Vec::<String>::new());
    let refs = all_refs(&data);
    assert!(refs.contains(&"Move.target".to_string()), "{refs:?}");
    assert!(
        refs.contains(&"Dropout-Studio-Co/ds-agent-skills".to_string()),
        "{refs:?}"
    );
}

#[test]
fn gitignored_missing_markdown_link_is_not_stale() {
    let fixture = Fixture::new();
    fixture.write(".gitignore", "generated/**\n");
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n[generated](generated/index.md)\n"),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(stale_refs(&data), Vec::<String>::new());
    assert_eq!(count_of(&data, "ignored"), Some(1));
}

#[test]
fn cli_flags_and_make_options_are_not_classified() {
    let fixture = Fixture::new();
    base_manifest(&fixture);
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n- `make --help`\n- pass `--json` for machine output\n"),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let refs = all_refs(&data);
    assert!(!refs.contains(&"make --help".to_string()), "{refs:?}");
    assert!(!refs.contains(&"--json".to_string()), "{refs:?}");
    assert_eq!(stale_refs(&data), Vec::<String>::new());
    assert_eq!(count_of(&data, "scoped"), None);
}

#[test]
fn shorthand_package_scripts_and_script_runners() {
    let fixture = Fixture::new();
    base_manifest(&fixture);
    fixture.write("scripts/present.py", "print(\"ok\")\n");
    fixture.write("scripts/present.sh", "echo ok\n");
    fixture.write(
        "AGENTS.md",
        &format!(
            "{DEFAULT_AGENTS}\n```sh\npnpm build\nbun build\nyarn build\npnpm nope\nbun nope\nyarn nope\npnpm install\nbun add vitest\npython3 scripts/present.py\npython3 scripts/missing.py\nbash scripts/present.sh\nbash scripts/missing.sh\npython3 -m unittest\n```\n"
        ),
    );
    fixture.commit();
    let stale = stale_refs(&fixture.ok_audit(&[]));
    for bad in [
        "pnpm nope",
        "bun nope",
        "yarn nope",
        "python3 scripts/missing.py",
        "bash scripts/missing.sh",
    ] {
        assert!(
            stale.contains(&bad.to_string()),
            "{bad} missing from {stale:?}"
        );
    }
    for good in [
        "pnpm build",
        "bun build",
        "yarn build",
        "pnpm install",
        "bun add vitest",
        "python3 scripts/present.py",
        "bash scripts/present.sh",
        "python3 -m unittest",
    ] {
        assert!(!stale.contains(&good.to_string()), "{good} in {stale:?}");
    }
}

#[test]
fn many_unresolved_references_are_batched_into_one_ignore_lookup() {
    let fixture = Fixture::new();
    let mut lines: Vec<String> = (0..3)
        .map(|index| format!("- [generated {index}](generated/file-{index}.md)"))
        .collect();
    lines.extend((0..3).map(|index| format!("- [cache {index}](cache/file-{index}.md)")));
    fixture.write(".gitignore", "generated/\ncache/\n");
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n{}\n", lines.join("\n")),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(count_of(&data, "ignored"), Some(6));
    assert_eq!(stale_refs(&data), Vec::<String>::new());
}

#[test]
fn non_git_repository_keeps_missing_references_stale() {
    let fixture = Fixture::new();
    let plain = fixture.tmp.path().join("plain");
    fs::create_dir_all(&plain).expect("plain dir");
    fixture.write_at(
        &plain,
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n- [gone](./gone/missing.md)\n"),
    );
    fixture.write_at(&plain, "CLAUDE.md", "@AGENTS.md\n");
    let data = fixture.ok_audit_at(&plain, &[]);
    assert!(stale_refs(&data).contains(&"./gone/missing.md".to_string()));
    assert_eq!(count_of(&data, "ignored"), None);
}

#[test]
fn traversal_ref_does_not_poison_gitignored_batch() {
    let fixture = Fixture::new();
    fixture.write(".gitignore", "generated/\n");
    fixture.write(
        "AGENTS.md",
        &format!(
            "{DEFAULT_AGENTS}\n- [generated](generated/index.md)\n- [outside](./../outside.md)\n"
        ),
    );
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    assert_eq!(count_of(&data, "ignored"), Some(1));
    assert!(!stale_refs(&data).contains(&"generated/index.md".to_string()));
}

#[test]
fn dangling_imports_are_reported() {
    let fixture = Fixture::new();
    fixture.write(
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n@docs/missing.md\n"),
    );
    fixture.commit();
    let dangling = fixture.ok_audit(&[])["structure"]["dangling_imports"].clone();
    let array = dangling.as_array().expect("dangling array");
    assert_eq!(array.len(), 1, "{dangling}");
    assert_eq!(array[0]["import"], "@docs/missing.md");
}

#[test]
fn skill_frontmatter_is_validated() {
    let fixture = Fixture::new();
    fixture.write(
        ".agents/skills/wrong/SKILL.md",
        "---\nname: other\n---\nBody.\n",
    );
    fixture.write(".agents/skills/plain/SKILL.md", "No frontmatter.\n");
    fixture.write(
        ".agents/skills/good/SKILL.md",
        "---\nname: good\ndescription: Good skill.\n---\nBody.\n",
    );
    fixture.commit();
    let issues = fixture.ok_audit(&[])["structure"]["skill_frontmatter"].clone();
    let pairs: Vec<(String, String)> = issues
        .as_array()
        .expect("issues array")
        .iter()
        .map(|item| {
            (
                item["file"].as_str().unwrap_or_default().to_string(),
                item["error"].as_str().unwrap_or_default().to_string(),
            )
        })
        .collect();
    assert!(
        pairs
            .iter()
            .any(|(_file, error)| error.contains("does not match folder"))
    );
    assert!(
        pairs
            .iter()
            .any(|(_file, error)| error == "missing YAML frontmatter")
    );
    assert!(
        !pairs
            .iter()
            .any(|(file, _error)| file == ".agents/skills/good/SKILL.md")
    );
}

#[test]
fn cross_file_duplicates_are_capped_and_located() {
    let fixture = Fixture::new();
    let line = "Always run the full integration suite before pushing any release branch.";
    fixture.write("AGENTS.md", &format!("{DEFAULT_AGENTS}\n{line}\n"));
    fixture.write("GEMINI.md", &format!("# Gemini\n\n{line}\n"));
    fixture.commit();
    let duplicates = fixture.ok_audit(&[])["structure"]["duplicates"].clone();
    let array = duplicates.as_array().expect("duplicates array");
    assert_eq!(array.len(), 1, "{duplicates}");
    let files: Vec<&str> = array[0]["locations"]
        .as_array()
        .expect("locations")
        .iter()
        .map(|spot| spot["file"].as_str().expect("file"))
        .collect();
    assert!(files.contains(&"AGENTS.md"), "{files:?}");
    assert!(files.contains(&"GEMINI.md"), "{files:?}");
}

#[test]
fn legacy_rule_overlaps_are_reported() {
    let fixture = Fixture::new();
    fixture.write(".cursorrules", "Legacy.\n");
    fixture.write(
        ".cursor/rules/modern.mdc",
        "---\nalwaysApply: false\n---\nModern.\n",
    );
    fixture.write(".windsurfrules", "Legacy.\n");
    fixture.write(".windsurf/rules/modern.md", "Modern.\n");
    fixture.commit();
    let overlaps = fixture.ok_audit(&[])["structure"]["legacy_overlaps"].clone();
    let legacy: Vec<&str> = overlaps
        .as_array()
        .expect("overlaps array")
        .iter()
        .map(|item| item["legacy"].as_str().expect("legacy"))
        .collect();
    assert_eq!(legacy.len(), 2, "{overlaps}");
    assert!(legacy.contains(&".cursorrules"), "{legacy:?}");
    assert!(legacy.contains(&".windsurfrules"), "{legacy:?}");
}

#[test]
fn raw_home_paths_and_secrets_are_redacted() {
    let fixture = Fixture::new();
    let secret = format!("{}p_{}", "gh", "a".repeat(24));
    let home = format!("/{}/alice/private notes.", "Users");
    fixture.write(
        ".claude/rules/risky.md",
        &format!("Never commit {home}\ntoken={secret}\n"),
    );
    fixture.write(
        ".claude/rules/clean.md",
        "Contact dev@example.com for help.\n",
    );
    fixture.commit();
    let hits = fixture.ok_audit(&[])["hygiene"]["redaction_hits"].clone();
    let risky: Vec<&Value> = hits
        .as_array()
        .expect("hits array")
        .iter()
        .filter(|hit| hit["file"] == ".claude/rules/risky.md")
        .collect();
    assert_eq!(risky.len(), 2, "{hits}");
    for hit in risky {
        let text = hit["redacted"].as_str().expect("redacted text");
        assert!(text.contains("[REDACTED]"), "{text}");
    }
    assert!(
        !hits
            .as_array()
            .expect("hits array")
            .iter()
            .any(|hit| hit["file"] == ".claude/rules/clean.md"),
        "{hits}"
    );
}

#[test]
fn clean_instructions_have_no_hits() {
    let fixture = Fixture::new();
    assert_eq!(
        fixture.ok_audit(&[])["hygiene"]["redaction_hits"],
        serde_json::json!([])
    );
}

#[test]
fn bun_builtin_test_and_eval_flags_are_not_stale() {
    let fixture = Fixture::new();
    fixture.write(
        "package.json",
        "{\"name\": \"fixture\", \"scripts\": {\"lint\": \"echo ok\"}}\n",
    );
    fixture.write(
        "AGENTS.md",
        "# Notes\n\n```sh\nbun test\nbun build\nnode -e \"console.log('a/b')\"\nperl -e 's/foo/bar/'\n```\n",
    );
    fixture.commit();
    let stale: Vec<Value> = fixture.ok_audit(&[])["references"]["stale"]
        .as_array()
        .expect("stale")
        .iter()
        .filter(|item| item["file"] == "AGENTS.md")
        .cloned()
        .collect();
    assert_eq!(stale, Vec::<Value>::new());
}

#[test]
fn docs_coverage_reports_manifests_and_gaps() {
    let fixture = Fixture::new();
    fixture.write("package.json", "{\"name\": \"fixture\", \"scripts\": {}}\n");
    fixture.write("Makefile", "test:\n\techo ok\n");
    fixture.write("CONTRIBUTING.md", "Contribute.\n");
    fixture.write("docs/architecture.md", "Architecture.\n");
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let coverage = &data["docs_coverage"];
    let manifests: Vec<&str> = coverage["manifests"]
        .as_array()
        .expect("manifests")
        .iter()
        .map(|name| name.as_str().expect("name"))
        .collect();
    assert!(manifests.contains(&"package.json"), "{manifests:?}");
    assert!(manifests.contains(&"Makefile"), "{manifests:?}");
    let present: Vec<&str> = coverage["present_docs"]
        .as_array()
        .expect("present docs")
        .iter()
        .map(|name| name.as_str().expect("name"))
        .collect();
    assert!(present.contains(&"AGENTS.md"), "{present:?}");
    assert!(present.contains(&"CONTRIBUTING.md"), "{present:?}");
    assert_eq!(coverage["missing_recommended_docs"], serde_json::json!([]));
    assert_eq!(coverage["has_command_examples"], true);
    assert!(
        coverage["docs_file_count"].as_u64().expect("count") >= 3,
        "{coverage}"
    );
}

#[test]
fn missing_recommended_docs_are_reported() {
    let fixture = Fixture::new();
    fixture.remove("README.md");
    fixture.commit();
    let coverage = fixture.ok_audit(&[])["docs_coverage"].clone();
    let missing: Vec<&str> = coverage["missing_recommended_docs"]
        .as_array()
        .expect("missing docs")
        .iter()
        .map(|name| name.as_str().expect("name"))
        .collect();
    assert!(missing.contains(&"README.md"), "{missing:?}");
    assert_eq!(coverage["has_command_examples"], false);
}

/// A fixture mimicking the `ds-agent-skills` repository's own memory files.
const SELF_AGENTS: &str = "# ds-agent-skills - notes for agents

`skills/ds-agent-docs/scripts/check_instructions.py` runs a read-only audit.
`scripts/collect_sessions.py` collects evidence. See [AGENTS.md](./AGENTS.md).

```sh
python3 -m unittest discover -s skills/ds-deps-upgrade/tests -t skills/ds-deps-upgrade
bash skills/ds-dev-protocol/tests/smoke.sh
diff -rq -x __pycache__ -x graft skills/<name> ~/.agents/skills/<name>
```

Skills live under `skills/<name>` and keep `SKILL.md` and `task-profile.json`.
Scripts: `scripts/depup.py`, `scripts/review_task.py`, `scripts/collect_sessions.py`,
`scripts/check_instructions.py`, `scripts/gate.sh`, `scripts/premerge-and-merge.sh`,
`scripts/implement.sh`, `tests/smoke.sh`, `tests/implement-smoke.sh`.
State: `runs.jsonl`, `state.json`, `launchd.log`, `.env`, `.DS_Store`.

A GitHub slug such as `Dropout-Studio-Co/ds-agent-skills` is not a path, and `Move.target` is prose.
";

const SELF_CONTRIBUTING: &str = "# Contributing

`ds-consolidate` and `ds-ui-overhaul` resolve `../ds-deps-upgrade/scripts/review_task.py`
and `task-profile.json`. Read [AGENTS.md](./AGENTS.md) for sync rules.

[Conventional Commits](https://www.conventionalcommits.org/) and [MIT](./LICENSE).
";

#[test]
fn agent_skills_fixture_has_no_stale_references() {
    let fixture = Fixture::new();
    fixture.write("AGENTS.md", SELF_AGENTS);
    fixture.write("CONTRIBUTING.md", SELF_CONTRIBUTING);
    fixture.write("LICENSE", "MIT\n");
    for rel in [
        "task-profile.json",
        "skills/ds-deps-upgrade/scripts/review_task.py",
        "skills/ds-deps-upgrade/scripts/depup.py",
        "skills/ds-agent-docs/scripts/collect_sessions.py",
        "skills/ds-agent-docs/scripts/check_instructions.py",
        "skills/ds-dev-protocol/scripts/gate.sh",
        "skills/ds-dev-protocol/scripts/premerge-and-merge.sh",
        "skills/ds-dev-protocol/scripts/implement.sh",
        "skills/ds-dev-protocol/tests/smoke.sh",
        "skills/ds-dev-protocol/tests/implement-smoke.sh",
    ] {
        fixture.write(rel, "placeholder\n");
    }
    for rel in [
        "skills/ds-deps-upgrade/tests",
        "skills/ds-dev-protocol/tests",
    ] {
        fs::create_dir_all(fixture.repo.join(rel)).expect("tests dir");
    }
    fixture.commit();
    let data = fixture.ok_audit(&[]);
    let stale: Vec<Value> = data["references"]["stale"]
        .as_array()
        .expect("stale")
        .iter()
        .filter(|item| item["file"] == "AGENTS.md" || item["file"] == "CONTRIBUTING.md")
        .cloned()
        .collect();
    assert_eq!(stale, Vec::<Value>::new());
    assert_eq!(data["import"]["ok"], true);
    assert_eq!(data["structure"]["dangling_imports"], serde_json::json!([]));
}

#[test]
fn invalid_inputs_exit_two_with_json() {
    let fixture = Fixture::new();
    let missing = fixture.tmp.path().join("missing");
    let (code, value) = fixture.audit_at(&missing, &[]);
    assert_eq!(code, 2);
    assert_eq!(value.expect("payload")["status"], "invalid");
    fixture.invalid(&["--budget-tokens", "-1"]);
}

#[test]
fn audit_is_read_only() {
    let fixture = Fixture::new();
    let before = fixture.git(&["status", "--porcelain"], None);
    fixture.ok_audit(&[]);
    let after = fixture.git(&["status", "--porcelain"], None);
    assert_eq!(before, after);
}

#[test]
fn legacy_subcommands_are_gone() {
    let fixture = Fixture::new();
    for command in ["check", "stage", "gate", "apply"] {
        let output = Command::new(BIN)
            .arg(command)
            .arg("--repo")
            .arg(&fixture.repo)
            .envs(fixture.env())
            .output()
            .expect("binary must run");
        assert_eq!(output.status.code(), Some(2), "{command}");
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(!stdout.contains("\"status\": \"ok\""), "{command}");
    }
}

#[test]
fn payload_is_pretty_printed_with_sorted_keys() {
    let fixture = Fixture::new();
    let output = Command::new(BIN)
        .arg("audit")
        .arg("--repo")
        .arg(&fixture.repo)
        .arg("--json")
        .envs(fixture.env())
        .output()
        .expect("binary must run");
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.starts_with("{\n"), "{stdout}");
    assert!(stdout.ends_with("}\n"), "output must end with a newline");
    let top_level: Vec<&str> = stdout
        .lines()
        .filter(|line| line.starts_with("  \""))
        .filter_map(|line| {
            let rest = line.strip_prefix("  \"")?;
            rest.split('"').next()
        })
        .collect();
    assert!(!top_level.is_empty(), "{stdout}");
    let mut sorted = top_level.clone();
    sorted.sort_unstable();
    assert_eq!(top_level, sorted, "top-level keys must be sorted");
}

/// Write one row-per-surface repository that exercises most audit branches.
fn build_rich_fixture(fixture: &Fixture) {
    fixture.write(
        "AGENTS.md",
        "# Fixture memory\n\nUse the documented commands.\n\nAlways open a pull request before merging.\n\n- [bad](missing.md)\n- [generated](generated/index.md)\n- `./missing/file.py`\n- `npm run nope`\n- `make nope`\n- `npm run build`\n- `make test`\n- `SKILL.md` and `task-profile.json`\n- `docs/guide.md`\n- `Move.target`\n- `Dropout-Studio-Co/ds-agent-skills`\n- `skills/<name>`\n- `https://example.dev/path`\n- `.env.local`\n- `make --help`\n- `docs/`\n\n```sh\npnpm build\nbun build\npnpm nope\npython3 scripts/present.py\npython3 scripts/missing.py\nbash scripts/present.sh\nbun test\nnode -e \"console.log('a/b')\"\n```\n\n@docs/missing.md\n\nAlways run the full integration suite before pushing any release branch.\n",
    );
    fixture.write(
        "GEMINI.md",
        "# Gemini\n\nAlways run the full integration suite before pushing any release branch.\n",
    );
    fixture.write("AGENTS.override.md", "Override.\n");
    fixture.write("CLAUDE.local.md", "Local notes.\n");
    fixture.write(
        "CONTRIBUTING.md",
        "# Contributing\n\nRead [AGENTS.md](./AGENTS.md) for sync rules.\n",
    );
    fixture.write("ARCHITECTURE.md", "Architecture.\n");
    fixture.write("docs/guide.md", "Guide.\n");
    fixture.write(".github/copilot-instructions.md", "Read `AGENTS.md`.\n");
    fixture.write(
        ".github/instructions/ts.instructions.md",
        "---\napplyTo: \"**/*.ts\"\n---\nStrict.\n",
    );
    fixture.write(".claude/rules/api.md", "Validate inputs.\n");
    fixture.write(
        ".claude/rules/scoped.md",
        "---\npaths:\n  - \"src/**\"\n---\nScoped.\n",
    );
    fixture.write(".agents/rules/shared.md", "Shared rule.\n");
    fixture.write(
        ".cursor/rules/style.mdc",
        "---\nalwaysApply: true\n---\nTabs.\n",
    );
    fixture.write(
        ".cursor/rules/ui.mdc",
        "---\nglobs: \"*.tsx\"\nalwaysApply: false\n---\nUI.\n",
    );
    fixture.write(".cursorrules", "Legacy cursor.\n");
    fixture.write(".windsurf/rules/w.md", "Windsurf rule.\n");
    fixture.write(".clinerules", "Cline rule.\n");
    fixture.write(".claude/commands/release.md", "Release checklist.\n");
    fixture.write(".claude/agents/reviewer.md", "Review.\n");
    fixture.write(".claude/output-styles/tone.md", "Tone.\n");
    fixture.write(
        ".agents/skills/demo/SKILL.md",
        "---\nname: demo\ndescription: |\n  First line.\n  Second line.\nmetadata:\n  version: \"1.0\"\n---\nBody.\n",
    );
    fixture.write(
        ".agents/skills/manual/SKILL.md",
        "---\nname: manual\ndescription: Manual-only workflow.\ndisable-model-invocation: true\n---\nBody.\n",
    );
    fixture.write(
        ".agents/skills/wrong/SKILL.md",
        "---\nname: other\n---\nBody.\n",
    );
    fixture.write(".agents/skills/plain/SKILL.md", "No frontmatter.\n");
    fixture.write(
        ".claude/skills/tool/SKILL.md",
        "---\nname: tool\ndescription: Tool.\n---\nBody.\n",
    );
    fixture.write(
        ".codex/skills/codex-helper/SKILL.md",
        "---\nname: codex-helper\ndescription: Codex.\n---\nBody.\n",
    );
    fixture.write(
        ".gemini/skills/helper/SKILL.md",
        "---\nname: helper\ndescription: Help.\n---\nBody.\n",
    );
    fixture.write(
        ".trail/learnings/note.md",
        "---\nstatus: active\n---\nNote.\n",
    );
    fixture.write(".trail/cache/AGENTS.md", "Ignored.\n");
    fixture.write("node_modules/pkg/AGENTS.md", "Ignored.\n");
    fixture.write("docs/architecture.md", "Architecture doc.\n");
    fixture.write(
        "package.json",
        "{\"name\": \"fixture\", \"scripts\": {\"build\": \"echo ok\"}}\n",
    );
    fixture.write("Makefile", "test:\n\techo ok\n");
    fixture.write("scripts/present.py", "present\n");
    fixture.write("scripts/present.sh", "echo ok\n");
    fixture.write("task-profile.json", "placeholder\n");
    fixture.write(".gitignore", ".env.local\ngenerated/\n");
    let secret = format!("{}p_{}", "gh", "b".repeat(24));
    let home = format!("/{}/alice/private notes.", "Users");
    fixture.write(
        ".claude/rules/risky.md",
        &format!("Never commit {home}\ntoken={secret}\n"),
    );
    let oversized: Vec<String> = (0..320)
        .map(|index| format!("Rule line {index} for the oversized fixture."))
        .collect();
    fixture.write(
        "AGENTS.md",
        &format!(
            "{}\n{}\n",
            fs::read_to_string(fixture.repo.join("AGENTS.md")).expect("agents"),
            oversized.join("\n")
        ),
    );
    let nested = fixture.repo.join("nested");
    fs::create_dir_all(nested.join(".git")).expect("nested git");
    fixture.write_at(&nested, "AGENTS.md", DEFAULT_AGENTS);
    fixture.commit();
    // Leave the tree dirty: a modified memory file and a symlinked bridge.
    fixture.write("AGENTS.override.md", "Dirty override.\n");
    fixture.remove("CLAUDE.md");
    fixture.link("CLAUDE.md", "AGENTS.md");
    let external = fixture.tmp.path().join("external");
    fs::create_dir_all(&external).expect("external");
    fixture.write_at(&external, "AGENTS.md", DEFAULT_AGENTS);
    symlink(&external, fixture.repo.join("linked")).expect("symlink");
}

fn mask_timestamps(value: &Value) -> Value {
    let mut value = value.clone();
    if let Some(commands) = value
        .get_mut("delivery")
        .and_then(|delivery| delivery.get_mut("commands"))
        .and_then(Value::as_array_mut)
    {
        for command in commands.iter_mut() {
            if let Some(text) = command.as_str() {
                *command = Value::String(mask_stamp(text));
            }
        }
    }
    value
}

fn mask_stamp(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut index = 0;
    while index < bytes.len() {
        if looks_like_stamp(bytes, index) {
            out.push_str("<STAMP>");
            index += 16;
            continue;
        }
        let character = text[index..].chars().next().expect("char boundary");
        out.push(character);
        index += character.len_utf8();
    }
    out
}

fn looks_like_stamp(bytes: &[u8], start: usize) -> bool {
    let end = start + 16;
    if end > bytes.len() {
        return false;
    }
    let stamp = &bytes[start..end];
    stamp[..8].iter().all(u8::is_ascii_digit)
        && stamp[8] == b'T'
        && stamp[9..15].iter().all(u8::is_ascii_digit)
        && stamp[15] == b'Z'
}

/// Path to the Python reference helper.
fn python_script() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../skills/ds-agent-docs/scripts/check_instructions.py")
}

/// Run the Python reference audit, or `None` when it cannot run here.
fn run_python(repo: &Path, extra: &[&str]) -> Option<(i32, Value)> {
    let script = python_script();
    if !script.is_file() {
        eprintln!("skipping parity: {} is missing", script.display());
        return None;
    }
    let output = Command::new("python3")
        .arg(&script)
        .arg("audit")
        .arg("--repo")
        .arg(repo)
        .arg("--json")
        .args(extra)
        .current_dir(repo)
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .output()
        .ok()?;
    let code = output.status.code().unwrap_or(-1);
    let value = serde_json::from_slice(&output.stdout).ok()?;
    Some((code, value))
}

/// Run the Rust audit with the same clean git environment.
fn run_rust(repo: &Path, extra: &[&str]) -> (i32, Value) {
    let output = Command::new(BIN)
        .arg("audit")
        .arg("--repo")
        .arg(repo)
        .arg("--json")
        .args(extra)
        .current_dir(repo)
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .output()
        .expect("the audit binary must run");
    let code = output.status.code().unwrap_or(-1);
    let value = serde_json::from_slice(&output.stdout).expect("audit JSON");
    (code, value)
}

fn assert_parity(repo: &Path, extra: &[&str]) {
    let Some((python_code, python)) = run_python(repo, extra) else {
        return;
    };
    let (rust_code, rust) = run_rust(repo, extra);
    assert_eq!(python_code, rust_code, "exit codes differ");
    assert_eq!(
        mask_timestamps(&python),
        mask_timestamps(&rust),
        "payloads differ for {repo:?} {extra:?}"
    );
}

#[test]
fn parity_with_the_python_reference_on_a_rich_fixture() {
    let fixture = Fixture::new();
    build_rich_fixture(&fixture);
    assert_parity(&fixture.repo, &[]);
    assert_parity(&fixture.repo, &["--scope", ".claude/rules"]);
    assert_parity(&fixture.repo, &["--budget-tokens", "10"]);
}

#[test]
fn parity_on_a_plain_directory_and_invalid_inputs() {
    let fixture = Fixture::new();
    let plain = fixture.tmp.path().join("plain");
    fs::create_dir_all(&plain).expect("plain dir");
    fixture.write_at(
        &plain,
        "AGENTS.md",
        &format!("{DEFAULT_AGENTS}\n- [gone](./gone/missing.md)\n"),
    );
    fixture.write_at(&plain, "CLAUDE.md", "@AGENTS.md\n");
    assert_parity(&plain, &[]);
    assert_parity(&fixture.repo, &["--scope", "does/not/exist"]);
    assert_parity(&fixture.repo, &["--budget-tokens", "0"]);
}

#[test]
fn parity_with_the_python_reference_on_this_repository() {
    // The worktree can be mutated by sibling agents between the two runs, so a
    // transient disagreement is retried before it counts as a real difference.
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("repository root")
        .to_path_buf();
    if !python_script().is_file() {
        eprintln!("skipping parity: {} is missing", python_script().display());
        return;
    }
    let extra = ["--skills-dir", "skills"];
    let mut last: Option<(Value, Value)> = None;
    for _attempt in 0..3 {
        let Some((python_code, python)) = run_python(&repo_root, &extra) else {
            return;
        };
        let (rust_code, rust) = run_rust(&repo_root, &extra);
        assert_eq!(python_code, rust_code, "exit codes differ");
        let (python, rust) = (mask_timestamps(&python), mask_timestamps(&rust));
        if python == rust {
            return;
        }
        last = Some((python, rust));
    }
    let (python, rust) = last.expect("attempted parity");
    panic!(
        "payloads differ\npython: {}\nrust:   {}",
        serde_json::to_string(&python).expect("python json"),
        serde_json::to_string(&rust).expect("rust json")
    );
}
