---
title: "New skills are published only when they carry an opt-in marker, because the repo is public"
author: Beyourahi
date: 2026-11-16
branch: main
id: l-1c2d21b7
scope: repo
status: active
src: agent
touches:
  - AGENTS.md
  - CONTRIBUTING.md
---

## Decided
- A background job pushes edits to the installed copies of `skills/<name>` straight to main, and installs merged main changes back. A new skill is published only if its folder holds an empty `.agent-skills-sync` marker file.
- Per-skill three-way merge against the last synced tree. If both sides changed, the skill is held and never overwritten.

## Tried and ruled out
- Treating any folder missing from the skills installer lock as "ours": 44 such folders on this machine are third-party, and this repo is public.
- rsync for copying: macOS ships openrsync, so a stdlib mirror is used instead.
- WatchPaths triggers: they fire only on top-level changes, so the job polls every 300 s instead.

## Watch out
- An edit to the installed copy goes to main without review. Agent changes should still use PRs here. AGENTS.md ("Automatic sync") and CONTRIBUTING.md describe the rules.
- The dev clone falls behind main after automatic pushes, so pull before you work in it.

In the code: AGENTS.md, CONTRIBUTING.md, skills/; outside the repo: ~/.agents/bin/agent-skills-sync, LaunchAgent com.beyourahi.agent-skills-sync, ~/.local/state/agent-skills-sync/runs.jsonl
