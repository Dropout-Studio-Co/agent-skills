---
name: ds-responsive
description: Platform-agnostic intrinsic responsiveness, adaptive layout, typography/scaling resilience, and accessible interactions for web, mobile, native, desktop and TV UI. Read for every UI task: fixes, audits, design systems, layouts.
---

# Intrinsic & Adaptive Responsive UI (`ds-responsive`)

Related content keeps its preferred compact arrangement while it fits, then adapts against actual allocated space, content, font
metrics, state and input capabilities across web, mobile, native, desktop and TV. This mandates neither fluid everything,
deleted breakpoints, extra wrappers nor redesign. Platform primitives — layout, scaling, fonts, media/DPR, safe areas, targets,
verification — live in [`references/platforms.md`](references/platforms.md).

## Discover and ground first

- Inspect instructions, platforms, layout/styling architecture, components and callers, fonts/media, supported targets, tests,
  adaptive compositions, accessibility and performance budgets; reconcile findings against current source and rendering first.
- Ground in current official documentation and compatibility evidence: installed modern-web guidance for client HTML/CSS/JS
  (official Svelte workflow when used); each mobile/desktop/TV platform's official layout, accessibility and HIG/TV guidelines;
  relevant passages only.
- Project-authoritative colors, type roles, tokens, APIs, media, motion and ownership win over skill examples. Where required,
  keep Swiss design as the structural baseline and the mandatory `frontend-design` + `swiss-design` + `apple-design`
  composition, without importing its example font/palette, twelve tracks, device prefixes or nonbreaking value/unit pairs.
  Ground and critique a task-sized color/type/layout/interaction plan; a behavior fix preserves it.

## Layout decision tree

1. **State the invariant:** what must stay together, may wrap/reflow, must stay readable/operable, and depends on container
   space, window/screen size, safe area or input capability.
2. **Keep normal/intrinsic flow** when it works (web document flow; native stack/column flow).
3. **One-dimensional groups (Flex / Stack / Row-Column):** intentional wrapping, basis/growth/shrink, logical gaps/minimums;
   stop min-content constraints squeezing controls. Put a shrink boundary at the actual shrink boundary, not everywhere. A
   value/unit pair may wrap if accepted; no unconditional nowrap rule.
4. **Two-dimensional alignment (Grid):** repeating/auto-fitting tracks where items share aligned geometry; choose auto-fit vs
   auto-fill (adaptive column counts on native) deliberately and reuse parent tracks where supported. Guard content-derived minimums
   against narrow containers; keep authored editorial spans instead of an automatic grid.
5. **Container-driven adaptation:** when flow cannot express a reusable composition transition, query an owned
   container/constraint with a usable default baseline; derive transitions from readable content/control needs and test
   neighbors at different font scales.
6. **Viewport/window/screen queries:** reserve for app-shell architecture, navigation/sidebar/rail transitions, screen-bound
   overlays, short heights and safe-zone/overscan margins. Branch on actual input capabilities
   (hover/pointer/touch/D-pad/keyboard) and preferences, never screen width.
7. **Bounded fluid spacing/display type:** only where beneficial; body/UI readability and target minimums stay fixed or scale
   strictly with OS text preferences, and blocks may grow with content.
8. **Intentional 2D regions:** semantic tables, maps, charts, timelines and code blocks stay locally scrollable, labeled,
   keyboard/D-pad usable; never downgrade tables into inferior cards.
9. **Imperative measurement last:** measure in code only when declarative layout cannot express the need or
   indicator/canvas/positioning requires it; batch reads/writes, bound observers, dispose cleanly, never build a generic
   responsive engine.

Fixed icons, logos, artwork, aspect ratios, target minimums, app-shell modes and dialog maximums can be legitimate; check for a
safe escape/scroll path before changing a constraint.

## Typography and scaling decision tree

Semantic role/readability → fixed vs bounded-fluid/OS-scaled role → font stack → formats/styles/Unicode coverage/axes →
loaded/fallback metrics → optical sizing → measured loading/shift/payload → optimization if justified.

- **User zoom and OS text scaling:** browser zoom and text enlargement, OS text-size preferences, desktop font-scale settings,
  TV viewing-distance legibility. Pure viewport-width sizing or shrinking text to fit boxes is not enlarged-text acceptance.
- **Weight/style, optical sizing, metrics:** verify variable axes and static fallback parity; downloaded files do not prove
  which face rendered a glyph; use text balancing/pretty wrapping selectively, never globally; keep meaningful line-height,
  tracking and reading measures; never shrink type to repair cramped containers.
- **Font economics:** inspect load/block/swap behavior, compressed or variable formats, subsets, request count, cache, duplicate
  preloads; measure font CLS rather than guessing from screenshots. Text stays readable and operable during delayed/failed
  loading.

## Content, source order, and internationalization

- Stress long names/labels, URLs/emails/IDs/hashes, large values/currencies/dates, extra actions/badges, validation,
  loading/error/empty and async states with shrink boundaries, intrinsic tracks, flexible height and owned wrapping. Essential
  text cannot vanish behind clipping, clamping or truncation; document intentional bounded summaries with full-text access.
- Keep reading/focus order meaningful (DOM order on web, accessibility traversal on mobile/desktop, directional focus on TV);
  audit visual reordering, absolute positioning and duplicated responsive trees. Divergent visual/source order needs interaction
  and accessibility evidence.
- Use logical start/end directions, locale/direction metadata, RTL mirroring, bidi isolation and directional icons. Cover
  Arabic/Hebrew, mixed RTL/LTR, CJK, long compounds and locale dates/numbers/currencies as fixtures; never invent supported
  translations or silently reinterpret ambiguous input.

## Media and asynchronous stability

- Intrinsic dimensions/aspect and accessible alternative → adaptive sizing/cropping/art direction → density/DPR-aware assets →
  justified priority/lazy strategy → loading/error geometry and labels; do not force every visual to full container width.
- Reserve honest geometry for fonts, media, API data, skeletons and banners; verify initial and settled frames, since ready
  assets prove neither styles, hydration nor interactive initialization. Never defer required controls to improve a resource
  metric.

## Floating UI, scroll, safe areas, and input

- Reuse existing accessible positioning/portal/overlay primitives, tracing anchor, viewport/window bounds, stacking/z-order,
  flipping/shifting, collision padding and available width/height **through to the actual user-scrollable descendant**. Keep
  close controls, selected/last items, filters and required actions reachable at screen edges, short heights, overscan margins
  and enlarged text; preserve focus trapping/return, keyboard/typeahead/D-pad navigation and non-drag alternatives.
- Choose necessary scroll owners, constrain meaningful local overflow, and verify keyboard/wheel/touch/D-pad scrolling,
  chaining, restoration and anchor offsets. Sticky/fixed surfaces must not obscure focused content; use owned clearance and
  preserve scroll-lock lifecycle. Root clipping never proves responsive correctness.
- Handle platform viewport geometry intentionally: dynamic viewport units and safe-area insets on web; notches/bars/IME
  keyboards on mobile; window chrome and split panes on desktop; TV overscan zones and Back-key dismissal on 10-foot UIs. Match
  native input types/keyboards/autocomplete to field meaning. Emulators are not physical-device proof; label emulated vs
  physical evidence honestly.

## Interaction, preferences, and motion

- WCAG 2.2 AA is the minimum baseline; keep stronger project or platform rules, including coarse-pointer, platform-minimum and
  high-visibility TV focus targets (exact sizes in the reference). Pointer, touch, keyboard, D-pad and hybrid support are
  independent of screen width; hover is optional enrichment; dragging gets single-pointer/keyboard/D-pad alternatives.
- Preserve immediate feedback, interruptibility, spatial consistency and existing motion language. Do not animate ordinary
  wrapping or add arbitrary timers, layout-heavy resize loops, blanket `transition: all` or unnecessary animation dependencies.
  Support reduced motion, forced/high contrast and transparency preferences with robust baselines.

## Testing, performance, and completion

Extend existing tests/stories/showrooms and conformance architecture, not a second pipeline. Static pattern matches (nowrap,
fixed dimensions, breakpoints, reorder, root clipping, pure-vw type, drag-only, `transition-all`) are owner/reason review
signals, not automatic bans.

- Sample critical viewport/window/screen **and independent container** dimensions densely, including awkward transition
  neighbors, wide ranges and short/landscape ratios; refine real failing intervals.
- Test focus, active, open, expanded, selected, disabled, loading, submitting, error, empty, populated, long-content and
  badge/action states — not only resting screens.
- Verify text scaling and reflow per the reference's platform matrices (narrow reflow widths, text enlargement/zoom levels,
  minimum/large window sizes, DPI or safe-zone scaling, D-pad traversal).
- Cover font states, locales/RTL, capabilities and accessibility preferences; keep physical-device and assistive-tech checks
  distinct from automation. Inspect ancestor/descendant clipping, local scroll geometry, overlap, focused hit visibility,
  last-item reachability, close/focus return and sticky focus clearance.
- Bind performance checks to real standards (web: production-build LCP/INP/CLS and approved RUM; mobile/desktop/TV: frame
  pacing/jank, startup latency, GPU/memory budgets). Missing data is `UNAVAILABLE`, never zero.

A scoped UI fix is done only after causal regression checks, required native checks, and actual responsive, accessibility,
visual and performance evidence on the final candidate. Record commands and results, intentional exceptions, unavailable
dimensions and unresolved findings honestly.
