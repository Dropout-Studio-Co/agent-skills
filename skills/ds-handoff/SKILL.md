---
name: ds-handoff
description: Safe Switch. Produce a copyable session handoff (no args) or hand off and continue in a fresh session with a next-step directive (with args). Manual invocation only.
argument-hint: "Optional: next-session task or 'continue' (omit for copyable handoff only)"
disable-model-invocation: true
---

# Safe Switch (`ds-handoff`)

Because `disable-model-invocation: true` prevents harnesses that enforce it from auto-loading this skill, invoke it explicitly: `/ds-handoff`, or say "Safe Switch" when the skill is manually loaded or routed by user policy. Never trigger automatically, never for quota, usage or rate limits, and never as an automatic fallback.

## Mode Selection

Choose the mode from whether the invocation includes an argument (or a continuation instruction after "Safe Switch"):

- **No argument → Mode 1: Handoff Only.** Gather verified state, output a complete copyable handoff directly in your response, and stop. Do not save files, start a new session, or perform any additional actions.
- **Any argument → Mode 2: Handoff and Continue.** Gather verified state, incorporate the argument into the handoff, save it durably, and start a fresh session seeded with it.
  - **Simple continuation** (`continue`, `carry on`, `resume`, `keep going`): continue the current work from the exact next uncompleted step.
  - **Specific directive** (any next task, pivot, focus, or detailed instruction): make the argument the new session's primary mission and first action while preserving all relevant context, verified state, constraints, and dead ends.

## 1. Settle the Current Session

- Finish or stop any mid-write edit so nothing is left half-applied. Do not start new work.
- Wait for short owned commands to finish; for any still-running background task or process, record its task ID, output path, and PID.
- Leave git state untouched: do not commit, push, stash, reset, or clean anything just for the switch.

## 2. Capture Verified State (Facts, Not Memory)

Run read-only commands; never write git, PR, or check values from recollection. Once step 1 has
settled the session, batch these read-only git and PR/CI checks concurrently across every touched
repository and worktree; all other steps stay strictly serial with no subagents (never start new work
and never delegate handoff synthesis).

For every git repository or worktree touched in this session (skip git checks if no repo was touched):

- `git -C <path> rev-parse --show-toplevel`, current branch, `HEAD` SHA, upstream, and ahead/behind counts.
- `git -C <path> status --porcelain` (dirty and untracked files; mark each as session-owned or foreign).
- Active worktrees (`git -C <path> worktree list`), open PR numbers/URLs, CI/check status, and merge/deploy status (`gh-axi` or `gh` if available).

Also inventory: checks run with exact commands, results, and evidence paths; pending operations (with exact next commands); running workers or background tasks; active runtime resources (dev servers, ports, browser tabs, simulators/emulators, device connections such as `adb`/`sdb`, native builds, app windows/preview sessions, and lock/turn claims); and open blockers.

## 3. Build the Handoff (Structured Markdown)

Use **Structured Markdown** with the fixed sections below. Omit sections that do not apply (for example, omit git fields in a non-code conversation) rather than writing filler.

1. **Objective & Scope** — The goal, accepted constraints, and what done means.
2. **Next Session Directive** —
   - *Mode 1*: Concrete next action(s) for whoever picks up the work.
   - *Mode 2*: Incorporate the user's argument directly (quoting specific instructions verbatim so nuance is preserved) as the primary mission — either exact continuation from the next uncompleted step, or the requested new task/focus — plus the single concrete first step.
3. **Status** — Completed, in progress, and not started.
4. **Verified State** — Live facts from step 2 (paths, branches, SHAs, PRs, dirty/untracked files with ownership, checks and evidence paths, running tasks, active runtime resources). Mark any unverified belief or hypothesis explicitly as `(unverified)` so the next session never treats an assumption as fact.
5. **Pending Operations** — Exact next command or action for each queued/in-flight operation; mark operations that must not repeat.
6. **Decisions & Dead Ends** — Decisions made and *why* (do not re-open), plus approaches already tried and why they failed (do not repeat).
7. **Key Artifacts** — Paths or URLs to specs, plans, ADRs, issues, commits, diffs, and evidence files. Reference them; do not duplicate their contents.
8. **Suggested Skills** — Skills the next session should load (include `ds-dev-protocol` only if it was explicitly invoked for this task).
9. **Resume Rules** (include verbatim):
   - *(Mode 2 only)* First verify runtime: confirm the new session matches the current harness, model and effort level (or any axis the user explicitly asked to change, or `ds-dev-protocol` routing if `ds-dev-protocol` was explicitly invoked for this task). On mismatch, stop and report; never substitute silently.
   - Re-check every SHA, branch, dirty file and PR state in Verified State against live state before mutating anything. If anything differs, reconcile it first; treat unexplained changes as foreign work.
   - Never repeat a completed or already-applied operation. Start directly from the Next Session Directive.

**Redaction:** Strip all API keys, tokens, passwords, secrets, and personal data before outputting or saving.

## 4. Deliver by Mode

### Mode 1 — Handoff Only (No Arguments)

- Deliver the complete handoff directly in your response inside a single four-backtick fenced block (` ````markdown ... ```` `) so internal code blocks never break copy-paste.
- Do not write files, launch a session, or run any other actions. Stop once the handoff is delivered.

### Mode 2 — Handoff and Continue (With Any Argument)

- **Save durably:** Write the handoff to `${XDG_STATE_HOME:-~/.local/state}/ds-handoff/<YYYYMMDD-HHMMSS>-<slug>.md` (create the directory; UTC timestamp; mode `0600`; expand `~` before writing; durable storage, not OS temp).
- **Preserve harness, model, and effort:** Keep the current session's harness, model, and effort level without switching, selecting, or enforcing another model, harness, provider, account, billing, or effort unless the user explicitly requested a specific change (or `ds-dev-protocol` was explicitly invoked for this task, in which case its routing rules apply).
- **If the current harness supports launching a fresh session/thread:** Launch a new top-level session/thread (never a child subagent, so the continued work survives this session's exit) in the work's directory using the harness's native session-launch tool or command. Give it a short descriptive name derived from the task/argument, and pass the saved handoff file's contents as its prompt without overriding model or effort (and without letting the shell expand backticks or `$` inside the handoff). Confirm the new session started. If launch fails, keep the handoff file and report the exact error; do not retry with another harness, model, or flag set.
- **If the current harness has no automated session-launch capability:** Do not invoke another harness's CLI. Keep the verified handoff file on disk and give the user the handoff file path with a short ready-to-paste resume instruction pointing to it.
- **Close out:** Stop acting on the work in this session (the new session owns it now). Reply with the handoff file path and either the launched session identifier and how to open/attach to it, or the fallback resume instruction pointing to the handoff path.
