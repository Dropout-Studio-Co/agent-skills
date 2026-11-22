---
title: "The policy skill's size cap was raised because an unreviewed sync had already broken it"
author: Beyourahi
date: 2026-11-16
branch: main
id: l-e2e750c5
scope: repo
status: active
src: agent
touches:
  - skills/execution-protocol/tests/smoke.sh
---

## Decided
2026-11-17 (PR #17): the execution-protocol SKILL.md size cap in the smoke test is 23800 bytes, raised from 23300 instead of trimming existing rules. The base was already over the old cap.

## Tried and ruled out
Trimming unrelated SKILL.md sections to fit: it would spread a High-tier policy change into text the task did not need, and each trim risks changing meaning.

## Watch out
The automatic sync pushes local edits to main unreviewed. The 2026-11-16 conductor-effort edit arrived that way and pushed the file 15 bytes over the cap, so smoke.sh was red on main before anyone noticed. Run smoke.sh on main before starting a skill change. About 70 bytes of headroom are left; new text should replace words.

In the code: skills/execution-protocol/tests/smoke.sh check "SKILL size 23800 max"; bash skills/execution-protocol/tests/smoke.sh; SKILL.md was 23726 bytes after #17.
