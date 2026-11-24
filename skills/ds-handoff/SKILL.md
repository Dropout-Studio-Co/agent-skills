---
name: ds-handoff
description: Safe Switch — output a copyable session handoff (no args) or hand off and continue in a fresh session (with args).
argument-hint: "Optional: next-session task or 'continue' (omit for copyable handoff only)"
disable-model-invocation: true
---

# Safe Switch (`ds-handoff`)

Run only on explicit user invocation (`/ds-handoff` or `"Safe Switch"`). Never auto-trigger, never trigger for quota, usage, or rate limits, and never use as an automatic fallback.

## Mode Selection

Choose the mode from whether the invocation includes an argument (or a continuation instruction after `"Safe Switch"`):

- **No argument → Mode 1: Handoff Only.** Output a copyable handoff directly in your response.
- **Any argument → Mode 2: Handoff and Continue.** Incorporate the argument into a durable handoff and launch a fresh session seeded with it:
  - **Simple continuation** (`continue`, `carry on`, `resume`, `keep going`): continue from the exact next uncompleted step.
  - **Specific directive** (any next task, pivot, focus, or detailed instruction): make the argument the new session's primary mission and first action while preserving relevant context, verified state, constraints, and dead ends.

## 1. Settle the Current Session

- Finish or stop any mid-write edit so nothing is left half-applied. Do not start new work.
- Wait for short owned commands to finish; for any still-running background task or process, record its task ID, output path, and PID.
- Leave git state untouched: do not commit, push, stash, reset, or clean anything just for the switch.

## 2. Capture Verified State (Facts, Not Memory)

Run read-only commands; never write git, PR, or check values from recollection. Once step 1 settles the session, batch these read-only git and PR/CI checks concurrently across every touched repository and worktree; keep all other steps strictly serial with no subagents (never delegate handoff synthesis).

For every git repository or worktree touched in this session (skip git checks if no repo was touched):

- `git -C <path> rev-parse --show-toplevel`, current branch, `HEAD` SHA, upstream, and ahead/behind counts.
- `git -C <path> status --porcelain` (dirty and untracked files; mark each as session-owned or foreign).
- Active worktrees (`git -C <path> worktree list`), open PR numbers/URLs, CI/check status, and merge/deploy status (`gh-axi` or `gh` if available).

Also inventory:

- Originating runtime identity (current harness, model, effort, and any user-requested axis change).
- Checks run with exact commands, results, and evidence paths.
- Review findings (fixed and open).
- Pending operations (with exact next commands), running workers or background tasks, and open blockers.
- Active runtime resources (dev servers, ports, browser tabs, simulators/emulators, device connections such as `adb`/`sdb`, native builds, app windows/preview sessions, and lock/turn claims).

## 3. Build the Handoff (Structured Markdown)

Use **Structured Markdown** with the fixed sections below. Omit sections that do not apply (for example, omit git fields in a non-code conversation) rather than writing filler.

1. **Objective & Scope** — The goal, accepted constraints, and what done means.
2. **Next Session Directive** —
   - *Mode 1*: Concrete next action(s) for whoever picks up the work.
   - *Mode 2*: Incorporate the user's argument directly (quoting specific instructions verbatim so nuance is preserved) as the primary mission — either exact continuation from the next uncompleted step, or the requested new task/focus — plus the single concrete first step.
3. **Status** — Completed, in progress, not started, and open blockers.
4. **Verified State** — Live facts from step 2: originating runtime (harness, model, effort, and any user-requested switch target), repo paths, branches, SHAs, PRs, dirty/untracked files with ownership, checks and evidence paths, running tasks, and active runtime resources. Mark any unverified belief or hypothesis explicitly as `(unverified)` so the next session never treats an assumption as fact.
5. **Pending Operations** — Exact next command or action for each queued/in-flight operation; mark operations that must not repeat.
6. **Decisions, Findings & Dead Ends** — Decisions made and *why* (do not re-open), review findings (fixed and open), and approaches already tried and why they failed (do not repeat).
7. **Key Artifacts** — Paths or URLs to specs, plans, ADRs, issues, commits, diffs, and evidence files. Reference them; do not duplicate their contents.
8. **Suggested Skills** — Skills the next session should load (include `ds-dev-protocol` only if it was explicitly invoked for this task).
9. **Resume Rules** — In Mode 2, prepend a concrete runtime-verification bullet naming the recorded expected harness, model, and effort from Verified State (or the user-requested target, or `ds-dev-protocol` routing if `ds-dev-protocol` was explicitly invoked for this task), instructing the new session to stop and report on mismatch rather than substituting silently. In both modes, include these two rules verbatim:
   - Re-check every SHA, branch, dirty file and PR state in Verified State against live state before acting on repo or PR state. If anything differs, reconcile it first; treat unexplained changes as foreign work.
   - Never repeat a completed or already-applied operation. Start directly from the Next Session Directive.

## Pre-Delivery Gate: Redaction

Before outputting or writing the handoff, strip all API keys, tokens, passwords, secrets, and personal data.

## 4. Deliver by Mode

### Mode 1 — Handoff Only (No Arguments)

- Output the complete handoff directly in your response inside a single markdown code fence longer than any backtick run inside the handoff (default four backticks: ` ````markdown ... ```` `).
- Do not write files, launch a session, or run any other actions. Stop once the handoff is delivered.

### Mode 2 — Handoff and Continue (With Any Argument)

- **Save durably:** Expand `~`, create `${XDG_STATE_HOME:-~/.local/state}/ds-handoff` with mode `0700`, and write `${XDG_STATE_HOME:-~/.local/state}/ds-handoff/<YYYYMMDD-HHMMSS>-<slug>.md` (UTC timestamp; `<slug>` as safe ASCII kebab-case `[a-z0-9-]+` derived from the task/argument) directly with mode `0600` so there is no world-readable window. Use durable storage, never OS temp.
- **Preserve routing:** Keep the current session's harness, model, effort, provider, account, and billing — and preserve worker routing (implementer, gates, and helpers stay as configured) — unless the user explicitly requested a specific axis change (or `ds-dev-protocol` was explicitly invoked for this task, in which case its routing rules apply).
- **Launch (if supported):** Launch a new top-level session/thread (never a child subagent, so continued work survives this session's exit) in the work's directory using the harness's native session-launch tool or command. Name it from the task/argument, pass the saved handoff file's contents as its prompt (preventing shell expansion of backticks or `$`), and pass model or effort overrides ONLY for an axis the user explicitly asked to change (otherwise leave defaults untouched). Confirm the new session started; on failure, keep the handoff file, report the exact error, and do not retry with another harness, model, or flag set.
- **Fallback (if no automated launch):** Do not invoke another harness's CLI. Keep the handoff file on disk and give the user its path with a short ready-to-paste resume instruction pointing to it.
- **Close out:** Stop acting on the work in this session (the new session owns it now). Reply with the handoff file path and either the launched session identifier and how to open/attach to it, or the fallback resume instruction.
