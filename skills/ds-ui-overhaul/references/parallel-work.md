# Parallel Work & Isolation Contract (`ds-ui-overhaul`)

Default to serial execution. Parallelize mutating implementation only when the overhaul is large and
ownership is non-overlapping — disjoint vertical surfaces (separate routes/pages, apps, or platform shells)
— and only after shared design-system primitives, tokens, and layout/navigation shells land serially and are
committed. Never split horizontal concerns (`responsive`, `accessibility`, `motion`) across parallel workers
on the same components, and never parallelize shared design-system work.

## Worker isolation contract

- Commit the shared design-system/shell foundation first; preserve unrelated user dirty work.
- Give each mutating worker one temporary linked worktree outside the repository, created from the
  post-shared-DS commit; cap active mutating workers at **2–3** (or a tighter global limit).
- Include in every worker brief:
  - exact vertical scope and owned file/directory list;
  - forbidden files (shared design system, tokens, shells, manifests);
  - base commit;
  - verification commands using separate ports and caches (no AXI Chrome, simulator, emulator, or TV capture
    in workers);
  - unchanged session harness, model, and effort level;
  - "no push/merge".
- Keep `review_task.py start` at the original pre-edit base recorded before the first edit (including the
  shared-DS/shell foundation commit); never re-run `start` after integrating workers.
- Integrate worker branches serially in the lead session (one cherry-pick or merge at a time, then verify),
  remove clean integrated worker worktrees without `--force` (keeping dirty or unintegrated ones), then run
  the serial Phase 3 combined motion/rendering-performance review, final polish, and Phase 4 rendered
  verification.

## Serial-only boundaries

Keep all of the following serial in the lead session:

- Shared design-system, token, and layout/navigation shell edits
- Cross-repository shared design-system sync
- Phase 2 `plan`
- Phase 3 combined motion/rendering-performance review and final polish
- Lead integration and review-finding fixes
- All rendered capture and verification (AXI Chrome, simulators/emulators, TV devices, and Lighthouse 13's
  three serial runs per page and viewport)
