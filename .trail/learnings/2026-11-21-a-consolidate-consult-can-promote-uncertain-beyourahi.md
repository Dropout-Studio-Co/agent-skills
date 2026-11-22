---
title: A consolidate consult can promote uncertain work only with evidence the owner controls
author: Beyourahi
date: 2026-11-21
branch: main
cost: { minutes: 12, tokens: 182236 }
id: l-bea55df2
scope: repo
status: superseded
src: agent
touches:
  - skills/consolidate/SKILL.md
  - skills/consolidate/routing.json
  - skills/dependency-upgrade/references/review-routing.md
  - skills/dependency-upgrade/scripts/review_router.py
  - skills/dependency-upgrade/scripts/routed_task.py
  - skills/dependency-upgrade/tests/test_routed_task.py
  - skills/sync-agent-instructions/scripts/collect_sessions.py
  - skills/sync-agent-instructions/tests/test_collect_sessions.py
  - skills/execution-protocol/scripts/premerge-and-merge.sh
  - skills/execution-protocol/scripts/gate.sh
---

## Decided
- When consolidate cannot settle a decision, it consults Opus 5.5 High through the shared router as an advisory, read-only task. Plans stay at xhigh.
- An uncertain item becomes still-needed only with verified evidence the repository owner controls: their own open PR or issue, or code in main that depends on it.
- An unsettled item stays kept. An unsettled build, test or review problem stops the run with no push and no cleanup.

## Tried and ruled out
- Accepting any open PR or issue as proof the work is wanted: on a public repo an outsider could get abandoned code pushed to main.
- Keeping an item after an aborted conflict when earlier commits from it already landed: the push would publish half of a kept item.
- Web access for consults: they read untrusted branch text, so it would open an exfiltration path.

## Watch out
- The gate does not hash the ledger, so re-running the reconciliation review after a consult changes the ledger is a skill instruction, not enforced by code.

In the code: skills/consolidate/SKILL.md CONSULT, skills/consolidate/routing.json consult kind, skills/dependency-upgrade/scripts/routed_task.py cmd_plan. PR 23.
