---
name: frontend-ui-ux-overhaul
description: Comprehensive repository-wide frontend, UI, UX, interaction, accessibility, responsiveness, motion, design-system, and visual-quality audit plus implementation workflow.
---

# Frontend UI/UX overhaul

Use this skill when the user asks for a frontend, UI, UX, responsive, accessibility, motion,
design-system, or visual-quality overhaul. A normal invocation such as
`Run frontend-ui-ux-overhaul.` means audit and implement validated improvements, then verify them.
Do not stop at an audit unless the user explicitly requests audit-only.

This is a router, not a replacement for the specialist skills. Read only the specialists needed for
the current surface and phase. Their advice is advisory and must be reconciled with the repository.

## Authority order

Resolve conflicts in this order:

1. Current explicit user instruction.
2. Repository `AGENTS.md`, `CLAUDE.md`, or equivalent.
3. Current accepted product requirements.
4. Canonical shared design-system and component contracts.
5. Repository `DESIGN.md` or equivalent.
6. Existing intentional product identity and patterns.
7. This skill.
8. The four machine-required UI skills (`frontend-design`, `swiss-design`, `apple-design`,
   `intrinsic-responsive-ui`).
9. The other installed specialists named here.
10. Generic design conventions.

External skills must never blindly override the project architecture, brand, design system,
accepted direction, or safety constraints. Never make a product look like Apple merely because
`apple-design` is active.

## Baseline constraints

Unless a newer repository authority says otherwise:

- Do not add decorative visible borders, outlines, or rings for ordinary UI separation; use shade,
  contrast, spacing, hierarchy, material, and depth.
- Preserve a clearly visible accessible keyboard focus state.
- Do not use hover-scale effects on buttons.
- Preserve the canonical primary/CTA treatment.
- Prefer canonical design-system components and established animated-icon systems over local clones.
- Respect `prefers-reduced-motion` and avoid gratuitous animation.
- Check nested parent/child surface contrast, overflow, focus visibility, and target sizes.

## Required and specialist skills

Read `frontend-design`, `swiss-design`, `apple-design` and `intrinsic-responsive-ui` on every run:
they are required by machine policy, not optional lenses.

Read each installed skill directly from `~/.agents/skills/<name>/SKILL.md` by path so specialists
with `disable-model-invocation: true` (such as `review-animations`) or skills omitted from a
truncated skill index (such as `modern-web-guidance`) still load reliably.

Read the other installed specialists by phase and concrete need:

- Design and implementation: `animate`, `animation-vocabulary`, `improve-animations`,
  `find-animation-opportunities`, `review-animations`, `prototype`, `modern-web-guidance`,
  `fixing-metadata`.
- Performance and delivery: `chrome-devtools-axi` (and `cloudflare:web-perf` when installed).
- Component work: `shadcn-svelte` only where the repository already uses it; the `gsap-*` skills
  only where the repository already uses GSAP.
- Svelte work: the Svelte plugin skills, following `~/.agents/svelte-workflow.md`.

Never invent a specialist or install one. Use what is installed; if the one you need is absent,
continue with the required skills and native verification.

## Runtime workflow

### 1. Establish repository truth

Trail first: use `trail ask`, `trail grep`, `trail callers` and `trail skeleton` to orient in the
repository and to find callers and blast radius before editing. Never install or upgrade Trail or
Graft; use them read-only when present. Also inspect the repository root, `git status`, branch,
instruction files, framework, architecture, design system, component primitives, styling, animation
infrastructure, tests, browser tooling, and representative routes/components. Preserve unrelated
user work.

### 2. Understand the rendered product

Inspect the running/rendered product where tooling permits; source-only judgments are insufficient
for visual work. Create or update `DESIGN.md` only when it adds durable project value, and only
after the step 10a plan. Existing project tokens, patterns, and product identity win.

### 3. Broad design review

Read `frontend-design`, `swiss-design` and `apple-design` as the initial design-craft lenses. Review
layout, hierarchy, spacing, typography, visual consistency, components, states, interaction
feedback, navigation, forms, and information architecture. Translate the findings into the
project's existing design language.

### 4. Mobile and responsive review

Read `intrinsic-responsive-ui` and use `modern-web-guidance` for viewport and layout primitives.
Check touch targets, safe areas, viewport behavior, mobile navigation, keyboard/input behavior,
drawers/sheets, overflow, responsive layout, and pointer-versus-touch behavior.

### 5. Accessibility review

Read `intrinsic-responsive-ui` and `swiss-design` for the accessibility pass. Verify rendered
semantic HTML, keyboard access, focus and focus order, accessible names, dialogs, forms and errors,
contrast, reduced motion, target sizes, and screen-reader semantics. Automated checks do not replace
manual interaction evidence.

### 6. Resilience

Use `modern-web-guidance` and `frontend-design` when useful. Check loading, empty, error, success,
extreme content, long labels, large datasets, network failure, permissions, repeated submissions,
unusual Unicode, currencies/dates, localization, zoom, and text scaling.

### 7. Component and design-system review

Read `shadcn-svelte` only where the repository uses it, plus `frontend-design` and `swiss-design`,
when component choices or primitives are involved. Prefer the existing design system and component
primitives; fix systemic/root causes. Avoid unnecessary hand-rolled primitives, duplicate
components, and new UI frameworks.

### 8. Existing animation audit

Read `improve-animations` and `apple-design`. Treat `improve-animations` as read-only when it
declares an audit contract: it produces a plan; it does not edit source.

### 9. Motion opportunities

Read `find-animation-opportunities`, `animation-vocabulary` and `animate`. Add motion only when it
improves feedback, continuity, orientation, state understanding, or perceived responsiveness. Reject
motion that adds noise, delay, distraction, or maintenance cost.

### 10. Prototype only when ambiguity is real

Read `prototype` only when there are materially different viable solutions whose choice cannot be
resolved from repository truth. Do not prototype obvious fixes.

### 10a. Architecture and implementation plan (fresh-context, read-only)

Before modifying files, when there is meaningful work (more than a trivial, local fix), write a
handoff (accepted requirements, scope, authority order and baseline constraints, repository
instructions, design system and component inventory, findings from steps 1-10 with file:line,
verification tooling) and run ONE fresh-context `plan` task (see Fresh-context planning and
review). Add one `--kind architecture --subject <change>` task only for significant or high-risk
changes (shared design-system primitive, layout/navigation shell, checkout/auth UI, animation
system, cross-repository contract). The planner is read-only and advisory: check every decision
against the authority order and this skill, adopt or reject each with a reason, and implement it
yourself. A plan never authorizes destructive operations, policy changes or an unrequested
redesign. Replan only when scope or findings change materially. If planning is `unavailable`, do
not edit: report the blocker and stop.

### 11. Implement validated improvements

Implement the selected fixes in the existing architecture. Read `animate` for motion implementation
and the narrowest relevant specialist for other changes. Fix root causes when safe, preserve
intentional product behavior, and do not turn the pass into an unrequested redesign.

### 12. Motion performance

Read `review-animations` and `modern-web-guidance`. Check layout thrashing, unnecessary
measurements, expensive filters/blur, poor scroll animation, excessive JavaScript animation,
avoidable rerenders, misuse of `will-change`, and avoidable main-thread work.

### 13. Animation review

Read `review-animations` after motion changes or when existing motion is material. Fix material
findings and preserve reduced-motion behavior.

### 14. Final polish

Read `fixing-metadata` and `modern-web-guidance` when useful. Look for spacing inconsistency,
typography, wrapping, alignment, visual noise, responsive discontinuities, overflow/clipping,
stacking, and inconsistent states. Stop before unrequested redesign.

### 15. Rendered verification

Inspect representative desktop, tablet/laptop where useful, and mobile views plus important states
and flows through `chrome-devtools-axi`: use AXI Chrome, never the personal Chrome. Check overflow,
clipping, wrapping, spacing, contrast, sticky/fixed collisions, focus, touch, keyboard behavior,
animation, and layout shift.

### 16. Repository verification

Run the repository's actual applicable formatting, linting, static analysis, TypeScript checks,
unit/component tests, integration/E2E tests, and production build. Fix regressions caused by the
work. Never weaken verification to obtain green results.

### 16a. Lighthouse 13 before merge (horcrux.app, dropoutstudio.co, beyourahi.com)

For UI changes to `horcrux.app`, `dropoutstudio.co` or `beyourahi.com`, run Lighthouse 13 on the
production build of the affected pages before merge, at both mobile and desktop, for all four
categories: performance, accessibility, best-practices and SEO. Take the median of three serial runs
per page and viewport, and compare each with the repository's thresholds; a missing threshold is a
gap to report, not a waiver. Record the report path, the median category scores and the URL/viewport
for each page in the rendered-evidence manifest used by step 17. A missing Lighthouse 13 result is an
Important finding and blocks delivery.

### 17. Independent review (fresh-context, before completion or delivery)

Review the actual final changes against the run base (the commit recorded by `start` before any
edit), each category as its own fresh-context task with `--required`, depth by risk:

- Low (copy, token or local style fix, no interaction change): `code`.
- Normal: `code` + `ui-ux`.
- High (broad overhaul, shared design system, navigation/layout shell, forms/checkout/auth UI,
  motion system): `code` + `ui-ux` + `accessibility`.

Pass `--context` (requirements, accepted decisions, checks run with results) and, for `ui-ux` and
`accessibility`, `--rendered-evidence <manifest>` listing the real screenshots, viewports, states,
keyboard and reduced-motion checks from step 15, plus the Lighthouse 13 reports and scores for the
three sites above when they changed. If rendering was impossible, pass
`--no-rendered-evidence "<why>"` instead; never claim visual verification that did not happen. Fix
findings in this session, rerun the affected checks and rendered verification, then review the new
candidate (`reused` results for an unchanged candidate are not repeated). Finish only when
`gate --require code` (plus `--require ui-ux` / `--require accessibility` for the tiers above) exits
0; if a required review cannot run, record `unavailable`, report it unverified and do not deliver.

## Context discipline

Do not load every specialist at once. Load specialists sequentially by phase and concrete need; a
full run may use many specialists over time without putting them all in one context. A responsive
sheet might read `intrinsic-responsive-ui`, `modern-web-guidance` and `apple-design`. A
motion-performance pass might read `review-animations`, `animate` and `improve-animations`. A Svelte
page in a shadcn-based repository might add `shadcn-svelte` and the Svelte plugin skills.

## Parallel work

Parallelize only when the overhaul is large and ownership is non-overlapping. Valid partitions
include marketing, dashboard/app, mobile/responsive, accessibility, motion, and the shared design
system. Assign one owner per shared file/component; send cross-cutting findings to the appropriate
owner. Every delegated prompt must state exact scope, constraints, verification, preservation of
unrelated work, unchanged session model/harness/effort configuration, and the repository's
delivery policy. Use repository-owned risk/blast-radius-based validation and the independent
reviews of step 17; No-Mistakes is permanently retired. Parallel workers and fresh-context
planning/review tasks use the current session's harness, model and effort level without switching,
selecting or enforcing alternatives; only when `execution-protocol` is explicitly invoked alongside
this skill do its model-routing and execution rules take precedence for the applicable tasks.

## Fresh-context planning and review

Shared with `dependency-upgrade` (one implementation).
`T=~/.agents/skills/dependency-upgrade/scripts/review_task.py`:

- Before the first edit: `python3 $T start --skill frontend-ui-ux-overhaul --repo .` → `run_dir`
  (records HEAD as the review base); then prepare tasks with
  `python3 $T plan <run_dir> --context <handoff> [--kind architecture --subject S]` and
  `python3 $T review <run_dir> --kind code|ui-ux|accessibility --required ...`, run each printed
  `prompt.md` in a fresh, read-only context using this session's current harness, model and effort
  (or per `execution-protocol` when explicitly invoked alongside this skill), bind the answer with
  `python3 $T record <run_dir> --task-id <id> --output <file> --by "<fresh-context-id>"` (or mark
  unrunnable with `python3 $T unavailable <run_dir> --task-id <id> --reason "<why>"`), and verify
  before completion with `python3 $T gate <run_dir>`.
- Run tasks one at a time. Never switch models, harnesses or effort on your own, and never
  self-review in the authoring context in place of an unavailable required review.
- Implementation, debugging, fixes and verification stay with this session's model, effort and
  harness. Report the fresh-context runner, verdicts and the gate result.

## Related repositories

When working across related repositories, identify dependencies and the canonical shared
design-system owner first. Fix generic issues at the shared source when appropriate, verify the
shared contract, then update consumers. Do not let downstream repositories invent conflicting
primitives.

## Git and safety

Preserve unrelated branches, worktrees, uncommitted changes, and user-owned files. Deliver per the
repository's delivery mode and instructions (commit, PR, required checks and merge when green and
authorized); when `execution-protocol` is explicitly invoked alongside this skill, follow its
delivery and gate rules. Never force-push. Never touch unowned or foreign work. Do not switch or
override the session's model, harness or effort level. No-Mistakes is permanently retired. Preserve
all independent safety boundaries.
