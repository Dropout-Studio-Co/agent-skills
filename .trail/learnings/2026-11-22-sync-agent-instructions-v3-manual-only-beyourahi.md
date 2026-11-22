---
title: sync-agent-instructions v3.0 is manual only and replaces backpass-daily
author: Beyourahi
date: 2026-11-22
branch: main
id: l-sync3022
scope: repo
status: active
src: agent
touches:
  - skills/sync-agent-instructions/SKILL.md
  - skills/sync-agent-instructions/scripts/collect_sessions.py
  - skills/sync-agent-instructions/scripts/check_instructions.py
---

## Decided
- `/sync-agent-instructions` v3.0 (`beyourahi/agent-skills` PR #24, `23ddd902`) enforces git common-dir session matching, human-evidence filtering, redaction, repo-truth reference checking, token budgeting, and typed-claim gating (`check`, `stage`, `gate`, `apply`) on manual runs.
- `backpass-daily` automation is retired and removed; instruction updates happen manually through `/sync-agent-instructions`.

## Tried and ruled out
- Unattended scheduled `backpass-daily` landings via LaunchAgent: removed per owner decision in favor of manual `/sync-agent-instructions`.

## Watch out
- `check_instructions.py` enforces strict symlink/path containment (`_path_escapes_root`), `Move.target` pre-validation before stage reads, and POSIX comment-aware command tokenization (`shlex.split(..., comments=True)`) so inline shell comments with apostrophes or comment placeholders do not misclassify commands.
