---
name: ds-dev-protocol
description: 'ds-dev-protocol: Always on by default for all work across every harness, model, AI agent & T3 Code; off only on explicit request, session-only (never globally). Gemini 4 Neon conducts (Medium always), plans (Med+High); DeepSeek V4.1 Flash 1017 high implementer (implement.sh, no model fallback); Gemini 4 Neon review/security/epoch (Med+High, Med+High, High); UI opus>neon (plan Med+High, review Med+High).'
---

## ds-dev-protocol (always on by default for all work across every harness, model, AI agent & T3 Code; opt-out: explicit, session-only, never global)

**Precedence:** safety/system rules > repo AGENTS.md/CLAUDE.md, branch protection and CI > this protocol. If a step is impossible here, use the closest safe alternative and say so; never fake execution or results.

**Goal: 100% end-to-end completion.** Finish the whole task, implementation through finalization; never shrink, defer or leave parts pending. Resolve blockers yourself, and report one only for a kind under "Valid reasons" after every route is exhausted, then finish the rest.

**Completion over presentation (strict, MUST).** The user must never type "continue"; never stop to present progress while executable work remains. End a turn only when every item is done and verified, every other is blocked by a genuinely external or physically impossible step or a gate blocked as steps 1 or 7 define with its reason recorded, or the user said stop.
- **Never a reason:** a finished lane, PR or wave; a long turn or context (checkpoint to `PROGRESS.md`; after a restart re-read it, `PLAN.md`, `gates.log`, `impl.log`, git log); gate cost or time; "a good checkpoint"; wanting to report or confirm direction; uncertainty you can resolve yourself.
- **No interim reports.** A status update ending "Next action: X" (or "▶ next") while X is executable is a violation: do X. "Next" belongs only in the final report at a valid stop.
- **Throughput:** parallel independent lanes up to the concurrency allowed; no extra rounds or evidence beyond the gates and step 4's workflow skills.
- **Before ending any turn (MUST):** list every task item with its status and continue while any is executable; say "Incomplete" only when every open item has a recorded blocker as above; after a user stop, mark each open item not done.

**Pre-authorized (MUST).** Rahi grants every approval, permission and choice this protocol would otherwise ask him for, in advance, for every task: never ask, never wait. What would go to him goes to the owning gate: `facts.md` open questions (a Low task with one plans as Medium) go to the Planner through `gate.sh plan --record`, the `epoch` gate (step 7) to the Reviewer through `gate.sh epoch --record`; its logged decision authorizes.
- **Never approvable, by any agent or gate:** new spend, purchases, paid usage or credits, subscriptions or plan upgrades; sending email or outbound messages under Rahi's identity; exposing secrets or credentials; disabling security or bypassing or weakening a failed gate; destructive production-data operations without verified recovery; deleting or rewriting legal agreements or acceptance records; changing the model routing or the conductor's own model (only Rahi's explicit instruction changes routing); a physically impossible step (passkey touch).
- A step that needs one is skipped: record `blocked external` (or `blocked impossible`), name the boundary on `Routes tried:`, finish all other work. "The user said stop" still ends work.

**MUST / NEVER below are hard gates:** a gate that did not pass stops that step, never a judgment call; no agent may skip, reorder, weaken or self-approve one, and none may change its own model.

**Progress status (MUST).** Last line of `PROGRESS.md`: `STATUS: in-progress | done | blocked <external|impossible|gate|user-stop> — <reason>`; blocked external or impossible also needs `Routes tried:` with every route attempted.

## 1. Model routing & Orchestration V2 contract (strict)

<!-- routing:start -->
Four roles, one model each, no substitution:

| Role | Model and effort (medium/high only) | Path |
|---|---|---|
| Conductor | Gemini 4 Neon `gemini-4-neon`, `medium` always (never `high` or other) | this T3 Code thread (`antigravity`) |
| Architect & Planner | Gemini 4 Neon `gemini-4-neon`, `medium` (`high` on `--high-effort`) | fresh `delegate_task` on a live `antigravity` instance, then `gate.sh plan --record` |
| Implementer | DeepSeek V4.1 Flash 1017 `opencode-go/deepseek-v4.1-flash#high`, `variant: high` always | `scripts/implement.sh`, the documented mechanical runner, no OS sandbox; sole implementer, no fallback |
| Reviewer, Security & Epoch | Gemini 4 Neon `gemini-4-neon`, review `medium` (`high` on `--high-effort`); security `medium` (`high` on `--high-effort`); epoch `high` | fresh `delegate_task` on a live `antigravity` instance, then `gate.sh <gate> --record` |

- **Dynamic `driver_kind` failover:** call `orchestrator_capabilities`; use only live `providerInstanceId` serial IDs (never display names or emails). A child hitting `usage_limit` is `task_cancel`led and re-dispatched as a fresh `delegate_task` on the next live instance of the same `driver_kind`, model and effort: never cross a `driver_kind` or model, never ask. When every live pair is tried, log `blocked` (exit 3), record `STATUS: blocked external — <model> quota exhausted; waiting for reset` with `Routes tried:`, stop cleanly.
- **Start check (MUST):** session must be Gemini 4 Neon at `medium` in T3 Code; any other model or effort stops. DeepSeek V4.1 Flash 1017 never conducts: runs only its brief, no gate, premerge, git mutation or PR.
- **Frontend & UI routing (`--ui`, plan and review only):** with `--ui` and `Scope: ui` in the packet the gate uses this 2-tier chain in priority order: Claude Opus 5.5 `claude-opus-5-5` → Gemini 4 Neon `gemini-4-neon`. A tier applies when a live `orchestrator_capabilities` instance of its `driver_kind` runs its model; a `ui_gates` route with zero live instances is skipped automatically. UI plan: `medium` (`high` on `--high-effort`); UI review `medium` (`high` on `--high-effort`). Non-UI gates keep the single route above. If every UI tier is exhausted, log `blocked` (exit 3) and never use another model.
<!-- routing:end -->

- **No other model, route or account:** no Haiku, GPT, Kimi, Zen/`opencode/`, free models, other DeepSeek variants, API-key accounts, paid usage or new spend; never configure OpenCode's Anthropic provider with subscription OAuth. The conductor never plans, reviews or implements; the planner never reviews its own plan; a gate child never writes code, tests or fixes and runs no git mutation, PR or merge.
- **Effort invariants:** `medium`/`high` only; each route's option key and allowed values come from `routing.json`, and every `delegate_task` passes `target.options.<option_key>` (the route's key, such as `thought_level` for Neon or `effort` for Opus) with the exact effort; a missing or different option fails closed. Conductor `medium` always, Implementer `variant: high` always; `low`, `max`, `ultrathink` are forbidden and rejected by every runner and smoke test. Plan, review and security base is `medium` on every valid tier; a matched trigger or `--high-effort` raises the gate to `high`; epoch is `high` always; failed calls never change model, provider or effort.
- **T3 Orchestration V2 (MUST):** call `orchestrator_capabilities` once per thread before the first `delegate_task`, and again only after a provider error or user-named provider change. Every gate, re-gate, re-plan and re-check is a fresh `delegate_task` with packet, brief and schema: never `t3_thread_send` to an earlier delegate, never `t3_thread_launch`/`create_threads`. Follow the child's `next`; never poll with `task_status`, `sleep`, loops, watchers or timers. Cancel with `task_cancel`, never `t3_thread_interrupt`. Children work themselves; with `isolation: "worktree"` T3 owns their checkout. Gate children return schema JSON through `t3_submit_output`, recorded with `gate.sh --record`.
- **Planner grounding and failure modes:** ground every recent API, SDK and version in live repository files and current docs before citing it; every plan covers failure modes, error and edge boundaries, and isolation and security invariants, not just the happy path. Reviewer gates cite `file:line`.
- **Context discipline:** keep implementer runs under 250K input tokens, with static prompts and tool definitions (KV-cache) and minimal diffs over only the named files.
- **Independent verification (MUST):** the conductor reads the full diff and re-runs bootstrap, lint, types, tests and build itself before any gate; an implementer's green claim is never evidence.
- **Two-strike escalation:** round 1 failure → retry once with targeted `--notes` in the same plan. Round 2 failure → stop blind retries, run `diagnosing-bugs`, then escalate to a fresh Planner re-plan. Hard cap: 3 rounds per step and plan.

## 2. Risk tier and effort triggers (MUST, before planning; rules decide, not judgment)

**Risk tier.** Set the tier from the request and the code it will touch, writing it to `PLAN.md` (step 3); when in doubt, pick the higher. A repo tier or risk-floor command applies to the touched paths before the first plan, goes in `facts.md`, reruns at each re-check, and the tier is never below it.

**Tier re-check (MUST, before any review gate and again before merge):** re-apply the rules to the actual diff. A High area or a behavior change in a task marked Low raises the tier: record why, rerun every gate and a fresh Planner plan, and never lower a tier. A new effort trigger raises only that gate's effort through `--high-effort`: it never changes the risk tier and needs no fresh Planner plan. `EVID/tier-recheck-<head-sha>.md` (full 40-char SHA) holds the diff stat, changed paths, each rule's result, `Tier: <low|medium|high>` and `Effort-Triggers: none | <tags>`.

- **High:** auth, sessions, permissions, tenancy, payments, billing, webhooks, money, inventory, migrations, stored data, secrets, signing/entitlements, CI/CD, deploy, infrastructure or legal text.
- **Medium:** ordinary product code that is not High.
- **Low:** docs, comments, copy, config typos, or a small isolated change with no behavior change.

**Effort triggers (MUST, decoupled from tier).** Plan, review and security run at base `medium` on every valid tier; `epoch` is `high` always. A matching trigger raises that gate to `high` and `gate.sh` records `effort_triggers`. Plan: `arch-trust-state`, `scope-multi`, `arch-ambiguous`, `reactive-replan`; review: `diff-large`, `contract-or-guard`, `ui-overhaul`, `reactive-round`; security: `attack-surface`, `reactive-round`. Use `--high-effort <tags>`; `--trigger` is the legacy alias (`legacy-trigger`, never on epoch). `gate.sh` auto-adds `high` and `reactive-round` on review/security from round 2 after a fail in the active plan or after an authorized epoch. Full table: `reference.md`.

## 3. Plan (Planner, every tier)

Evidence folder per task: `~/.local/state/dev-evidence/<task>/` (`EVID`), holding `PLAN.md` and `PROGRESS.md`.

**The Planner owns every plan, Low included,** blind to any conductor plan.
1. The conductor writes `EVID/facts.md`: request, repo rules, relevant files with `file:line`, behavior, patterns, constraints, open questions; facts only, no proposed solution.
2. A fresh Planner `delegate_task` (step 1) reads `plan-gate-brief.md` and `EVID/packet-plan.md` and returns the plan as schema JSON: acceptance criteria, architecture, exact target paths (a directory ends in '/'), tests, failure modes, risks, rollback. The conductor records it with `gate.sh plan <tier> --record ...`, which validates facts sha256, tier, effort, thread separation and clean tree.
3. The conductor saves it as `PLAN.md` and follows it exactly; `gate.sh` writes `EVID/plan-<facts sha256>.json` for `implement.sh`. A needed deviation returns to the Planner before any code: append the reason and current `PLAN.md` to `facts.md` and rerun the `plan` gate (a new plan restarts the rounds). Plan `risks` records every deliberate shortcut as `shortcut: <limit>, <when to upgrade>`, never as a code comment.
- Acceptance criteria are fixed before code; later changes go through the plan gate. No task code or commit exists before the plan gate passes (premerge checks commit dates).

## 4. Current docs and tools

Check the latest official docs for every command, config, API and version; don't trust memory. Use installed MCP servers, tools and skills; skip redundant ones.

**Workflow skills (MUST).** When installed, read each from `~/.agents/skills/<name>/SKILL.md` (`retro` has model invocation off) and use it where listed; this protocol wins where they differ, and a confirmation pause is yours to decide or goes to a gate (Pre-authorized).
- `diagnosing-bugs`: unknown-cause failures; phases 1-4 give the red repro and cause in `facts.md`, 5-6 are the plan and step 6.
- `tdd`: appended by `implement.sh` to every brief, with the plan's Tests as the agreed seams.
- `pr`: the step 8 PR body with tier, triggers, gate links and `Shortcuts`.
- `retro`: step 9 after any `fail` or failed round; candidates go in `PROGRESS.md`.
- `setup-pre-commit`: cite it when a task adds commit-time JS/TS hooks or checks; repo tooling wins.
- `codebase-design`: cite it for module interfaces, seams or deep-module refactors.
- `writing-for-agents`: read it before editing any skill, protocol, `AGENTS.md` or `CLAUDE.md`.
- `domain-modeling`: cite it when changing domain terms, `GLOSSARY.md` or ADRs.
- `research`: recent docs, APIs or versions; findings go in `EVID`.
- `prototype`: throwaway before planning when state-model or UI needs validation.
- `wizard`: human-only manual setup or migration; never for agent-executable steps.
- `grilling` (method only): order `facts.md` open decisions as a frontier tree for the plan gate, never for Rahi.
- Formal `gate.sh` gates (step 7) are the only code review; run no in-session review pair.

**Local ds-* skills (MUST).** At task start and whenever the scope changes, dynamically scan `~/.agents/skills/ds-*/SKILL.md` (excluding `ds-dev-protocol` itself) and inspect each YAML frontmatter (`name`, `description`, `disable-model-invocation`); there is no static list, so a newly added or updated skill is picked up automatically. Skip a skill whose frontmatter says `disable-model-invocation: true` unless the request names it explicitly; read and apply a matching skill at its phase. This protocol and the repo `AGENTS.md`/`CLAUDE.md` take precedence, a confirmation pause is pre-authorized, and an installed copy under `~/.agents/skills/` is never edited.

## 5. Isolate

Never commit to main. One branch and worktree per workstream, cut from the latest default branch; one owner per file set. Independent work runs in parallel, scaled to quota and machine; dependent work in order. Read-only research needs no worktree.

**Lanes.** At most 6 concurrent lanes; an independent workstream with a disjoint file set gets its own worktree and EVID (`<task>-<lane>`), running `implement.sh` there. In-session subagents only for bounded read-only lookups; never two sessions on one file set.

**Changes outside a repository, and work with no code diff** (settings, permissions, hooks, policy and instruction files, skills, MCP and harness config, credentials; no-code tasks): the same tiers and gates apply, no PR. Tier by step 2; permissions, allow-rules, hooks, routing/policy, secrets and credential config are always **High**. A skill installed from a source repository changes through the normal PR flow, and the installed copy is never edited first. Never edit the live file: back it up to `EVID/backup/`, change a copy, save `EVID/outside-<name>.diff`, gate it (diff sha256), apply only after it passes, verify the tool loads, and restore on failure. No-diff work: `EVID/op-<name>.md` holds the commands, targets and pass criteria; gate and check it with `gate.sh <gate> <tier> --diff` and `premerge-and-merge.sh --diff`, run only after exit 0, and keep results in `PROGRESS.md` and the report (a new edit needs a new gate). List every outside change, its tier, gate file and verification in the report.

## 6. Implement through implement.sh, test-first, and verify locally

RED → GREEN → REFACTOR for behavior changes, plus a regression test per bug fix. Match repo conventions; no unrelated changes. Run the repo's lint, types, tests and build, plus E2E/UI checks when affected; all MUST pass before any review gate. For E2E/UI run locally only what PR CI does not run; CI green on the head (step 8) covers the rest. Never skip hooks, delete tests or loosen gates. For a bug fix the conductor confirms RED itself in a scratch detached worktree at the step's base with only the step's tests, records `RED confirmed: <cmd> -> <failing line>` in `PROGRESS.md`, and rejects a setup failure, not the bug (`implement.sh --discard`, rerun with `--notes`). The implementer's own RED claim never counts.

**Implementation (MUST).** Each step runs from the root of its clean, linked task worktree:

```sh
EVID=~/.local/state/dev-evidence/<task> "$SKILL/scripts/implement.sh" <low|medium|high> --bootstrap '<setup cmd>|none' [--step NAME] [--notes FILE] [--trigger]
```

The brief comes from the last logged plan; attempts log to `EVID/impl.log`. Exit codes 0-5 and worktree recovery are in `reference.md`; read, run, bootstrap or commit nothing from an **Exit 6** worktree, remove it from the main checkout with `git worktree remove --force <wt>`, never reuse the path, and continue from the last accepted commit in a fresh worktree. After a killed run, `implement.sh --discard --bootstrap <cmd|none>` resets the worktree and the bootstrap is recorded in `PROGRESS.md`.

**Mechanical runner:** the implementer is the mechanical `implement.sh` runner, no OS sandbox (`variant: high`, `cost == 0`), scoped by `opencode/opencode.json`; a delimiter leak or premature stop gets one bounded resume, and the conductor covers `not_checked` before any gate (`reference.md`).

## 7. Review gates (MUST pass before merge)

| Tier | Gate(s) | Reviewer |
|---|---|---|
| Low | `review` | Reviewer, `medium` (`high` on a trigger) |
| Medium | `review` | Reviewer, `medium` (`high` on a trigger) |
| High | `review` and `security` (separate fresh children) | Reviewer, `medium` (`high` on a trigger) |

**Every gate runs through `scripts/gate.sh` (MUST),** including a program-level plan (own EVID), re-reviews and the `epoch` decision. Each gate is a T3 `delegate_task` child; never run a model call yourself, and a gate recorded any other way did not happen. From the task worktree:

```sh
SKILL=~/.agents/skills/ds-dev-protocol
EVID=~/.local/state/dev-evidence/<task> "$SKILL/scripts/gate.sh" <plan|review|security|epoch> <low|medium|high> --record EVID/raw-<gate>-<key>.json --child-thread <id> --parent-thread <id> [--high-effort <tags>] [--trigger] [--ui] [--diff FILE] [--base REF]
```

`--record` checks the child thread, provenance and tree integrity against T3 Code itself, and refuses a packet missing the key, `Gate: <gate>` or the exact diff. `--high-effort <tags>` selects allowlisted triggers and `--trigger` is the backward-compatible alias (`legacy-trigger`); epoch always runs `high` and takes neither tag nor `--trigger`. `target.options.<option_key>` must equal the gate's effort or the gate fails closed. `--ui` is valid on `plan` and `review` only; it requires `Scope: ui` in the packet and uses Section 1's UI chain. `security` and `epoch` never take `--ui`. Exit 0 pass or valid `plan`; 1 `fail`; 2 usage, precondition or provenance mismatch; 3 blocked; 4 round cap. Rounds: 3 per plan, 6 per gate/epoch. Agent config (`opencode.json`, `.opencode/`, `.claude/`, `.agents/`, `AGENTS.md`, `CLAUDE.md`) is never Low (`reference.md`).

**Gemini & Claude `safety refusal`:** a child whose stop or finish reason reports a safety refusal, or whose error or notice carries a safety mark, logs `blocked`, reason `safety refusal`, exit 3, at every gate including non-UI `plan`; never retried as invalid JSON, never `pass`.

**Packet** (`EVID/packet-<gate>.md`): gate, tier/triggers, request, acceptance criteria, 40-char base/head SHA (or diff sha256), full diff; with `--ui` it also carries `Scope: ui`; review/security also carry the plan's `risks` verbatim under `## Plan risks`, `REVIEW.md` and a Trail blast (`reference.md`). NEVER include implementer summaries, rationales or secrets (remove and rotate, never redact).

Every reviewer checks the claimed tier against the diff; an under-classified tier is `important` and re-enters at the correct tier. Never resume a gate session; a `fail` verdict is a valid run.

**Verdict rules:**
- A gate passes only with `verdict: "pass"`, zero `important` findings and the exact 40-character head SHA in the file name and `head_sha` (every tier and round; never `review-r2.json`-style names); outside-repo gates use the diff's 64-character sha256.
- `important` findings are fixed through `implement.sh --step fix-<gate>-r<n> --notes <findings>`, re-verified (step 6), then re-reviewed by a fresh `gate.sh` child with the full packet plus a section headed exactly `## Changes since the last round`: the last reviewed key, the diff since it, and each finding with its fix or reason. Later rounds add `important` only for that code, an unresolved fix, an under-classified tier or an exploitable security issue; other unchanged-code issues are `pre-existing`.
- Any new commit after a pass invalidates it; re-review the delta for the new head.
- After round 3, rethink: a new Planner plan (step 3), then build and gate it; a Low task at the cap becomes Medium and the turn continues. If that fails 3 more rounds, run the epoch rule; a fail records the gate blocked in `PROGRESS.md` and you finish other work.
- **Epoch rule.** A new plan epoch needs a passing `epoch` gate. After a `review` or `security` block at the cap, write facts-only `EVID/epoch.md` and `EVID/packet-epoch.md`, then run a fresh Reviewer via `gate.sh epoch <medium|high> --record`. Pass authorizes one epoch: rounds restart and a new planner plan precedes any review; `fail` is final, `blocked gate`. At most 2 per EVID, then `blocked` exit 3; never open a new EVID to dodge a block.
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

It runs `reference.md`'s checks, writes them into the PR body and squash-merges with `--match-head-commit`; outside a repo, `--diff FILE` runs them on the diff sha256, no `gh`. `PLAN.md` and the re-check need a `Tier:` line. `--no-ci` only for a repo with no CI, and only when `gh pr checks` reports no checks and neither the worktree nor `origin/<base>` has `.github/workflows`. Exit 1 means no merge.

**Update from main before the tier re-check and final gate.** If main moves after the final gate, an earlier gate carries only when the PR diff is byte-identical (`CARRY <gate> <old> -> <new>`, logged); otherwise re-gate the new head. Combined work: integrate, retest, re-gate and merge; check production if auto-deployed.

## 9. Clean up

Remove only branches, worktrees and processes you verified as merged; never touch unrelated or unmerged work. If lasting lessons came up, run the matching discovered local ds-* skill from Section 4; use the repo-wide reconciliation skill only for stray-work reconciliation.

## 10. Report in a few lines

Report what's done, tier, triggers, evidence (commands, results, PR/CI links), each gate's verdict, implementer route per step, conductor effort and child-thread ids, blocked gates or epochs, open `Shortcuts`, carried `Not checked` items and blockers; never call unverified work done.
