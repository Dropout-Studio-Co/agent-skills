---
name: ds-ui-overhaul
description: Repository-wide UI, UX, interaction, accessibility, responsiveness, motion, design-system and visual-quality audit plus implementation workflow across web, mobile, native, desktop and TV applications.
---

# UI/UX Overhaul (`ds-ui-overhaul`)

Use this skill when the user asks for a UI, UX, frontend, responsive, accessibility, motion, design-system
or visual-quality overhaul on any visual product — web, mobile, native, desktop or TV. `Run ds-ui-overhaul.`
means audit and implement validated improvements, then verify them; stop at an audit only when the user
explicitly asks for audit-only. This is a router, not a replacement for the specialist skills: read only
what the current platform, surface and phase need, and reconcile their advice with the repository.

## Authority order

Resolve conflicts in this order: explicit user instruction > repository `AGENTS.md`/`CLAUDE.md` or
equivalent > accepted product requirements > canonical design-system and component contracts > repository
`DESIGN.md` > existing intentional product identity and patterns > this skill > the machine-required UI
skills (`ds-responsive`, `frontend-design`, `swiss-design`, `apple-design`) > other installed specialists >
generic design conventions.

External skills must never override project architecture, brand, design system, accepted direction or
safety constraints. Never make a product look like Apple merely because `apple-design` is active.

## Platform adaptation

Detect the target platform(s) while establishing repository truth — **Web**, **Mobile** (iOS, Android,
React Native, Flutter), **Desktop** (macOS, Windows, Linux, Electron, Tauri, Rust/iced/wgpu, Qt/GTK) or
**TV / 10-foot** (Samsung Tizen / Lightning / Blits, tvOS, Android TV, WebOS) — and read
[`references/platforms.md`](references/platforms.md) for audit-specific motion, rendering-budget and
capture rules plus `~/.agents/skills/ds-responsive/references/platforms.md` for canonical layout, scaling,
safe-area, input and accessibility primitives. Skip checks that belong only to another platform (CSS/DOM
or Lighthouse on a native TV or desktop app) and apply the target platform's real equivalents.

## Baseline constraints

Unless a newer repository authority says otherwise:

- No decorative visible borders, outlines or rings for ordinary UI separation; use shade, contrast,
  spacing, hierarchy, material and depth.
- Keep a clearly visible accessible focus state (keyboard focus on web/desktop, spatial/D-pad focus on TV,
  assistive focus on mobile).
- No hover-scale effects on pointer buttons; on TV/10-foot UIs follow the product's intentional
  focus-elevation convention.
- Preserve the canonical primary/CTA treatment.
- Prefer canonical design-system components and established icon/motion primitives over local clones.
- Respect reduced-motion preferences (`prefers-reduced-motion` on web, OS Reduce Motion / Animator
  Duration Scale on native, mobile, desktop and TV) and avoid gratuitous animation.
- Check nested parent/child surface contrast, overflow/clipping, focus visibility and target sizes.

## Required and specialist skills

Read `ds-responsive`, `frontend-design`, `swiss-design` and `apple-design` when installed — mandatory where
machine policy requires them, never optional lenses. Read each installed skill directly from
`~/.agents/skills/<name>/SKILL.md` by path, so specialists with `disable-model-invocation: true` (such as
`review-animations`) or skills omitted from a truncated index (such as `modern-web-guidance`) still load. If
a specialist is not installed, continue with the installed core skills and native verification.

Read other installed specialists only when they match the repository's platform, stack and current phase:

- Cross-platform design and motion: `animate`, `animation-vocabulary`, `improve-animations`,
  `find-animation-opportunities`, `review-animations`, `prototype`.
- Web: `modern-web-guidance`, `fixing-metadata`, `chrome-devtools-axi` (and `cloudflare:web-perf` when
  installed); `shadcn-svelte` and Svelte plugin skills (`~/.agents/svelte-workflow.md`) only where the
  repository uses Svelte; `gsap-*` only where it uses GSAP.
- Native / Desktop / TV: `rust-iced-mpv-desktop` for Rust/iced/wgpu desktop apps; `lightning-blits-tizen`,
  `samsung-avplay`, `tizen-screenshot` for Samsung Tizen / Lightning / Blits TV apps; native
  simulator/emulator tools (`device_*` / `agent-device`) for iOS and Android.

Never invent or install a specialist. If the one you need is absent, continue with the required skills and
native verification.

## Phase 1 — Discover & Audit

1. **Repository truth, Trail first.** Use `trail ask`, `trail grep`, `trail callers` and `trail skeleton` to
   orient and to find callers and blast radius before editing; never install or upgrade Trail or Graft and
   use them read-only when present. Also inspect repository root, `git status`, branch, instruction files,
   target platform(s), framework/toolkit, architecture, design system, component primitives,
   styling/theming, animation infrastructure, tests, rendered-verification tooling and representative
   screens/routes/components. Preserve unrelated user work.
2. **Rendered product.** Inspect the running product on its real target surface where tooling permits
   (browser, simulator/emulator, desktop window, TV emulator/device); source-only judgments are
   insufficient for visual work.
3. **Focused passes**, each reading only the specialist it needs:
   - *Design craft* (`frontend-design`, `swiss-design`, `apple-design`): layout, hierarchy, spacing,
     typography, visual consistency, components, states, interaction feedback, navigation, forms/inputs,
     information architecture — translated into the project's existing design language and ergonomics.
   - *Adaptive/responsive* (`ds-responsive` plus its `references/platforms.md`; `modern-web-guidance` on
     web): adaptation across the target platform's real dimensions and input modes.
   - *Accessibility* (`ds-responsive`, `swiss-design`): platform semantics and assistive access, focus and
     traversal order, dialogs, forms/errors, contrast, reduced motion, target sizes. Automated checks never
     replace manual interaction evidence.
   - *Resilience* (`frontend-design`; `modern-web-guidance` on web): loading, empty, error, success,
     offline/network failure, extreme content, long labels, large datasets, permissions, repeated
     submissions, unusual Unicode, currencies/dates, localization/RTL, zoom and OS text scaling.
   - *Component and design-system reuse* (the repository's component specialist, or native/desktop/TV
     toolkit conventions, plus `frontend-design`/`swiss-design`): prefer existing primitives and fix
     systemic root causes; avoid hand-rolled duplicates, duplicate components and new UI frameworks.
   - *Existing motion* (`improve-animations`, `apple-design`): treat `improve-animations` as read-only when
     it declares an audit contract; it produces a plan and never edits source.
   - *Motion opportunities* (`find-animation-opportunities`, `animation-vocabulary`, `animate`): add motion
     only for feedback, continuity, orientation, state understanding or perceived responsiveness; reject
     noise, delay, distraction, frame drops and maintenance cost.
4. **Prototype** (`prototype`) only when materially different viable solutions cannot be resolved from
   repository truth; never prototype obvious fixes.

## Phase 2 — Plan (Fresh-Context, Read-Only)

Before modifying files, for meaningful work (more than a trivial local fix), write the handoff — accepted
requirements, target platform(s), scope, authority order and baseline constraints, repository
instructions, design system and component inventory, Phase 1 findings with `file:line`, verification
tooling — then run ONE fresh-context `plan` task with `review_task.py` (runner below). Add a single
`--kind architecture --subject <change>` task only for significant or high-risk changes (shared
design-system primitive, layout/navigation/focus shell, checkout/auth UI, animation/rendering pipeline,
cross-repository contract).

The planner is read-only and advisory: check every decision against the authority order and this skill,
adopt or reject each with a reason, and implement it yourself. A plan never authorizes destructive
operations, policy changes or unrequested redesign; replan only when scope or findings change materially.
Create or update `DESIGN.md` only after the plan and only when it adds durable project value — existing
tokens, patterns and identity win. If planning is `unavailable`, do not edit: report the blocker and stop.

## Phase 3 — Implement & Polish

- Implement the selected fixes inside the existing architecture, root causes first where safe. Read
  `animate` for motion implementation and the narrowest relevant specialist for other changes; preserve
  intentional product behavior and unrelated work; no unrequested redesign.
- Run ONE combined motion and rendering-performance review after motion changes or when existing motion is
  material: read `review-animations` once (plus `modern-web-guidance` on web) and check web layout
  thrashing, unnecessary measurements, expensive filters/blur, poor scroll animation, excessive JS
  animation, avoidable rerenders, `will-change` misuse and avoidable main-thread work; on mobile/desktop/TV
  check dropped frames/jank against the target refresh rate (60/120Hz), UI-thread blocking,
  overdraw/shadows/blur, texture/GPU memory bloat (especially constrained TVs) and avoidable rebuilds. Fix
  material findings and preserve reduced-motion behavior.
- Final polish (web: `fixing-metadata` and `modern-web-guidance` when useful): spacing inconsistency,
  typography, wrapping, alignment, visual noise, adaptive/responsive discontinuities, overflow/clipping,
  stacking/z-order and inconsistent states. Stop before unrequested redesign.

## Phase 4 — Verify & Independent Review

- **Rendered verification.** Inspect representative screen/window sizes or target devices plus important
  states and flows on the real target surface, following
  [`references/platforms.md`](references/platforms.md) and
  `~/.agents/skills/ds-responsive/references/platforms.md`; those matrices are canonical, so do not
  re-derive per-platform checklists here. Check overflow, clipping, wrapping, spacing, contrast,
  sticky/fixed/overlay collisions, focus, input behavior, animation and layout shift.
- **Rendered-evidence manifest.** Record screenshots, viewports/devices/window sizes, states,
  keyboard/D-pad/assistive and reduced-motion checks, plus the Lighthouse 13 reports below.
- **Repository verification.** Run the repository's applicable formatting, linting, static analysis, type
  checks (TypeScript, Swift, Kotlin, Dart, Rust, C#, etc.), unit/component/widget tests, integration/E2E
  tests and production/release build or packaging. Fix regressions caused by the work; never weaken
  verification to obtain green results.
- **Lighthouse 13 before merge (`horcrux.app`, `dropoutstudio.co`, `beyourahi.com`).** For UI changes to
  these sites, run Lighthouse 13 on the production build of the affected pages before merge at mobile and
  desktop for all four categories (performance, accessibility, best-practices, SEO), take the median of
  three serial runs per page and viewport, and compare each against the repository's thresholds; a missing
  threshold is a gap to report, not a waiver. Record report path, median category scores and URL/viewport
  per page in the rendered-evidence manifest. A missing Lighthouse 13 result is an Important finding and
  blocks delivery.
- **Independent review.** Review the final changes against the run base recorded by `start`, each category
  as its own fresh-context task with `--required`, depth by risk: Low (copy, token or local style fix, no
  interaction change) `code`; Normal `code` + `ui-ux`; High (broad overhaul, shared design system,
  navigation/layout/focus shell, forms/checkout/auth UI, motion/rendering system) `code` + `ui-ux` +
  `accessibility`. Pass `--context` with requirements, target platform(s), accepted decisions and checks
  run; for `ui-ux` and `accessibility` pass `--rendered-evidence <manifest>` or, when rendering was
  impossible, `--no-rendered-evidence "<why>"` — never claim visual verification that did not happen. Fix
  findings in this session, rerun the affected checks and rendered verification, then review the new
  candidate (`reused` results for an unchanged candidate are not repeated). Finish only when
  `gate --require code` (plus `--require ui-ux` / `--require accessibility` for the tiers above) exits 0;
  a required review that cannot run is recorded `unavailable`, reported unverified, and blocks delivery.

## Fresh-context task runner

Shared with `ds-deps-upgrade` (one implementation).
`T=~/.agents/skills/ds-deps-upgrade/scripts/review_task.py`:

- Before the first edit: `python3 $T start --skill ds-ui-overhaul --repo .` → `run_dir` (records HEAD as the
  review base).
- Prepare: `python3 $T plan <run_dir> --context <handoff> [--kind architecture --subject S]` and
  `python3 $T review <run_dir> --kind code|ui-ux|accessibility --required ...`; run each printed `prompt.md`
  in a fresh, read-only context.
- Bind the answer with `python3 $T record <run_dir> --task-id <id> --output <file> --by
  "<fresh-context-id>"`, or mark it unrunnable with `python3 $T unavailable <run_dir> --task-id <id>
  --reason "<why>"`.
- Run tasks one at a time and verify with `python3 $T gate <run_dir>` before completion. Never self-review
  in the authoring context in place of an unavailable required review. Report the runner, verdicts and gate
  result.

## Model and harness neutrality

Planning, review and parallel workers use the current session's harness, model and effort level without
switching, selecting or enforcing alternatives; implementation, debugging, fixes and verification stay in
this session. Only when `ds-dev-protocol` is explicitly invoked alongside this skill do its model-routing,
execution and delivery rules take precedence.

## Context discipline

Do not load every specialist at once. Load sequentially by phase, platform and concrete need; a full run
may use many specialists over time without putting them all in one context. A responsive web sheet might
read `ds-responsive`, `modern-web-guidance` and `apple-design`; a Tizen TV focus pass `ds-responsive`,
`lightning-blits-tizen` and `apple-design`; a Rust desktop pass `ds-responsive` and `rust-iced-mpv-desktop`.

## Parallel work

Parallelize only when the overhaul is large and ownership is non-overlapping: marketing/public surfaces,
app/workspace flows, responsive/adaptive layout, accessibility, motion, platform-specific shells, and the
shared design system. Assign one owner per shared file/component and route cross-cutting findings to that
owner. Every delegated prompt states exact scope, constraints, verification, preservation of unrelated
work, unchanged session model/harness/effort configuration, and the repository delivery policy. Use
repository-owned risk/blast-radius validation and the Phase 4 reviews.

## Related repositories

Identify dependencies and the canonical shared design-system owner first. Fix generic issues at the shared
source when appropriate, verify the shared contract, then update consumers; never let downstream
repositories invent conflicting primitives.

## Git and safety

Preserve unrelated branches, worktrees, uncommitted changes and user-owned files. Deliver per the
repository's delivery mode and instructions (commit, PR, required checks and merge when green and
authorized); when `ds-dev-protocol` is explicitly invoked alongside this skill, follow its delivery and gate
rules. Never force-push and never touch unowned or foreign work. Preserve all independent safety
boundaries.
