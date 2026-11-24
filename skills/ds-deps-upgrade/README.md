# ds-deps-upgrade (Agent Skill)

Runs a complete, safe dependency upgrade from one invocation (analyze, research, plan,
upgrade, migrate, test, review, fix, verify, deliver) in any repository, from any supported
coding harness. This directory is the source of truth; `~/.agents/skills/ds-deps-upgrade/`
is the installed copy kept in sync from the repository (see [Repository workflow](#repository-workflow)).

## Invoke

| Harness | How it finds the skill | Explicit invocation |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/ds-deps-upgrade` → relative symlink to the installed skill | `/ds-deps-upgrade` |
| OpenCode | native `~/.agents/skills` (also reads `~/.claude/skills`; same target, loaded once) | ask: "use the ds-deps-upgrade skill" |

Modes: `upgrade` (default: the full pipeline, no further input), `plan` (read-only), `verify`,
`resume`, `rollback`, `status`. Add a scope, e.g. `/ds-deps-upgrade react family only`.
Scope profiles: `security-only`, `compatible`, or `all-stable` (default). Prereleases require
an explicit scope. Delivery follows the repository's delivery mode (`direct-PR`: push the owned
branch, PR, merge when green and authorized; otherwise `local-only`: a verified local branch).
The `rollback` mode cleans only empty owned state; undo committed upgrade batches with verified
compensating `git revert` commits, never by deleting or resetting their branch.

Implicit loading is off where the harness supports it (`disable-model-invocation: true` for Claude Code).
OpenCode has no per-skill flag; the skill itself runs read-only `plan` when it
was loaded without the user naming it. Claude Code pre-approves the package-manager, Git and
test commands the pipeline needs via `allowed-tools`, so `dontAsk` sessions do not deny them.

## Layout

```
SKILL.md                entry workflow (progressive disclosure)
references/             workflow, safety, javascript, ecosystems, parallelism,
                        verification, report-schema, fresh-context-tasks
scripts/depup.py        deterministic helper (stdlib, Python 3.9+), JSON output
scripts/task_protocol.py shared low-level protocol: refusals, atomic writes, redaction,
                        repository/Git state, diff bundles, provider-neutral prompts and
                        strict JSON result parsers
scripts/review_task.py  fresh-context task helper for sibling skills (ds-consolidate,
                        ds-ui-overhaul): run dirs, profiles (<skill>/task-profile.json),
                        candidate binding and review gate
tests/                  unit, integration and offline end-to-end tests
```

Run state (journals, owned worktrees, logs, reports) lives outside repositories in
`~/.local/state/ds-deps-upgrade/<repo-key>/<run-id>/` (override `DEPUP_STATE_DIR`;
`XDG_STATE_HOME` and Windows `%LOCALAPPDATA%` are honored).

## Reviews, architecture and planning

Planning and review tasks are model-agnostic and harness-agnostic: `depup.py` (and
`scripts/review_task.py` for sibling skills) prepares self-contained prompts and inputs, binds each
task to the exact candidate, validates the returned JSON result block and writes tamper-evident
receipts. The invoking session runs each prepared prompt in a fresh, read-only context using its
own harness, model and effort level — without switching models, overriding effort or invoking an
external model CLI. Only when `ds-dev-protocol` is explicitly invoked alongside the skill do
`ds-dev-protocol`'s model-routing and gate rules take precedence for the applicable tasks.
Planning returns an advisory plan; implementation stays in the main session. Details:
`references/fresh-context-tasks.md`.

## Repository workflow

Install the skill through the repository root `README.md`; that is the only supported install
path. Never edit `~/.agents/skills/ds-deps-upgrade` directly: the automatic sync pushes local
edits there straight to `main` without review.

Make every change in the repository on a branch and open a pull request:

1. Edit this directory in the repository.
2. Run the tests from the repository root and make them pass:
   `python3 -m unittest discover -s skills/ds-deps-upgrade/tests -t skills/ds-deps-upgrade`
   (also run it with `/usr/bin/python3` when the code must support the oldest interpreter).
3. Open the pull request; after the merge, update your local installed copy from `main` using
   the repository's install/sync workflow.

No shell profile, harness config, policy file or global toolchain is modified by this skill.

## Safety summary

Never edits the user's checkout; upgrades happen in an owned worktree/branch based on the
fetched upstream default branch. Push/PR/merge only for the owned branch and only per the
delivery mode; no force operations, bypass merges or branch deletion with unmerged work. High-risk migrations (data, auth,
payments, secrets, deploy config) require documented impact research, alternatives, controls,
recovery, independent review and a separate security review. The skill does not ask for approval;
it proceeds when evidence and controls support the safest option, and blocks only an unsafe or
physically human-only step. `PASS` requires recorded checks and complete high-risk evidence; the
report helper downgrades unsupported claims.
