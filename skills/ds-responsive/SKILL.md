---
name: ds-responsive
description: Platform-agnostic intrinsic responsiveness, adaptive layout, typography/scaling resilience, accessible interactions and verification across web, mobile, native, desktop and TV applications. Read for every UI task, including small fixes, audits, design-system work and new layouts; complements project design authority and Swiss structure without prescribing a brand or framework.
---

# Intrinsic & Adaptive Responsive UI (`ds-responsive`)

Related content stays in its preferred compact arrangement while it comfortably fits, then adapts
against actual allocated space, content, font metrics, state, and input capabilities — across web,
mobile, native, desktop, and TV surfaces. This is not a requirement to make everything fluid,
eliminate every breakpoint/size-class, add extra wrappers, or redesign a product.

For platform-specific primitives, scaling APIs, and verification targets (Web CSS/DOM, iOS/Android/
RN/Flutter, Desktop windowing/DPI, TV 10-foot/D-pad), read
[`references/platforms.md`](references/platforms.md).

## Discover and ground first

Inspect project instructions, target platform(s), layout/styling architecture, reusable components
and callers, fonts/media, supported OS/browser/device targets, existing tests, adaptive
compositions, accessibility, and performance budgets. Reconcile earlier findings against current
source and rendering before duplicating fixes.

Use current official platform/framework documentation and compatibility evidence. On web targets,
start client HTML/CSS/JS work with the installed modern-web guidance workflow (and the official
Svelte workflow when Svelte is used); primary web references include
[WCAG 2.2](https://www.w3.org/TR/WCAG22/), [MDN](https://developer.mozilla.org/), and
[Core Web Vitals](https://web.dev/articles/vitals). On mobile, desktop, or TV targets, consult the
target platform's official layout, accessibility, and HIG/TV guidelines. Retrieve only the relevant
passages, not whole documentation corpora.

Project-authoritative colors, type roles, tokens, APIs, media, motion, and ownership win over
skill examples. Swiss design remains the structural/art-direction baseline where required;
intrinsic behavior does not mandate its example font/palette, twelve tracks, device prefixes, or
nonbreaking value/unit pairs. Retain the mandatory `frontend-design` + `swiss-design` +
`apple-design` composition where required. Ground and critique a task-sized color/type/layout/
interaction plan; a behavior fix normally preserves the existing plan rather than inventing one.

## Layout decision tree

1. **State the invariant:** what must stay together, may wrap/reflow, must remain
   readable/operable, and depends on container space, window/screen size, safe area, or input
   capability.
2. **Keep normal/intrinsic flow** when it already works (document flow on web, native stack/column
   flow on mobile/desktop/TV).
3. **One-dimensional groups (Flex / Stack / Row-Column):** intentional wrapping, basis/growth/
   shrink, and logical gaps/minimums. Group related content; prevent automatic min-content
   constraints from squeezing controls. Place shrink boundaries (`min-inline-size: 0` on web,
   flexible/expanded constraints on native/Flutter/iced) at the actual shrink boundary, not
   everywhere. A value/unit pair may wrap if that is its accepted contract; no unconditional nowrap
   rule.
4. **Two-dimensional alignment (Grid):** use repeating/auto-fitting tracks where items share
   aligned geometry. Choose `auto-fit` vs `auto-fill` (or adaptive column-count rules on native)
   deliberately; use subgrid where supported and materially useful. Guard content-derived minimums
   against narrow containers (`min(100%, minimum)` on web; bounded min-width on native/desktop).
   Preserve authored editorial spans and occupancy instead of replacing them with an automatic
   grid.
5. **Container-driven adaptation:** when flow cannot express a genuine reusable composition
   transition, query an owned container/constraint (CSS container queries, `LayoutBuilder` /
   `GeometryReader` / `BoxWithConstraints` / responsive widget bounds) with a usable default
   baseline. Derive transitions from readable content/control needs and test their neighbors at
   different font scales.
6. **Viewport / window / screen queries:** reserve them for actual page/app-shell architecture,
   navigation/sidebar/rail transitions, screen-bound overlays, short heights, and safe-zone/
   overscan margins. Branch on actual input capabilities (hover/pointer/touch/D-pad/keyboard) and
   user preferences, never screen width as their proxy.
7. **Bounded fluid spacing/display type:** apply only where beneficial. Body/UI readability and
   target minimums may remain fixed or scale strictly with OS text preferences. Permit
   content-dependent block growth.
8. **Intentional 2D regions:** keep semantic tables, maps, charts, timelines, and code blocks
   locally scrollable, labeled, and keyboard/D-pad usable; do not turn semantic tables into
   inferior cards.
9. **Imperative measurement last:** measure layout in code only when declarative layout cannot
   express the actual need, or existing indicator/canvas/positioning behavior requires it. Batch
   reads/writes, bound observers/listeners, and dispose them cleanly. Do not build a generic
   responsive engine.

Fixed icons, logos, artwork, aspect ratios, target minimums, app-shell modes, and dialog maximums
can be legitimate. Inspect whether content has a safe escape/scroll path before changing a
constraint.

## Typography and scaling decision tree

Semantic role/readability → fixed vs bounded-fluid/OS-scaled role → selected font stack →
delivered formats/styles/Unicode coverage/axes → loaded/fallback metrics → optical sizing/
synthesis needs → measured loading/shift/payload costs → delivery optimization if justified.

- **Preserve user zoom and OS text scaling:** support 200%/400% zoom on web, Dynamic Type on iOS,
  `sp` scaling on Android, desktop font-scale settings, and viewing-distance legibility on TV.
  Pure viewport-width sizing or shrinking text to fit boxes is not enlarged-text acceptance.
- **Preserve semantic weight/style and optical sizing:** verify variable font axes and static
  fallback parity where used. Downloaded font files do not prove which face rendered a glyph.
- **Keep meaningful line-height, tracking, reading measures, and script coverage:** use text
  balancing/pretty wrapping selectively where supported, never globally. Do not shrink type to
  repair cramped containers.
- **Web font economics:** inspect `font-display`/FOIT/FOUT, WOFF2/static vs variable size,
  subsets, request count, cache, and duplicate preloads; measure font CLS rather than guessing
  from final screenshots. Keep text readable and operable during delayed/failed loading.

## Content, source order, and internationalization

Stress realistic long names/labels, URLs/emails/IDs/hashes, large values/currencies/dates, extra
actions/badges, validation, loading/error/empty, and asynchronous states. Use shrink boundaries,
intrinsic tracks, flexible height, and owned wrapping where appropriate. Essential text cannot
disappear behind clipping, clamping, or truncation; document intentional bounded summaries with
full-text access.

Keep reading/focus order meaningful (DOM order on web, accessibility traversal order on mobile/
desktop, directional focus order on TV). Audit visual reordering, absolute positioning, and
duplicated responsive trees; exceptional visual/source divergence needs explicit interaction and
accessibility evidence.

Use logical layout directions (start/end), locale/direction metadata (`lang`/`dir`, RTL layout
mirroring), bidi isolation, and appropriate directional icons. Include Arabic/Hebrew, mixed
RTL/LTR, CJK, long compounds, and locale dates/numbers/currencies as fixtures where relevant. Do
not invent supported product translations or reinterpret ambiguous numeric input silently.

## Media and asynchronous stability

Intrinsic dimensions/aspect and accessible alternative → appropriate adaptive sizing/cropping/art
direction → density/DPR-aware assets (`srcset`/`sizes`/`picture` on web, 1x/2x/3x or vector
assets on native/desktop/TV) → justified priority/lazy strategy → loading/error geometry and
labels/tooltips. Do not force every visual to full container width.

Reserve honest geometry for fonts, media, API data, skeletons, banners, and notifications where
feasible. Verify both initial and settled frames; ready assets do not prove styles, hydration, or
interactive initialization. Do not defer required controls merely to improve a resource metric.

## Floating UI, scroll, safe areas, and input

Reuse existing accessible positioning/portal/overlay primitives. Trace anchor, viewport/window
bounds, stacking/z-order, flipping/shifting, collision padding, and available width/height
**through to the actual user-scrollable descendant**. Keep close controls, selected/last items,
filters, and required actions reachable at screen edges, short heights, overscan margins, and
enlarged text. Preserve focus trapping/return, keyboard/typeahead/D-pad navigation, and
non-drag alternatives.

Choose necessary scroll owners, constrain meaningful local overflow, and verify keyboard/wheel/
touch/D-pad scrolling, scroll chaining, restoration, and anchor offsets. Sticky/fixed surfaces
must not obscure focused content; use owned clearance/scroll-padding/scroll-margin. Preserve
scroll-lock lifecycle. Root clipping (`overflow: hidden/clip`) is never proof of responsive
correctness.

Handle platform viewport geometry intentionally: `dvh`/`svh`/`lvh` and safe-area insets on web;
notches/bars/IME keyboards on mobile; window chrome and split panes on desktop; TV overscan safe
zones and Back-key dismissal on 10-foot UIs. Match native input types/keyboards/autocomplete to
actual field meaning. Emulators are not physical-device proof; label emulated vs physical evidence
honestly.

## Interaction, preferences, and motion

WCAG 2.2 AA is the minimum baseline; retain stronger project or platform rules (including 44x44px
coarse-pointer targets on web, 44x44pt iOS / 48x48dp Android targets, and high-visibility TV
focus indicators). Pointer, touch, keyboard, D-pad, and hybrid support are independent of screen
width. Hover is optional enrichment. Provide single-pointer/keyboard/D-pad alternatives for
nonessential dragging.

Preserve useful immediate feedback, interruptibility, spatial consistency, and existing motion
language. Do not animate ordinary wrapping or introduce arbitrary timers, layout-heavy resize
loops, `transition: all`, or unnecessary animation dependencies. Support reduced motion, forced/
high contrast, and transparency preferences with robust baselines.

## Testing, performance, and completion

Extend existing tests/stories/showrooms and conformance architecture, not a second pipeline.
Static pattern matches (nowrap, fixed dimensions, breakpoints, reorder, root clipping, pure-vw
type, drag-only, `transition-all`) are owner/reason review signals, not automatic bans.

- Sample critical viewport/window/screen **and independent container** dimensions densely,
  including awkward transition neighbors, supported wide ranges, and short/landscape aspect
  ratios. Refine actual failing intervals.
- Test relevant focus, active, open, expanded, selected, disabled, loading, submitting, error,
  empty, populated, long-content, and badge/action states — not only resting screens.
- Verify text scaling and reflow for the target platform (web: 320px reflow, 200% text
  enlargement, 400% zoom, WCAG spacing; mobile: Dynamic Type / large font scale + compact/split
  sizes; desktop: min/max window + DPI scaling; TV: 1080p/4K safe-zone + D-pad focus traversal).
- Cover font states, locales/RTL, capabilities, and accessibility preferences. Keep physical
  device and assistive-tech checks distinct from automation.
- Inspect descendant and ancestor clipping, local scroll geometry, overlap, focused hit
  visibility, last-item reachability, close/focus return, and sticky focus clearance.
- Bind performance checks to real platform standards (web: production-build LCP/INP/CLS and
  approved RUM where available; mobile/desktop/TV: frame pacing/jank, startup/transition latency,
  and GPU/memory budgets). Missing data is `UNAVAILABLE`, never zero.

A scoped UI fix is done only after causal regression checks, required native checks, and actual
responsive, accessibility, visual, and performance evidence on the final candidate. Record
commands/results, intentional exceptions, unavailable dimensions, and unresolved findings
honestly.
