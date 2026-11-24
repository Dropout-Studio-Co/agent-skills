# ds-dev-protocol: reference

Script internals, exit codes and accepted-risk documentation that `SKILL.md` refers to; every MUST/NEVER rule stays in `SKILL.md`.

## Gate recording: T3-verified provenance (`gate.sh --record`)

Every gate is produced by a T3 Code `delegate_task` child thread; `gate.sh <gate> <tier> --record <json-file> --child-thread <id> --parent-thread <id> [--trigger] [--diff FILE] [--base REF]` is the only writer of gate evidence. It never trusts caller-supplied model, effort or thread flags:

- **Thread read.** It queries T3 Code directly with `acp-mcp-call t3_thread_read` (`T3_ACP_MCP_NODE` / `T3_ACP_MCP_ENTRYPOINT`) and reads the child's configuration with `t3_thread_configure`. A run counts only when `childThreadId != parentThreadId`, the child's `status` is `completed`, its `providerInstanceId` (logged as `account`) is an enabled instance of the expected provider, its model is exact, and its option (`thought_level` for `plan`, `effort` for `review`, `security`, `epoch`) matches the tier and `--trigger` rule.
- **Model pinning.** `plan` needs `gemini-4-neon`; `review`, `security` and `epoch` need `claude-opus-5-5`. A silent downgrade (for example `claude-opus-4-8`) is `invalid`, never accepted.
- **Payload match.** The recorded JSON must equal the child's final `t3_submit_output` payload and validate against `plan-schema.json` or `review-schema.json`; `facts_sha256` must match `EVID/facts.md` for `plan`, and the packet must carry the exact diff, merge-base and `HEAD` for `review` and `security`.
- **Tree integrity.** Because `delegate_task` cannot strip write or shell tools, the worktree must be clean (`git status --porcelain --untracked-files=all` empty) and `HEAD` unchanged before and after the child; dirty or mutated state is `exit 2`, never a pass.
- **Accepted risks.** `T3_ACP_MCP_NODE` (and `T3_ACP_MCP_ENTRYPOINT`) is the trust root: a substituted node binary or entrypoint can forge `t3_thread_read`/`t3_thread_configure` output, and with it the thread state, provider, model, effort and account this file verifies, so it is guarded like a credential and never overridden per run. The tree check reads only this worktree's tracked and untracked status, so a child that writes outside the worktree (another checkout, `~`, a temp dir, the common git dir) or rewrites ignored files is not detected; the conductor reads the diff and checks the branch itself before merge.
- **Limit and malformed-output failover.** A `usage_limit` child logs `invalid` with `reason: "usage_limit"` and exits 2, naming the next enabled instance of the same provider, model and effort to dispatch; once every instance is tried it logs `blocked` with `reason: "<model> quota exhausted on every instance"` and exits 3. An `invalid output` run (unparsable or non-matching submission) exits 2 and is re-dispatched as a fresh child; a second invalid output for the same gate key logs `blocked` with `reason: "invalid output after retry"` and exits 3.
- **Refusal fail-closed.** A Claude run reporting a refusal (`stop_reason == "refusal"`, Anthropic `[cyber]` classifier, or `[cyber]` in the error or notice) logs `status: "blocked"`, `reason: "cyber refusal"`, `account: <providerInstanceId>` and exits 3. It is never retried as invalid JSON, never logged `pass`, never counted as model unavailability.
- **Metrics preserved.** `review` and `security` rows keep `log_metrics` writing every finding to `~/.local/state/review-metrics/findings.jsonl`, unchanged.
- **Log row.** One JSON line per run in `EVID/gates.log`: `provenance_mode: "t3-verified"`, `engine`, `provider`, `route`, `model`, `effort`, `task_id`, `gate`, `tier`, `round`, `key`, `facts_sha256`, `base_ref`, `base_sha`, `diff_sha256`, `head_sha`, `file`, `file_sha256`, `session_id`, `parent_thread_id`, `account`, `input_tokens`, `output_tokens`, `cost_usd`, `ts`, `status`, `verdict`, `reason`.
- **Exit codes.** 0 pass or a valid plan; 1 `fail`; 2 usage, precondition, or provenance and tree mismatch; 3 blocked; 4 round cap, re-plan.

## Step 6 implementer: documented mechanical runner, no OS sandbox

`scripts/implement.sh` is the sole implementation path: `opencode run --standalone`, pinned to `opencode-go/deepseek-v4.1-flash#high`, with `OPENCODE_DISABLE_CLAUDE_CODE=1`, `OPENCODE_DISABLE_FREE_MODELS=1` and `opencode/opencode.json` tool scoping (no git mutation, `gh`, web, subagents or `.env`). No other model, variant, account or conductor run substitutes for it.

- **Delimiter leak and premature stop.** A run that leaks `<|tool_calls_cbegin|>` in **that turn's own assistant text**, or stops before writing `.impl/result.json` (with `HEAD` intact), is resumed once in the same session within the remaining `IMPL_DEADLINE` and under 250K input tokens; only the current turn's `EVID/impl-<tag>-<name>.events` is scanned, never the cumulative `session export` (on a resume it still holds the earlier turn's leak) and never a tool output or a file the run read, which can quote the literal string. If it still does not complete, the round is discarded, the patch saved and the run exits 1 as one strike; a resume classified unavailable exits 3 at once with no failed or `cost_usd > 0` row, and a resume that times out keeps its timeout reason.
- **`not_checked`.** `.impl/result.json` records the verification commands the implementer ran and a `not_checked` list of what it could not run; the conductor copies it to `EVID/impl-<tag>.json`, covers the gap itself before any gate, and never reports the step complete on `not_checked` alone.
- **Accepted risks:** the implementer runs as Rahi's user with unrestricted reads (credentials included), writes and network; the permission rules match command prefixes lexically and can be bypassed (for example through `sh -c`); writes to git config or hooks in the common git dir are not detected; a process that leaves the worktree (`setsid` plus `cd` elsewhere) is not reaped; and implementer code runs in the conductor's checks after the conductor reads the diff.

## Step 8 delivery: premerge checks

`scripts/premerge_lib.py` checks the clean tree; the tier floor (final tier is the highest `Tier:` line across the re-check and `PLAN.md`; a lower one fails); and the 4-stage chronology, fail closed at exit 1:

1. **Facts binding:** `EVID/facts.md` exists and its sha256 equals `plan.facts_sha256` on every tier.
2. **Plan provenance and separation:** the `plan` row is `engine == "t3-delegate"`, `provenance_mode == "t3-verified"`, `route == "neon"`, `model == "gemini-4-neon"`, effort `medium` (Low) or `high` (Medium and High), `account` `antigravity` or `antigravity_2`, and a non-empty `session_id` distinct from `parent_thread_id`.
3. **Plan before code:** `ts(ok plan) <= ts(first non-start impl.log row)` and `<=` the first branch commit timestamp; a raised tier needs a raised-tier High-effort plan before final review, and the raised-from-Low exception survives only with a logged Low plan and review before the raise.
4. **Code before review:** `ts(last done impl.log row) <= ts(the passing review or security row on HEAD)`, or a carry from an earlier gated head with a byte-identical PR diff and no prior fail on it.
5. **Review and security provenance:** `engine == "t3-delegate"`, `provenance_mode == "t3-verified"`, `route == "opus"`, `model == "claude-opus-5-5"`, `account` a `claudeAgent*` instance, `childThreadId != parentThreadId`, effort matching the tier and `--trigger`, and exact binding via `head_sha`, `base_ref` (`origin/<pr-base>`), `base_sha` (`merge-base`) and `diff_sha256`. Any other route or provenance mode is rejected.
6. **Epoch integrity:** every `epoch-*.json` has an `ok` row with the same T3-verified provenance, effort by tier, a matching `file_sha256`, at most 2 authorized epochs per EVID, no denied epoch in the active epoch, and a fresh `plan` row before any later review or security pass counts.
7. **Stray files:** every `plan-*.json`, `review-*.json`, `security-*.json` and `epoch-*.json` in `EVID/` has a matching `ok` row and `file_sha256` in `gates.log`. A `--record` working copy goes to `EVID/raw-<gate>-<key>.json`, which is never a gate file, so a failed call cannot leave a stray `<gate>-<key>.json` behind for this check to trip on.

`implement.sh --check` accepts only pinned DeepSeek rows (`opencode-go/deepseek-v4.1-flash`, `high`, `cost == 0`) plus the empty-route `start` and `discarded` rows; the script then squash-merges with `--match-head-commit`.

## Step 6 implement.sh exit codes

- 0: done; read the full diff, rerun bootstrap and repo checks, and commit the accepted round.
- 1: one failed round; the patch is saved, the tree reset, the reason logged in `EVID/impl.log`, and the next round uses `--notes` (at most 3 per step and plan).
- 2: usage or precondition.
- 3: no implementer available; record the blocked external status with `Routes tried:`; never call another model.
- 4: round cap; re-plan.
- 5: escalate through `EVID/escalation-<tag>.md` and `--notes`, or re-plan.
- 6: worktree processes survived; read, run, bootstrap or commit nothing from that worktree, remove it from the main checkout with `git worktree remove --force <wt>`, never reuse the path, continue from the last accepted commit in a fresh worktree, and record the PIDs in `PROGRESS.md` and the report.

Run nothing else in the worktree during a run: the runner stops every process whose working directory is inside it (exit 6 if one survives). After a killed run, `implement.sh --discard --bootstrap <cmd|none>` resets the worktree; resets wipe ignored files, so the bootstrap (from AGENTS.md/CLAUDE.md/README, recorded in `PROGRESS.md`) must recreate them.

## Conductor parent-thread recovery

A limited Antigravity main thread cannot switch itself: recover by a manual picker switch plus `continue` (delegated children do not migrate, so check or `task_cancel` orphaned ones), or wait for reset (optional same-account `autoResumeLimitedThreads`).

## Step 7 delta and epoch mechanics

- **Delta commands.** The diff since the last reviewed head is `git diff --no-color <last reviewed head> H` in a repository, or `diff -u` of the old and new diff files saved as `EVID/diff-<key>.diff` outside one.
- **Refusal and invalid rows.** A refusal is a `blocked` row with `reason: "cyber refusal"` and exit 3. A run refused after the key logs `invalid`; one invalid run is re-dispatched as a fresh child, then logged `blocked`.
- **Epoch packet.** `EVID/epoch.md` is facts only: the request verbatim, the blocked gate and key, its `gates.log` rows, every round's gate file and `PLAN.md`; no proposed approach. `EVID/packet-epoch.md` carries `Gate: epoch`, the tier, the sha256 of `epoch.md` and its text, and is recorded with `gate.sh epoch <medium|high> --record` at a tier no lower than the blocked gate's.

## Shortcuts in plans and PRs

A deliberate shortcut with a known limit is recorded in the plan's `risks` as `shortcut: <limit>, <when to upgrade>`; the code never carries a shortcut comment. The PR body lists each open shortcut under a `Shortcuts` heading, or `none`. The step 10 report repeats every still-open shortcut and every `Not checked` item carried from the implementer.

## Workflow skills (extended notes)

Each skill is read from `~/.agents/skills/<name>/SKILL.md`; `retro` has model invocation off. `diagnosing-bugs` phases 1-4 run in a scratch detached worktree (removed after) and produce the red repro command and confirmed cause for `facts.md` or `--notes`; phases 5-6 are the plan and step 6, and a round 2 implementer failure also runs it. `tdd` is appended by `implement.sh` to every brief, with the plan's Tests as the agreed seams. `pr` supplies the repo PR template; the protocol adds tier, triggers, gate links and `Shortcuts`. `retro` runs at step 9 after any `fail` verdict or failed or escalated round, writing candidates to `PROGRESS.md`, never to the user. `setup-pre-commit` is cited in `facts.md` when a JS/TS task adds commit-time hooks or checks, with the repo's hook manager, formatter and package manager winning. `codebase-design` is cited for module interfaces, seams and deep-module refactors. `writing-for-agents` is read before editing a skill, protocol, `AGENTS.md` or `CLAUDE.md`. `domain-modeling` is cited for domain terms, `GLOSSARY.md` or ADRs. `research` is primary-source investigation for recent docs, APIs or versions, captured in `EVID`. `prototype` is an uncommitted throwaway before planning when state-model or UI needs validation. `wizard` is an interactive bash script for human-only setup or migration, never for agent-executable steps. `grilling` is a method only: order `facts.md` open decisions as a frontier tree for the Neon plan gate, never for Rahi.

## Gate eval set

The review and plan gate eval set lives in `skills/ds-dev-protocol/evals/` (`README.md` there: fixtures, staging, recording, scoring). It stays off the gate path: `scripts/`, the briefs and the schemas never read it. `evals/fixture-check.sh` proves all eight fixtures and runs their suites; `evals/build_fixtures.py --check` with `evals/inputs.sha256` binds the fixture bytes; `evals/run.sh` stages a fixture outside the repository, records through `gate.sh --record` and scores through `evals/score.py` against `evals/rubric.json`. Rescore after any change to `opus-gate-brief.md`, `plan-gate-brief.md`, `plan-schema.json` or `review-schema.json`, and record one row per run in `~/.local/state/review-metrics/evals.jsonl`.
