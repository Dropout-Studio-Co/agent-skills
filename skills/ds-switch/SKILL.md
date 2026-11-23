---
name: ds-switch
description: Safe Switch. Capture verified task state and hand the current work off losslessly to a fresh session using the current harness, model and effort, on explicit request only. Manual invocation only.
argument-hint: "Optional: next-session focus"
disable-model-invocation: true
---

# Safe Switch (`ds-switch`)

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
- Worktrees (`git worktree list`), open PR number/URL, CI/check state, merge and deploy status (`gh-axi` or `gh` if available).

Also record: the task objective and scope, decisions made and why, review findings (fixed / open),
checks run with results and evidence paths, pending operations (with exact next command), running
workers, background tasks, active runtime resources (dev servers, ports, browser tabs, simulators/
emulators, device connections such as `adb`/`sdb`, native builds, app windows/preview sessions, and
lock/turn claims held), and blockers.

## 3. Write the handoff

Save it to `~/.local/state/ds-switch/<YYYYMMDD-HHMMSS>-<slug>.md` (create the folder; durable, not OS temp).
Sections, in order:

1. **Objective** and accepted scope (what done means).
2. **Where things stand**: completed, in progress, not started.
3. **State**: the facts from step 2 (paths, branches, SHAs, PRs, dirty files, checks, evidence paths).
4. **Pending operations**: each with its exact next command or action; mark ones that must not repeat.
5. **Decisions and findings**: with reasons; do not re-open them.
6. **Next action**: the single first step for the new session.
7. **Suggested skills**: which skills the next session should load (include `ds-protocol` only
   if it was explicitly invoked for this task).
8. **Resume rules** (copy verbatim):
   - First verify runtime: confirm the new session matches the current harness, model and effort level (or any axis the user explicitly asked to change, or `ds-protocol` routing if `ds-protocol` was explicitly invoked for this task). On mismatch, stop and report; never substitute silently.
   - Re-check every SHA, branch, dirty file and PR state in section 3 against live state before acting. If anything differs, reconcile it first; treat unexplained changes as foreign work.
   - Never repeat a completed or already-applied operation. Continue from the next action.

Do not copy what already lives in specs, plans, issues, commits, diffs or evidence files; reference them by path or URL.
Redact secrets, tokens, passwords and personal data; the file becomes the next session's prompt.
If the user passed arguments describing a focus, tailor the handoff to it.

## 4. Hand off to the new session

- **Model, harness and effort:** Keep the current session's harness, model and effort level without
  switching, selecting or enforcing another model, harness, provider, account, billing or effort
  unless the user explicitly requested a specific change (or `ds-protocol` was explicitly
  invoked alongside this task, in which case its routing rules apply).
- **If the current harness supports launching a fresh session/thread:** Start one in the work's
  directory using the harness's native session-launch tool or command, passing the handoff file's
  contents as the prompt without overriding model or effort (and without letting the shell expand
  backticks or `$` inside the handoff). Confirm the new session started. If launch fails, keep the
  handoff file and report the exact error; do not retry with another harness, model or flag set.
- **If the current harness has no automated session-launch capability:** Do not invoke another
  harness's CLI. Keep the verified handoff file on disk and give the user the handoff file path
  with a short ready-to-paste resume instruction pointing to it.

## 5. Close out

Stop acting on the work in this session (the new session owns it now). Reply with: the handoff file
path, and either the launched session identifier and how to open/attach to it, or the resume
instruction pointing to the handoff path.
