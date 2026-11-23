# Parallel work, isolation and integration

Default: **serial**, one agent. Parallelize only when the harness has subagents, the
machine has headroom, the user's policy allows it, and the pieces are truly independent.
Follow the user's global concurrency limits (they win over this file). Typical safe split:

| Work | Parallel? | Notes |
| --- | --- | --- |
| Changelog/migration-guide research per package family | yes, read-only | each worker returns cited findings, no edits |
| Fixture or test design | optional, high-risk migrations only | separate scratch dirs |
| Code migrations in disjoint packages/directories | yes, carefully | each in its own worktree + branch |
| Lockfile / manifest version changes | **no** | single integration owner |
| Installs, builds, test suites | limited | respect machine load; separate ports/caches |

## Always serial
Lockfile/manifest version bumps, locked installs and codegen/build in the integration worktree,
`run start`/`finish`/`report`, per-batch integration commits, lead-only `cherry-pick`/`merge`,
`rollback`, and stateful or heavy end-to-end checks never run concurrently.

## Rules for mutating workers
1. The lead creates the run and the integration worktree (`run worktree`) and commits the
   lockfile/manifest bump on the integration branch first; the integration worktree must be clean
   before any worker starts. Each worker then gets its own owned worktree with
   `depup.py run worker <run_ref> --domain <name>` (branch `depup/<run-id>-<domain>`, path
   `<run_dir>/workers/<domain>`), which defaults `--base` to the integration branch's current
   `HEAD` (and refuses a dirty integration worktree unless `--base` is passed explicitly). The
   journal records each worker with its base, so `status` and `rollback` cover it. Never create
   worker worktrees by hand.
2. Each brief names: objective, absolute worktree path, owned files/directories, files
   it must not touch (always: lockfiles and root manifests), base commit, checks to run,
   unchanged session model/harness/effort, deliverable (commits on its branch + summary), and
   "no push/merge".
3. Workers never run installs that rewrite the lockfile. They install frozen from the bumped
   lockfile already committed on the integration branch and inherited via the worker's base.
4. Separate ports, temp dirs and caches per worker (`PORT`, `TMPDIR`, tool cache env vars).
5. Only the lead integrates: one cherry-pick/merge at a time into the integration branch,
   resolving conflicts semantically, re-running the quick gate after each.
6. Cap concurrently active mutating workers at **2–3** (or fewer when the user's global policy sets
   a tighter limit) to avoid install/build/test CPU and RAM contention.

## Integration and consolidation
- Deterministic consolidation: list every worker branch, `git log <worker-base>..<branch>` using
  the worker's recorded base printed by `run worker` (not the pre-upgrade `worktree_base`),
  integrate in dependency order, verify each, record the result per branch.
- Do **not** route integration through a general "consolidate everything into main" skill
  that deletes branches/worktrees or pushes to the default branch; it conflicts with this
  skill's no-delete/no-push rules.
- Worker worktrees are removed only when their commits are integrated and they are clean
  (`git worktree remove` without `--force`); otherwise keep and report them.

## Review
Review the integrated candidate only, using the fresh-context task workflow
([fresh-context-tasks.md](fresh-context-tasks.md), including its
[model rule](fresh-context-tasks.md#model-harness-and-ds-dev-protocol-rule)): one fresh read-only
context per review task on the current session's configuration. Distinct `(kind, subject)` review
tasks may run in parallel on the same frozen candidate, but never a parallel committee or a
duplicate review of the same `(kind, subject)`; keep the tree frozen until every parallel review is
recorded. Fix findings on the integration branch and re-verify. If a required review is
`unavailable`, do not merge.
