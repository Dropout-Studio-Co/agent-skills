---
name: consolidate
description: Get all unfinished work from every branch, worktree, clone, stash and PR into main, then delete only what is proven to be in main, after a restore point. Use when the user says "consolidate".
---

Consolidate and clean up this repo: get every piece of still-needed work into main, and remove only
what evidence proves is already safe. This run is fully autonomous: never ask a question, never pause
for confirmation, and never wait. Decide from the evidence below and the repository's own
instructions. Keep anything uncertain.

SCOPE (include work created by the user AND by any AI agent/harness/model):
- All worktrees registered to this repo (`git worktree list`), wherever they live on disk
- Other clones/copies of this repo anywhere on the computer (search the home dir and common
  agent/temp dirs for git repos whose remote matches this repo's origin)
- All local branches, stashes, and uncommitted/untracked changes in every location above
- All remote branches and open PRs on GitHub (use `gh`)

STEP 1 — AUDIT (read-only):
- Fetch and prune remotes. Update main to the latest.
- For every branch/worktree/clone/stash/PR, collect the facts that are NOT already in main:
  unmerged commits (`git cherry main <ref>`, `git log main..<ref>`), uncommitted changes, untracked
  files, ignored files, and 24-hour activity (`git log -1 --format=%cI`, file mtimes).
- Start the routing run now (`$R`: see ROUTING), on main at its pre-consolidation commit:
  `python3 $R start --skill consolidate --repo . --base <main SHA>` (every review compares against
  this base).
- CLASSIFY every item into exactly one of four evidence classes:
  - **(a) in main**: `git cherry main <ref>` shows no `+` line, or the tip is an ancestor of main
    (`git merge-base --is-ancestor <tip> main`). For a stash or uncommitted change, its patch
    reverse-applies cleanly on main (`git apply -R --check`). For an untracked file, the same blob
    exists at that path in main.
  - **(b) superseded**: only with a cited main commit SHA and file:line in the ledger that show the
    replacement.
  - **(c) still-needed**: unique work that is not (d).
  - **(d) keep**: uncertain; in-progress (`lsof -a -d cwd` shows a live process inside the location,
    or files/commits changed within 24 h); foreign (PR or branch author other than `gh api user`,
    forks, bots); or holding ignored files other than reproducible caches (`node_modules`, build
    output, `.venv`, `__pycache__`). A (d) item is never integrated, deleted, dropped or closed.
- PLAN (read-only, before any integration decision or mutation): when there is still-needed work,
  write a handoff (scope, the audit ledger with every item, its class and its evidence, repo
  instructions, constraints, conflict risks) and run ONE routed planning task (see ROUTING). Add
  `--kind architecture --subject <item>` only for a significant/high-risk item (diverged design,
  big conflict, schema/auth/deploy changes). Skip it when everything is (a) or (b). Check the
  returned plan against these rules and the repo's instructions; adopt or reject each part with a
  reason. The plan never deletes anything. If planning is `unavailable`, change nothing, report the
  blocker and stop.
- Write the audit summary table (with the adopted plan, every kept item and its reason, and the
  deletion evidence) into the run report and continue. Nothing pauses here.

RESTORE POINT (write it before STEP 2, and again after the gate, before STEP 4):
- Location: `${XDG_STATE_HOME:-~/.local/state}/consolidate/<repo>/<UTC>/`, outside the repository.
- For every stash entry and every worktree HEAD, create a temporary ref:
  `git update-ref refs/consolidate/<UTC>/stash/<n> stash@{n}` and
  `git update-ref refs/consolidate/<UTC>/worktree/<name> <worktree HEAD SHA>`.
- `git bundle create <path>/repo.bundle --all` and then `git bundle verify <path>/repo.bundle`.
- A bundle per extra clone (`git -C <clone> bundle create <path>/<clone>.bundle --all`, verified).
- For every dirty location, a patch (`git diff --binary HEAD` plus staged and untracked data) and an
  archive of its untracked files.
- `manifest.md` with the restore commands for every ref, bundle, patch, archive, remote branch and
  PR, plus the exact commit and path each item came from, including the command that recovers the
  temporary refs from the verified bundle.
- A cleanup never starts unless the restore point for every item on the cleanup list is present and
  verified in the manifest.
- After STEP 4 and the final report, delete this run's temporary refs
  (`git for-each-ref --format='%(refname)' refs/consolidate/<UTC>/ | xargs -n1 git update-ref -d`):
  the verified bundle keeps them.

STEP 2 — RECONCILE:
- Bring every (c) item into main by merging, cherry-picking, or porting by hand if main has diverged.
  Resolve conflicts in favor of main's current design.
- Never integrate a (d) item.
- Commit any uncommitted work you need to keep before integrating it.
- Build and run the tests. Fix anything broken. Push main.

STEP 3 — VERIFY:
- Re-check every branch, worktree, stash, clone and PR against the updated main and record the
  evidence for each item in the ledger, together with the restore-point path, the cleanup list
  ((a)/(b) only) and the kept list ((d) with reasons). Paste the restore point's full `manifest.md`
  and the verbatim output of every `git bundle verify` into the ledger: the reviewer cannot read
  the restore point itself, so it checks each cleanup-list item against that pasted manifest and
  bundle-verify output.
- INDEPENDENT REVIEW (always, even when no code changed; before any cleanup): run
  `review --kind reconciliation --required --context <ledger> --with-prs` plus `--location <path>`
  for every extra clone (and `--main-ref <branch>` if the default branch is not detected). The
  reconciliation review runs at effort high. If main's code changed, also run a separate
  `review --kind code --required`, adding `--high` when the integrated changes touch auth,
  sessions, permissions, payments, data or migrations, secrets, CI or deploy. Fix findings here
  (never in the reviewer), re-run affected builds/tests, then review the new candidate. Then run
  `gate --require reconciliation` (add `--require code` when main's code changed); it fails if a
  required review is missing, failed, unavailable, stale (main or any branch/worktree/stash/clone/PR
  changed since), or its receipt was altered.
- If a required review is `unavailable`, do not clean up and do not replace it with a self-review;
  report the blocker.

STEP 4 — CLEANUP (only after verify passes and `gate` exits 0):
- Remove only items on the ledger's cleanup list. Anything that refuses, or that changed since the
  gate, is kept and reported.
- `git worktree remove <path>` (never with `--force`), then `git worktree prune`.
- `git branch -d <branch>`; use `-D` only with (a) or (b) evidence in the ledger.
- Drop a stash only after re-finding it by SHA (`git stash list --format='%gd %H'`), and drop that
  exact entry.
- Delete a remote branch or close a PR only for the user's own items (`gh api user` compared with
  the branch/PR author). Never close foreign work.
- Delete an extra clone only when it is clean, stash-free, has no local-only commits and its bundle
  is verified in the restore point.

If planning or a required review is unavailable, change nothing further (integration stays) and do
not clean up; report the blocker.

ROUTING (shared with dependency-upgrade; one implementation): `R=~/.agents/skills/dependency-upgrade/scripts/routed_task.py`
- `start` (STEP 1) → `run_dir`. Then `python3 $R plan <run_dir> --context <handoff>` /
  `python3 $R review <run_dir> --kind <k> ...` / `python3 $R gate <run_dir>`. Run tasks one at a time
  as background commands (a task can take up to 30 min) and collect the JSON.
- Each task runs on exactly one model, in a fresh read-only session outside the repo: Claude Opus 5.5
  only, through Claude Code. Plans run at effort `xhigh`; reviews at `medium`, and at `high` for the
  reconciliation review, a high-tier review or when `--high` is given. There is no fallback: an Opus
  outage makes the task `unavailable` and blocks the run. `python3 $R probe` shows availability
  without model calls.
- `reused` means the same candidate was already reviewed/planned: don't repeat it. Never review your
  own work in this session to satisfy a required review. Do not pass session flags; they do not exist.
- Implementation, merging, conflict resolution, fixes and cleanup stay in this session. Evidence
  lives in the run dir; put the selected model, effort, verdicts and the gate result in the report.

Finish with a short report: what was integrated, what was kept (with reasons), what was deleted, the
restore-point path, and planning/review routing (model, effort, verdicts) and the gate result.
