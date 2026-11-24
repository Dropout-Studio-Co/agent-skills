---
name: ds-ui-overhaul
description: Overhaul UI/UX across web, mobile, desktop, or TV: audits layout, accessibility, responsiveness, motion, and design-system reuse, then implements and verifies fixes (or stops at audit-only when asked).
---

# UI/UX Overhaul (`ds-ui-overhaul`)

Use this skill for any UI, UX, frontend, responsive, accessibility, motion, design-system, or visual-quality
overhaul across web, mobile, native, desktop, or TV. `Run ds-ui-overhaul.` means audit, implement validated
improvements, and verify; stop at an audit only when the user explicitly asks for audit-only. This skill is
a router over installed specialists: load only what the current platform, surface, and phase need, and
reconcile their advice with the repository.

## Authority order

Resolve conflicts in this order: explicit user instruction > repository `AGENTS.md`/`CLAUDE.md` or
equivalent > accepted product requirements > canonical design-system and component contracts > repository
`DESIGN.md` > existing intentional product identity and patterns > this skill > the machine-required UI
skills (`ds-responsive`, `frontend-design`, `swiss-design`, `apple-design`) > other installed specialists >
generic design conventions.

External skills never override project architecture, brand, design system, accepted direction, or safety
constraints; never make a product look like Apple merely because `apple-design` is active.

## Platform adaptation

Detect the target platform(s) while establishing repository truth — **Web**, **Mobile** (iOS, Android,
React Native, Flutter), **Desktop** (macOS, Windows, Linux, Electron, Tauri, Rust/iced/wgpu, Qt/GTK), or
**TV / 10-foot** (Samsung Tizen / Lightning / Blits, tvOS, Android TV, WebOS) — and read
[`references/platforms.md`](references/platforms.md) for audit-specific motion, rendering-budget, and
capture rules plus `~/.agents/skills/ds-responsive/references/platforms.md` for canonical layout, scaling,
safe-area, input, and accessibility primitives. Apply the target platform's real equivalents and skip checks
that belong only to another platform (such as CSS/DOM or Lighthouse on a native TV or desktop app).

## Baseline constraints

Unless a newer repository authority says otherwise:

- Separate ordinary UI surfaces with shade, contrast, spacing, hierarchy, material, and depth rather than
  decorative visible borders, outlines, or rings.
- Maintain a clearly visible accessible focus state (keyboard focus on web/desktop, spatial/D-pad focus on
  TV, assistive focus on mobile).
- Keep pointer button hover states steady without hover-scale effects; on TV/10-foot UIs follow the
  product's intentional focus-elevation convention.
- Preserve the canonical primary/CTA treatment.
- Reuse canonical design-system components and established icon/motion primitives instead of local clones.
- Honor reduced-motion preferences (`prefers-reduced-motion` on web, OS Reduce Motion / Animator Duration
  Scale on native, mobile, desktop, and TV) and omit gratuitous animation.
- Verify nested parent/child surface contrast, overflow/clipping, focus visibility, and target sizes.

## Required and specialist skills

Read `ds-responsive`, `frontend-design`, `swiss-design`, and `apple-design` on every run — mandatory by
machine policy, never optional lenses. Read each installed skill directly from
`~/.agents/skills/<name>/SKILL.md` by path so specialists with `disable-model-invocation: true` (such as
`review-animations`) or skills omitted from a truncated index (such as `modern-web-guidance`) still load. If
any required skill is absent on this machine, disclose the gap and continue with the installed core skills
and native verification.

Load optional specialists progressively by phase, platform, and concrete need rather than all at once
(sequentially in the lead, or isolated inside Phase 1 read-only audit subagents on large overhauls):

- Cross-platform design and motion: `animate`, `animation-vocabulary`, `improve-animations`,
  `find-animation-opportunities`, `review-animations`, `prototype`.
- Web: `modern-web-guidance`, `fixing-metadata`, `chrome-devtools-axi` (and `cloudflare:web-perf` when
  installed); `shadcn-svelte` and Svelte workflow (`~/.agents/svelte-workflow.md`) only where the repository
  uses Svelte; `gsap-*` only where it uses GSAP.
- Native / Desktop / TV: `rust-iced-mpv-desktop` for Rust/iced/wgpu desktop apps; `lightning-blits-tizen`,
  `samsung-avplay`, `tizen-screenshot` for Samsung Tizen / Lightning / Blits TV apps; native
  simulator/emulator tools (`device_*` / `agent-device`) for iOS and Android.

For example, a responsive web sheet reads `ds-responsive`, `modern-web-guidance`, and `apple-design`; a
Tizen TV focus pass reads `ds-responsive`, `lightning-blits-tizen`, and `apple-design`; a Rust desktop pass
reads `ds-responsive` and `rust-iced-mpv-desktop`. Never invent or install a specialist; if one is absent,
continue with installed skills and native verification.

## Phase 1 — Discover & Audit

1. **Repository truth, Trail first.** Use `trail ask`, `trail grep`, `trail callers`, and `trail skeleton`
   read-only when present to orient and map callers and blast radius before editing (never install or
   upgrade Trail or Graft). Inspect repository root, `git status`, branch, instruction files, target
   platform(s), framework/toolkit, architecture, design system, component primitives, styling/theming,
   animation infrastructure, tests, rendered-verification tooling, and representative
   screens/routes/components. Preserve unrelated user work.
2. **Rendered product.** Inspect the running product on its real target surface where tooling permits
   (browser, simulator/emulator, desktop window, TV emulator/device); source-only judgments are
   insufficient for visual work.
3. **Focused passes**, each reading only the specialist it needs:
   - *Design craft* (`frontend-design`, `swiss-design`, `apple-design`): layout, hierarchy, spacing,
     typography, visual consistency, components, states, interaction feedback, navigation, forms/inputs,
     information architecture — translated into the project's existing design language and ergonomics.
   - *Adaptive/responsive* (`ds-responsive` + `references/platforms.md`; `modern-web-guidance` on web):
     adaptation across the target platform's real dimensions and input modes.
   - *Accessibility* (`ds-responsive`, `swiss-design`): platform semantics and assistive access, focus and
     traversal order, dialogs, forms/errors, contrast, reduced motion, target sizes. Automated checks never
     replace manual interaction evidence.
   - *Resilience* (`frontend-design`; `modern-web-guidance` on web): loading, empty, error, success,
     offline/network failure, extreme content, long labels, large datasets, permissions, repeated
     submissions, unusual Unicode, currencies/dates, localization/RTL, zoom, and OS text scaling.
   - *Component and design-system reuse* (the repository's component specialist or native/desktop/TV toolkit
     conventions, plus `frontend-design`/`swiss-design`): prefer existing primitives and fix systemic root
     causes; avoid hand-rolled duplicates and new UI frameworks.
   - *Existing motion* (`improve-animations`, `apple-design`): treat `improve-animations` as read-only when
     it declares an audit contract; it produces a plan and never edits source.
   - *Motion opportunities* (`find-animation-opportunities`, `animation-vocabulary`, `animate`): add motion
     only for feedback, continuity, orientation, state understanding, or perceived responsiveness; reject
     noise, delay, distraction, frame drops, and maintenance cost.
4. **Prototype** (`prototype`) only when materially different viable solutions cannot be resolved from
   repository truth; skip prototyping for obvious fixes.
5. **Large multi-surface overhauls** may fan static, read-only specialist passes (design-system reuse,
   `improve-animations`, static accessibility/resilience scan) out to parallel read-only subagents; skip
   this on small or scoped overhauls. Pass each subagent the repository-truth and authority-order summary,
   and keep them strictly source-only (the lead keeps sole ownership of browsers, simulators, emulators,
   and TV devices).

**Done when:** repository truth and target platform(s) are established, a rendered baseline is captured (or
inability to render is documented), and `file:line` findings are collected across every applicable pass.

**Audit-only exit:** if the user asked for audit-only, deliver a structured report with source and rendered
evidence plus recommended fixes, then stop before Phase 2.

## Phase 2 — Plan (Fresh-Context, Read-Only)

Before modifying files, for meaningful work (more than a trivial local fix):

1. Run `review_task.py start` (runner below) to record the pre-edit base commit.
2. Write the handoff: accepted requirements, target platform(s), scope, authority order and baseline
   constraints, repository instructions, design-system and component inventory, Phase 1 `file:line` findings,
   and verification tooling.
3. If significant or high-risk changes exist (shared design-system primitive, layout/navigation/focus shell,
   checkout/auth UI, animation/rendering pipeline, cross-repository contract), run concurrent
   `--kind architecture --subject <change>` tasks FIRST.
4. Run ONE serial `plan` task incorporating any `architecture` outputs; replan only if scope or findings
   change materially.

Check every advisory decision against the authority order and this skill, and adopt or reject each with a
reason. A plan never authorizes destructive operations, policy changes, or unrequested redesign. Create or
update `DESIGN.md` only after the plan and only when it adds durable project value — existing tokens,
patterns, and identity win. If planning is `unavailable`, do not edit: report the blocker and stop.

**Done when:** `start` recorded the base before the first edit, `plan` completed (incorporating any
`architecture` decisions), and every decision is adopted or rejected against the authority order.

## Phase 3 — Implement & Polish

- Implement the selected fixes inside the existing architecture, root causes first where safe. Read
  `animate` for motion implementation and the narrowest relevant specialist for other changes; preserve
  intentional product behavior and unrelated work with no unrequested redesign.
- **Rendering-performance and motion review (always run).** Always check platform rendering hazards — on
  web: layout thrashing, unnecessary measurements, expensive filters/blur, poor scroll animation, excessive
  JS animation, avoidable rerenders, `will-change` misuse, and avoidable main-thread work (`modern-web-guidance`);
  on mobile/desktop/TV: dropped frames/jank against the target refresh rate (60/120Hz), UI-thread blocking,
  overdraw/shadows/blur, texture/GPU memory bloat (especially constrained TVs), and avoidable rebuilds. When
  motion changed or existing motion is material, read `review-animations` once as part of this pass. Fix
  material findings and preserve reduced-motion behavior.
- **Final polish** (web: `fixing-metadata` and `modern-web-guidance` when useful): fix spacing
  inconsistency, typography, wrapping, alignment, visual noise, adaptive/responsive discontinuities,
  overflow/clipping, stacking/z-order, and inconsistent states. Stop before unrequested redesign.

**Done when:** selected fixes are implemented in-architecture, rendering-performance checks (and
`review-animations` when applicable) are resolved, and final polish is complete without unrequested redesign.

## Phase 4 — Verify & Independent Review

- **Rendered verification.** Inspect representative screen/window sizes or target devices plus important
  states and flows on the real target surface, following
  [`references/platforms.md`](references/platforms.md) and
  `~/.agents/skills/ds-responsive/references/platforms.md` (those matrices are canonical; do not re-derive
  them here). Check overflow, clipping, wrapping, spacing, contrast, sticky/fixed/overlay collisions, focus,
  input behavior, animation, and layout shift.
- **Rendered-evidence manifest.** Record screenshots/recordings, viewports/devices/window sizes, states, and
  keyboard/D-pad/assistive and reduced-motion checks. Per `review_task.py`, screenshot/recording entries
  MUST be **absolute or `~`-prefixed paths** with media extensions (`.png`, `.jpg`, `.jpeg`, `.webp`,
  `.gif`, `.avif`, `.mp4`, `.webm`, `.mov`, `.pdf`) so `review_task.py` copies them; write Lighthouse
  scores, console/network errors, and runtime logs **inline** in the manifest text (non-media files are not
  copied).
- **Lighthouse 13 site gate (`horcrux.app`, `dropoutstudio.co`, `beyourahi.com`).** For UI changes to these
  sites, run the production-build Lighthouse 13 gate in
  [`references/platforms.md#lighthouse-13-site-gate`](references/platforms.md#lighthouse-13-site-gate) and
  record scores inline in the manifest; a failing or missing gate is an Important finding and blocks delivery.
- **Repository verification.** Run the repository's applicable formatting, linting, static analysis, type
  checks (TypeScript, Swift, Kotlin, Dart, Rust, C#, etc.), unit/component/widget tests, integration/E2E
  tests, and production/release build or packaging. Fix regressions caused by the work; never weaken
  verification to obtain green results.
- **Independent review.** Review the final changes against the run base recorded by `start`, each category
  as its own fresh-context task with `--required`, depth by risk: Low (copy, token, or local style fix, no
  interaction change) `code`; Normal `code` + `ui-ux`; High (broad overhaul, shared design system,
  navigation/layout/focus shell, forms/checkout/auth UI, motion/rendering system) `code` + `ui-ux` +
  `accessibility`. Pass `--context` with requirements, target platform(s), accepted decisions, and checks
  run; for `ui-ux` and `accessibility` pass `--rendered-evidence <manifest>` or, when rendering was
  impossible, `--no-rendered-evidence "<why>"` — never claim visual verification that did not happen. Fix
  findings in this session, rerun affected checks and rendered verification, then review the new candidate
  (`reused` results for an unchanged candidate are not repeated). Finish only when `gate` exits 0 for the
  tier's required kinds; a required review that cannot run is recorded `unavailable`, reported unverified,
  and blocks delivery.

## Fresh-context task runner

Shared with `ds-deps-upgrade` (one implementation):
`T=~/.agents/skills/ds-deps-upgrade/scripts/review_task.py`

- **Start once before the first edit** (including any shared-DS/shell foundation commit; never re-run `start`
  after integrating workers):
  `python3 "$T" start --skill ds-ui-overhaul --repo .` → `run_dir` (records `HEAD` as the review base).
- **Plan:**
  `python3 "$T" plan <run_dir> --context <handoff> [--kind architecture --subject S]`
- **Review:**
  `python3 "$T" review <run_dir> --kind code|ui-ux|accessibility --required [--context <file>] [--rendered-evidence <manifest> | --no-rendered-evidence "<why>"]`
  Run each printed `prompt.md` in a fresh, read-only context.
- **Record or mark unavailable:**
  `python3 "$T" record <run_dir> --task-id <id> --output <file> --by "<fresh-context-id>"`
  `python3 "$T" unavailable <run_dir> --task-id <id> --reason "<why>"`
- **Gate:**
  `python3 "$T" gate <run_dir> --require code [--require ui-ux] [--require accessibility]` (matching the
  risk tier).

Distinct review kinds (`code`, `ui-ux`, `accessibility`) on the same frozen candidate and frozen
rendered-evidence manifest may run in parallel fresh-context subagents (never duplicate the same
`(kind, subject)` and never form a voting committee; keep the tree and rendered evidence frozen until every
result is recorded). Never self-review in the authoring context in place of an unavailable required review.
Report the runner, verdicts, and gate result.

## Model and harness neutrality

Planning, review, and parallel workers use the current session's harness, model, and effort level without
switching, selecting, or enforcing alternatives. Planners and reviewers are strictly read-only and advisory;
shared design-system/token/shell implementation, integration, review-finding fixes, rendering-performance
and motion review, final polish, and all rendered verification stay in the lead session, while disjoint
vertical surfaces on large overhauls may use isolated mutating workers under
[`references/parallel-work.md`](references/parallel-work.md). Only when `ds-dev-protocol` is
explicitly invoked alongside this skill do its model-routing, execution, and delivery rules take precedence.

## Parallel work

Default to serial. Parallelize only disjoint vertical surfaces after shared design-system/shell primitives
land, following [`references/parallel-work.md`](references/parallel-work.md).

## Related repositories

Identify dependencies and the canonical shared design-system owner first. Fix generic issues at the shared
source when appropriate, verify the shared contract, then update consumers; keep downstream repositories
aligned without inventing conflicting primitives.

## Git and safety

Preserve unrelated branches, worktrees, uncommitted changes, and user-owned files. Deliver per the
repository's delivery mode and instructions (commit, PR, required checks, and merge when green and
authorized). Never force-push, never touch unowned or foreign work, and preserve all independent safety
boundaries.
