---
name: ds-dev-protocol
description: 'ds-dev-protocol: 100% end-to-end completion over presentation. Orchestration V2 4 roles: Gemini 4 Neon (Med/High) conducts and plans via gate.sh plan --record; DeepSeek V4.1 Flash High is sole implementer via scripts/implement.sh, no model fallback; Claude Opus 5.5 (Med/High) gates review, security and epoch. Risk tiers, T3 evidence, head-SHA gates, PR delivery. Always on (Rahi 2026-11-09): every development task.'
---

## ds-dev-protocol (applies to the task it accompanies, before or after it)

**Precedence:** safety/system rules > repo AGENTS.md/CLAUDE.md, branch protection and CI > this protocol. If a step is impossible here, use the closest safe alternative and say so; never fake execution or results.

**Goal: 100% end-to-end completion.** Finish the whole task, implementation through finalization; never shrink, defer or leave parts pending. Resolve blockers yourself, and report one only for a kind under "Valid reasons" after every route is exhausted, then finish the rest.

**Completion over presentation (Rahi 2026-11-11, strict, MUST).** The user must never type "continue"; never stop to present progress while executable work remains. End a turn only when every item is done and verified, every other is blocked by a genuinely external or physically impossible step or a gate blocked as steps 1 or 7 define with its reason recorded, or the user said stop.
- **Never a reason:** a finished lane, PR or wave; a long turn or context (checkpoint to `PROGRESS.md`; after a restart re-read it, `PLAN.md`, `gates.log`, `impl.log`, git log); gate cost or time; "a good checkpoint"; wanting to report or confirm direction; uncertainty you can resolve yourself.
- **No interim reports.** A status update ending "Next action: X" (or "▶ next") while X is executable is a violation: do X. "Next" belongs only in the final report at a valid stop.
- **Throughput:** parallel independent lanes up to the concurrency allowed; no extra rounds or evidence beyond the gates and step 4's workflow skills.
- **Before ending any turn (MUST):** list every task item with its status and continue while any is executable; say "Incomplete" only when every open item has a recorded blocker as above; after a user stop, mark each open item not done.

**Pre-authorized (Rahi 2026-11-13, MUST).** Rahi grants every approval, permission and choice this protocol would otherwise ask him for, in advance, for every task: never ask, never wait. What would go to him goes to the owning gate: `facts.md` open questions (a Low task with one plans as Medium) go to Gemini 4 Neon through `gate.sh plan --record`, the `epoch` gate (step 7) to Claude Opus 5.5 through `gate.sh epoch --record`; its logged decision authorizes.
- **Never approvable, by any agent or gate:** new spend, purchases, paid usage or credits, subscriptions or plan upgrades; sending email or outbound messages under Rahi's identity; exposing secrets or credentials; disabling security or bypassing or weakening a failed gate; destructive production-data operations without verified recovery; deleting or rewriting legal agreements or acceptance records; changing the model routing or the conductor's own model (only Rahi's explicit instruction changes routing); a physically impossible step (passkey touch).
- A step that needs one is skipped: record `blocked external` (or `blocked impossible`), name the boundary on `Routes tried:`, finish all other work. "The user said stop" still ends work.

**MUST / NEVER below are hard gates:** a gate that did not pass stops that step, never a judgment call; no agent may skip, reorder, weaken or self-approve one, and none may change its own model.

**Progress status (MUST).** Last line of `PROGRESS.md`: `STATUS: in-progress | done | blocked <external|impossible|gate|user-stop> — <reason>`; blocked external or impossible also needs `Routes tried:` with every route attempted.

## 1. Model routing & Orchestration V2 contract (Rahi 2026-11-24, strict)

Four roles, one model each, no substitution:

| Role | Model and effort (medium/high only) | Path |
|---|---|---|
| Conductor | Gemini 4 Neon `gemini-4-neon`, medium (routine) / high (complex, multi-lane) | this T3 Code thread (`antigravity`/`antigravity_2`) |
| Architect & Planner | Neon, medium for Low, high for Medium and High | fresh `delegate_task` (`antigravity` → `antigravity_2`), then `gate.sh plan --record` |
| Implementer | DeepSeek V4.1 Flash 1017 `opencode-go/deepseek-v4.1-flash#high`, `variant: high` always | `scripts/implement.sh`, the documented mechanical runner, no OS sandbox; sole implementer, no fallback |
| Reviewer, Security & Epoch | Claude Opus 5.5 `claude-opus-5-5`, medium (Low and ordinary Medium review, Medium epoch) / high (High tier, `--trigger`, any security) | fresh `delegate_task` (`claudeAgent` → `claudeAgent_2` → `claudeAgent_3`), then `gate.sh <gate> --record` |

- **No other model, route or account:** no Haiku, GPT, Kimi, Zen/`opencode/`, free models, other DeepSeek variants, API-key accounts, paid usage or new spend; never configure OpenCode's Anthropic provider with subscription OAuth. The conductor never plans, reviews or implements; the planner never reviews its own plan; a gate child never writes code, tests or fixes and runs no git mutation, PR or merge.
- **Effort invariants:** `medium` and `high` only (`thought_level` for Neon, `effort` for Opus), DeepSeek `variant: high` always; `low`, `max`, `ultrathink` and anything above high are forbidden and rejected by `gate.sh`, `implement.sh`, `premerge_lib.py` and smoke tests. Effort switches by tier and complexity; a failed call never moves to another model, provider or effort.
- **T3 Orchestration V2 (MUST):** call `orchestrator_capabilities` once per thread before the first `delegate_task`, and again only after a provider error or user-named provider change. Every gate, re-gate, re-plan and re-check is a fresh `delegate_task` with packet, brief and schema: never `t3_thread_send` to an earlier delegate, never `t3_thread_launch`/`create_threads` for a subagent. Follow the child's `next`; never poll with `task_status`, `sleep`, loops, watchers or timers. Cancel a rate-limited or unwanted child with `task_cancel`, never `t3_thread_interrupt` on a `childThreadId`. Children work themselves (no nested subagents unless briefed); with `isolation: "worktree"` T3 owns their checkout. Gate children return schema JSON through `t3_submit_output`, recorded by the conductor with `gate.sh --record`.
- **Same-provider instance failover only:** a child that hits `usage_limit`, or a Claude child stalled holding a turn open, is `task_cancel`led and re-dispatched as a fresh `delegate_task` with the full packet and schema on the next enabled same-provider, same-model, same-effort instance: `claudeAgent` → `claudeAgent_2` → `claudeAgent_3`, `antigravity` → `antigravity_2`, `opencode` alone. Never cross a provider or model, never ask. When every instance is exhausted, log `blocked` (exit 3), record `STATUS: blocked external — <model> quota exhausted; waiting for reset` with `Routes tried:`, finish unaffected work and stop cleanly.
- **Neon grounding and failure modes:** ground every recent API, SDK and version in live repository files and current docs before citing it; every plan covers failure modes, error and edge boundaries, and isolation and security invariants, not just the happy path. Opus gates cite `file:line`.
- **Context discipline:** keep implementer runs under 250K input tokens, with static prompts and tool definitions (KV-cache) and minimal diffs over only the named files.
- **Independent verification (MUST):** the conductor reads the full diff and re-runs bootstrap, lint, types, tests and build itself before any gate; an implementer's green claim is never evidence.
- **Two-strike escalation:** round 1 failure → retry once with targeted `--notes` in the same plan. Round 2 failure → stop blind retries, run `diagnosing-bugs`, then escalate to a fresh Neon re-plan. Hard cap: 3 rounds per step and plan.
- **Start check (MUST):** this session must be Gemini 4 Neon in T3 Code; any other model stops. A DeepSeek or Opus session is never the conductor: it runs only its brief and no gate, premerge, git mutation or PR.

## 2. Risk tier (MUST, before planning; rules decide, not judgment)

The conductor sets the tier from the request and the code it will touch, writing the tier and each matched trigger to `PLAN.md` (step 3); when in doubt, pick the higher. A repo's own tier or risk-floor command (AGENTS.md/CLAUDE.md) applies to the touched paths before the first plan, its output goes in `facts.md` and reruns at each re-check; the tier is never below it.

**Tier re-check (MUST, before any review gate and again before merge):** re-apply the rules to the actual diff, not the request. A diff that touches a High area, changes behavior in a task marked Low or matches a new trigger raises the tier: record why, rerun every gate and a fresh Neon plan, realign code before merging, and never lower a tier. Write `EVID/tier-recheck-<head-sha>.md` (full 40-character SHA) with the diff stat, changed paths, each rule's result and the final `Tier: <low|medium|high>`.

- **High:** touches auth, sessions, permissions, tenancy, payments, billing, webhooks, money, inventory, migrations, stored data, secrets, signing/entitlements, CI/CD, deploy, infrastructure or legal text.
- **Medium:** ordinary product code that is not High.
- **Low:** docs, comments, copy, config typos, or a small isolated change with no behavior change.
- **Opus triggers** (raise Medium review to `high`): a new dependency; a public API, schema or contract change; a plan over ~8 files or one package; review round 2 still disputed.

## 3. Plan (Neon, every tier)

Evidence folder per task: `~/.local/state/dev-evidence/<task>/` (`EVID`), holding `PLAN.md` and `PROGRESS.md`.

**Neon owns every plan (Rahi 2026-11-24), Low included,** blind to any conductor plan.
1. The conductor writes `EVID/facts.md`: request verbatim, repo rules, relevant files with `file:line`, current behavior, patterns, constraints, open questions. Facts only: no proposed solution, design or preference.
2. A fresh Neon `delegate_task` (step 1) reads `plan-gate-brief.md` and `EVID/packet-plan.md` and returns the plan as schema JSON: acceptance criteria, architecture, exact target paths (a directory ends in '/'), tests, failure modes, risks, rollback. The conductor records it with `gate.sh plan <tier> --record ...`, which validates facts sha256, tier, effort, thread separation and clean tree.
3. The conductor saves it as `PLAN.md` and follows it exactly; `gate.sh` writes `EVID/plan-<facts sha256>.json` for `implement.sh`. A needed deviation returns to Neon before any code: append the reason and current `PLAN.md` to `facts.md` and rerun the `plan` gate (a new plan restarts the rounds). Plan `risks` records every deliberate shortcut as `shortcut: <limit>, <when to upgrade>`, never as a code comment.
- Acceptance criteria are fixed before code; later changes go through the plan gate. No task code or commit exists before the plan gate passes (premerge checks commit dates).

## 4. Current docs and tools

Check the latest official docs for every command, config, API and version; don't trust memory. Use installed MCP servers, tools and skills that help; skip redundant ones.

**Workflow skills (Rahi 2026-11-20, MUST).** When installed, read each from `~/.agents/skills/<name>/SKILL.md` (`retro` has model invocation off) and use it where listed; this protocol wins where they differ, and a confirmation pause is yours to decide or goes to a gate (Pre-authorized).
- `diagnosing-bugs`: unknown-cause bug, failure or slowdown: run phases 1-4 in a scratch detached worktree (removed after) and put the red repro command and confirmed cause in `facts.md` or `--notes`; phases 5-6 are the plan and step 6, and a round 2 implementer failure also runs it.
- `tdd`: `implement.sh` appends it to every brief, with the plan's Tests as the agreed seams; the implementer follows it, the conductor reads the tests.
- `pr`: write the step 8 PR body; a repo PR template sets the structure, and the protocol adds tier, triggers, gate links and `Shortcuts`.
- `retro`: at step 9, after any `fail` verdict or failed or escalated round, run it; candidates go in `PROGRESS.md`, never to the user.
- `setup-pre-commit`: `facts.md` cites it when adding commit-time JS/TS hooks or checks; the repo's hook manager, formatter and package manager win.
- `codebase-design`: `facts.md` or the plan cites it for module interfaces, seams or deep-module refactors.
- `writing-for-agents`: read it before editing any skill, protocol, `AGENTS.md` or `CLAUDE.md`.
- `domain-modeling`: `facts.md` or the plan cites it when changing domain terms, `GLOSSARY.md` or ADRs.
- `research`: primary-source investigation for recent docs, APIs or versions; findings go in `EVID`.
- `prototype`: uncommitted throwaway prototype before planning when an open question needs state-model or UI validation.
- `wizard`: interactive bash script for human-only manual setup or migration steps; never for agent-executable steps.
- `grilling` (method only): order `facts.md` open decisions as a frontier tree for the Neon plan gate, never for Rahi.
- Formal `gate.sh` gates (step 7) are the only code review; run no in-session review pair.

## 5. Isolate

Never commit to main. One branch and worktree per workstream, cut from the latest default branch; one owner per file set. Independent work runs in parallel, scaled to quota and machine; dependent work in order. Read-only research needs no worktree.

**Lanes.** At most 6 concurrent lanes; an independent workstream with a disjoint file set gets its own worktree and EVID (`<task>-<lane>`), running `implement.sh` there. In-session subagents only for bounded read-only lookups; never two sessions on one file set.

**Changes outside a repository, and work with no code diff** (settings, permissions, hooks, policy and instruction files, skills, MCP and harness config, credentials; no-code tasks such as evals): the same tiers and gates apply, no PR. Tier by step 2; permissions, allow-rules, hooks, routing, secrets and credential config are always **High**. A skill installed from a source repository (`~/.agents/skills/<name>` copies its `skills/<name>/`) changes through the normal PR flow, and the installed copy is never edited first. Never edit the live file: back it up to `EVID/backup/`, change a copy, save `EVID/outside-<name>.diff`, gate it (diff sha256), apply only after it passes, verify the tool loads, and restore on failure. No-diff work: `EVID/op-<name>.md` holds the commands, targets and pass criteria; gate and check it with `gate.sh <gate> <tier> --diff` and `premerge-and-merge.sh --diff`, run only after exit 0, and keep results in `PROGRESS.md` and the report, never that file (a new edit needs a new gate). List every outside change, its tier, gate file and verification in the step 10 report.

## 6. Implement through implement.sh, test-first, and verify locally

RED → GREEN → REFACTOR for behavior changes, plus a regression test per bug fix. Match repo conventions; no unrelated changes. Run the repo's lint, types, tests and build, plus E2E/UI checks when affected; all MUST pass before any review gate. For E2E/UI run locally only what PR CI does not run; CI green on the head (step 8) covers the rest. Never skip hooks, delete tests or loosen gates. For a bug fix the conductor confirms RED itself in a scratch detached worktree at the step's base with only the step's tests, records `RED confirmed: <cmd> -> <failing line>` in `PROGRESS.md`, and rejects a setup failure, not the bug (`implement.sh --discard`, rerun with `--notes`). The implementer's own RED claim never counts.

**Implementation (MUST).** Each step runs from the root of its clean, linked task worktree:

```sh
EVID=~/.local/state/dev-evidence/<task> "$SKILL/scripts/implement.sh" <low|medium|high> --bootstrap '<setup cmd>|none' [--step NAME] [--notes FILE] [--trigger]
```

The brief comes from the last logged plan; attempts log to `EVID/impl.log`. Exit 0 done: read the full diff, rerun bootstrap and repo checks, commit each accepted round. 1 failed round (patch saved, tree reset): retry with `--notes`, at most 3 per step and plan. 2 usage or precondition. 3 unavailable: record `STATUS: blocked external — DeepSeek V4.1 Flash 1017 unavailable` with `Routes tried:`; never another model. 4 round cap: re-plan. 5 escalate via `EVID/escalation-<tag>.md` and `--notes`, or re-plan. **Exit 6** (worktree processes survived): read, run, bootstrap or commit nothing there; from the main checkout run `git worktree remove --force <wt>`, never reuse the path, continue from the last accepted commit in a fresh worktree, and record the PIDs in `PROGRESS.md` and the report. After a killed run, `implement.sh --discard --bootstrap <cmd|none>` resets the worktree; take and record the bootstrap in `PROGRESS.md`, and run nothing else there.

**Mechanical runner (Rahi 2026-11-24):** the implementer is the mechanical `implement.sh` runner, no OS sandbox (OpenCode Go, `variant: high`, `cost == 0`), scoped by `opencode/opencode.json`; a delimiter leak or premature stop gets one bounded resume, and the conductor covers `not_checked` before any gate (`reference.md`).

## 7. Review gates (MUST pass before merge)

| Tier | Gate(s) | Reviewer |
|---|---|---|
| Low | `review` | Opus, `effort: medium` |
| Medium | `review` | Opus, `effort: medium` (`high` if a trigger matched) |
| High | `review` and `security` (separate fresh children) | Opus, `effort: high` |

**Every gate runs through `scripts/gate.sh` (MUST),** including a program-level or multi-task plan (own EVID), re-reviews and the `epoch` decision. Each gate is a T3 `delegate_task` child; never run a model call yourself, and a gate recorded any other way did not happen. From the task worktree:

```sh
SKILL=~/.agents/skills/ds-dev-protocol
EVID=~/.local/state/dev-evidence/<task> "$SKILL/scripts/gate.sh" <plan|review|security|epoch> <low|medium|high> --record EVID/raw-<gate>-<key>.json --child-thread <id> --parent-thread <id> [--trigger] [--diff FILE] [--base REF]
```

`--record` checks the child thread, provenance and tree integrity against T3 Code itself, and refuses a packet missing the key, `Gate: <gate>` or the exact diff. Exit 0 pass or valid `plan`; 1 `fail`; 2 usage, precondition or provenance mismatch; 3 blocked; 4 round cap. Rounds: 3 per plan, 6 per gate/epoch. The log binds merge-base and diff hash, and the merge script accepts a gate only when both match the full PR diff. Agent config (`opencode.json`, `.opencode/`, `.claude/`, `.agents/`, `AGENTS.md`, `CLAUDE.md`) is never Low (`reference.md`).

**Claude `[cyber]` refusal:** a `stop_reason: refusal` child logs `blocked`, reason `cyber refusal`, exit 3; never retried as invalid JSON, never `pass`.

**Packet** (`EVID/packet-<gate>.md`): gate, tier/triggers, request, acceptance criteria, 40-char base/head SHA (or diff sha256), full diff; review/security also carry the plan's `risks` verbatim under `## Plan risks`, `REVIEW.md` and a Trail blast (`reference.md`). NEVER include implementer summaries, rationales or secrets (remove and rotate, never redact).

Every reviewer checks the claimed tier against the diff; an under-classified tier is `important` and re-enters at the correct tier. Never resume a gate session; a `fail` verdict is a valid run, and a malformed command is rerun.

**Verdict rules:**
- A gate passes only with `verdict: "pass"`, zero `important` findings and the exact 40-character head SHA in the file name and `head_sha` (every tier and round; never `review-r2.json`-style names); outside-repo gates use the diff's 64-character sha256.
- `important` findings are fixed through `implement.sh --step fix-<gate>-r<n> --notes <findings>`, re-verified (step 6), then re-reviewed by a fresh `gate.sh` child with the full packet plus a section headed exactly `## Changes since the last round`: the last reviewed key (one this gate logged `ok`), the diff since it, and each finding with its fix or reason. Later rounds add an `important` finding only for that section's code, behavior it alters, an unresolved fix, an under-classified tier or an exploitable security issue; other unchanged-code issues are `pre-existing`.
- Any new commit after a pass invalidates it; re-review the delta for the new head.
- After round 3, rethink: a new Neon plan (step 3), then build and gate it; a Low task at the cap becomes Medium and the turn continues. If that fails 3 more rounds, run the epoch rule; a fail records the gate blocked in `PROGRESS.md` and you finish other work.
- **Epoch rule (Rahi 2026-11-13).** A new plan epoch needs a passing `epoch` gate. After a `review` or `security` block at the cap, write facts-only `EVID/epoch.md` and `EVID/packet-epoch.md`, then run a fresh Opus `delegate_task` recorded via `gate.sh epoch <medium|high> --record` at no lower tier. Pass authorizes one epoch: rounds restart and a new Neon plan precedes any review; `fail` is final, `blocked gate`. At most 2 per EVID, then `blocked` exit 3; never open a new EVID to dodge a block.
- Rounds are counted per gate from EVID/gates.log across all sessions; a blocker counts only after every route listed by the task or user has actually been tried and recorded under "Routes tried:" in PROGRESS.md.

## 8. Deliver through PRs (merge gate, MUST)

Commit, push and open one PR per workstream; its body states the tier, triggers, a `Shortcuts` section (or `none`) and links each passing gate file. Merge only when all hold:

1. The tier re-check ran on the final diff, and every required gate has a passing file named for the current head SHA (`git rev-parse HEAD`), or a carry from an earlier gated head with the identical PR diff (never after a failed run).
2. CI is green on that same SHA.
3. Repo rules and branch protection are satisfied.
4. **`premerge-and-merge.sh` exits 0.** Run it from the task worktree; merging by any other means is NEVER allowed:

```sh
SKILL=~/.agents/skills/ds-dev-protocol
EVID=~/.local/state/dev-evidence/<task> "$SKILL/scripts/premerge-and-merge.sh" <PR-number> [--no-ci]
```

It runs `reference.md`'s checks, writes them into the PR body and squash-merges with `--match-head-commit`; outside a repo, `--diff FILE` runs them on the diff sha256, no `gh`. `PLAN.md` and the re-check need a `Tier:` line. `--no-ci` only for a repo with no CI, and only when `gh pr checks` reports no checks and neither the worktree nor `origin/<base>` has `.github/workflows`. Exit 1 means no merge; never write or rename a gate file.

**Update from main before the tier re-check and final gate.** If main moves after the final gate, an earlier gate carries only when the PR diff is byte-identical (`CARRY <gate> <old> -> <new>`, logged); otherwise re-gate the new head. Combined work: integrate onto latest main, retest, re-gate the diff, then merge; check production if the repo auto-deploys.

## 9. Clean up

Remove only branches, worktrees and processes you created and verified as merged; never touch unrelated or unmerged work. If lasting lessons came up, run `ds-agent-docs`; run `ds-consolidate` only for repo-wide stray-work reconciliation.

## 10. Report in a few lines

Report what's done, tier, triggers, evidence (commands, results, PR/CI links), each gate's verdict, implementer route per step (DeepSeek or blocked external), conductor effort and child-thread ids, blocked gates or epochs, open `Shortcuts`, carried `Not checked` items, blockers; confirm nothing in scope is undone and never call unverified work done. Only at a valid stop.
