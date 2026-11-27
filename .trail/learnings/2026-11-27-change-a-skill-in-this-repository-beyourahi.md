---
title: "Change a skill in this repository through a PR, never in the installed copy"
author: Beyourahi
date: 2026-11-27
id: l-b22180d0
scope: repo
status: active
replaces: l-fee4a0a0
src: agent
touches:
  - AGENTS.md
  - skills/ds-dev-protocol/SKILL.md
---

## Decided
- `skills/<name>/` in this repository (for example `skills/ds-dev-protocol/`, formerly `skills/execution-protocol/`) is the source of truth; `~/.agents/skills/<name>` is only an installed plain copy.
- The LaunchAgent `com.beyourahi.agent-skills-sync` runs `~/.agents/bin/agent-skills-sync`, which syncs both ways: a local edit under `~/.agents/skills/<name>` is committed and pushed straight to `main` without review. So change a skill only through a PR here, never in the installed copy.
- After the merge, install the change at once with `~/.agents/bin/agent-skills-sync` (or the rsync in `AGENTS.md`), then run the drift check `diff -rq -x __pycache__ -x graft skills/<name> ~/.agents/skills/<name>`; it must print nothing.

## Tried and ruled out
- Symlinking the installed copy into a checkout: it would run unmerged branch code as live policy.
- Restoring a backup tar of installed skills as a rollback: the watcher pushes it to `main` as a local edit. Roll back with a revert PR instead.

## Watch out
- The old `skills/execution-protocol/` path is now `skills/ds-dev-protocol/`; the same source-of-truth and PR-only rules cover every `ds-*` skill, and a file deleted here must also be removed from the installed copy by hand.

In the code:
- `AGENTS.md` (Automatic sync), `~/.agents/bin/agent-skills-sync` (watcher and sync).
