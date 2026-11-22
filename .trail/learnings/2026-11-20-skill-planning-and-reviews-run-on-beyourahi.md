---
title: "Skill planning and reviews run on Opus only, with no fallback, and an outage blocks"
author: Beyourahi
date: 2026-11-20
branch: main
id: l-a891fc8d
scope: repo
status: superseded
src: agent
touches:
  - skills/dependency-upgrade/scripts/review_router.py
  - skills/consolidate/SKILL.md
  - skills/sync-agent-instructions/scripts/collect_sessions.py
---

## Decided
- The shared plan/review router runs Claude Opus 5.5 only: plans at xhigh, reviews at medium (high for security, independent, --high or a profile "effort": "high"). There is no DeepSeek or invoking-session fallback; an Opus outage makes the task unavailable and blocks the gate. This follows the 2026-11-14 routing rule (Opus plans and gates, DeepSeek only implements).
- A required review remembers the highest effort ever asked for it, so a later medium pass never satisfies a high requirement.
- consolidate decides alone from evidence, keeps anything uncertain, and pastes its restore-point manifest and bundle-verify output into the ledger, because the reviewer cannot read the restore-point folder.

## Tried and ruled out
- Routing these skills through the execution protocol's gate.sh: its packets must bind an exact git diff, while consolidate's reconciliation review covers a git inventory (branches, worktrees, stashes, clones, PRs) that is not a diff.
- Restoring a backup tar of installed skills as a rollback: with the sync watcher live, the restored trees look like local edits and get pushed to public main without review. Roll back with a revert PR instead.

## Watch out
- Opening OpenCode's WAL-mode SQLite store with mode=ro when no -wal/-shm files exist creates them next to the store. Use immutable=1 when there is no -wal, plain mode=ro only when both -wal and -shm exist, and skip otherwise.
- The 2026-11-09 learning about the OpenCode reviewer sandbox now points at deleted code; the sandbox went away with the DeepSeek route.

In the code: skills/dependency-upgrade/scripts/review_router.py (PREFERRED, PLAN_EFFORT, route), routed_task.py (cmd_review effort, mark_required, required_efforts, cmd_gate), skills/consolidate/SKILL.md STEP 3, skills/sync-agent-instructions/scripts/collect_sessions.py opencode_sessions. PR #22.
