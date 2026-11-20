---
name: safe-switch
description: Safe Switch. Hand the current work off losslessly to a fresh background Claude Code session that starts automatically and continues from the handoff. Manual invocation only.
argument-hint: "Optional: next-session focus, and/or the Claude model or effort to switch to"
disable-model-invocation: true
---

# Safe Switch

Run only when the user invokes this skill or explicitly says "Safe Switch". Never start it on your own,
never for quota, usage or rate limits, and never as an automatic fallback.

## 1. Settle the current session

- Finish or stop any step that is mid-write so nothing is left half-applied. Do not start new work.
- Wait for running scripts/commands you own to end, or record their task id, output path and PID.
- Do not commit, push, stash, reset or clean anything just for the switch. Record the state as it is.

## 2. Capture the state (facts, not memory)

Run the commands; never write values from recollection. For every repo or worktree touched:

- `git -C <path> rev-parse --show-toplevel`, branch, `HEAD` SHA, upstream and ahead/behind.
- `git status --porcelain` (dirty and untracked files; mark which are session-owned and which foreign).
- Worktrees (`git worktree list`), open PR number/URL, CI/check state, merge and deploy status (gh-axi).

Also record: the task objective and scope, decisions made and why, review findings (fixed / open),
checks run with results and evidence paths, pending operations (with exact next command), running
workers, background tasks, dev servers, ports, browser tabs and turn.sh claims held, and blockers.

## 3. Write the handoff

Save it to `~/.local/state/safe-switch/<YYYYMMDD-HHMMSS>-<slug>.md` (create the folder; durable, not OS temp).
Sections, in order:

1. **Objective** and accepted scope (what done means).
2. **Where things stand**: completed, in progress, not started.
3. **State**: the facts from step 2 (paths, branches, SHAs, PRs, dirty files, checks, evidence paths).
4. **Pending operations**: each with its exact next command or action; mark ones that must not repeat.
5. **Decisions and findings**: with reasons; do not re-open them.
6. **Next action**: the single first step for the new session.
7. **Suggested skills**: which skills the next session should load with the Skill tool
   (always `execution-protocol` for development work).
8. **Resume rules** (copy verbatim):
   - First verify runtime: model and effort match the switch target (default: `~/.claude/settings.json`). On mismatch, stop and report; never substitute.
   - Re-check every SHA, branch, dirty file and PR state in section 3 against live state before acting. If anything differs, reconcile it first; treat unexplained changes as foreign work.
   - Never repeat a completed or already-applied operation. Continue from the next action.

Do not copy what already lives in specs, plans, issues, commits, diffs or evidence files; reference them by path or URL.
Redact secrets, tokens, passwords and personal data; the file becomes the next session's prompt.
If the user passed arguments describing a focus, tailor the handoff to it.

## 4. Launch the new session

From the working directory the work belongs to:

```sh
claude --bg --name "Safe Switch: <short task name>" -- "$(cat <handoff file>)"
```

- Passing the file through `$(cat ...)` keeps the shell from running backticks or expanding `$` inside the handoff.
- Change only the axis the user explicitly named: `--model <id>` for an approved Claude model, `--effort <medium|high>`
  for effort (Medium/High only). Otherwise change nothing: the new session uses the configured default.
  Never switch provider, account or billing, and never change worker routing (implementer, gates, helpers stay as configured).
- Confirm it started: `claude agents` lists it. If launch fails, keep the handoff file and report the exact error; do not retry with other flags.

## 5. Close out

Stop acting on the work in this session (the new session owns it now). Reply with: handoff path,
the background session name, and how to open it: `claude attach "<name>"` (list: `claude agents`).
