---
title: "Skill planning and reviews use review_task.py and routing.json, not an Opus-only router"
author: Beyourahi
date: 2026-11-27
id: l-afaab136
scope: repo
status: active
replaces: l-a891fc8d
src: agent
touches:
  - skills/ds-deps-upgrade/scripts/review_task.py
  - skills/ds-consolidate/SKILL.md
  - skills/ds-agent-docs/scripts/collect_sessions.py
  - skills/ds-dev-protocol/routing.json
---

## Decided
- The old Opus-only `review_router.py` / `routed_task.py` are gone. Sibling skills (ds-deps-upgrade, ds-consolidate, ds-ui-overhaul) use `skills/ds-deps-upgrade/scripts/review_task.py`: it is model- and harness-agnostic, prepares fresh-context read-only plan/review tasks bound to the candidate fingerprint, records outputs with receipts and gates required reviews, and never selects or invokes a model or effort. The invoking session runs them, or `ds-dev-protocol` routing applies when that protocol is invoked.
- `ds-dev-protocol` model routing lives only in `skills/ds-dev-protocol/routing.json`: medium/high efforts only, plus separate conductor, implementer and gate (plan/review/security/epoch) routes. Never hardcode a model in scripts or learnings: change `routing.json`, then run `python3 -I skills/ds-dev-protocol/scripts/routing_lib.py sync`.
- consolidate reconciliation review covers a git inventory (branches, worktrees, stashes, clones, PRs), not a diff, so it does not go through `gate.sh`.
- `skills/ds-agent-docs/scripts/collect_sessions.py` opens OpenCode WAL SQLite with `mode=ro&immutable=1` when no `-wal` file exists, because plain `mode=ro` creates `-wal`/`-shm` next to the store.

## Tried and ruled out
- Routing these skills through the execution protocol gate.sh: its packets must bind an exact git diff, while the reconciliation review covers a git inventory that is not a diff.
- Restoring a backup tar of installed skills as a rollback: with the sync watcher live, the restored trees look like local edits and get pushed to `main` without review. Roll back with a revert PR instead.

## Watch out
- The old paths `skills/dependency-upgrade/`, `skills/consolidate/` and `skills/sync-agent-instructions/` are now `skills/ds-deps-upgrade/`, `skills/ds-consolidate/` and `skills/ds-agent-docs/`; references to `review_router.py` and `routed_task.py` point at deleted code.

In the code:
- `skills/ds-deps-upgrade/scripts/review_task.py` (prepare/record/gate), `skills/ds-dev-protocol/routing.json`, `skills/ds-agent-docs/scripts/collect_sessions.py` (opencode sessions), `skills/ds-consolidate/SKILL.md` (reconciliation review).
