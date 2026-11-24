---
name: ds-responsive
description: Intrinsic responsive UI across web, mobile, desktop, TV: layout/reflow, scaling, overlays/safe areas, input/a11y, verification. Read for every UI task: fixes, audits, design systems.
---

# Intrinsic & Adaptive Responsive UI (`ds-responsive`)

Keep compact arrangements, breakpoints, fixed sizes, and existing layouts wherever they fit; adapt what breaks against actual
allocated space, content, font metrics, state, and input capabilities across web, mobile, native, desktop, and TV.

Read the target platform's section in [`references/platforms.md`](references/platforms.md) before choosing platform primitives,
target minimums, performance signals, or verification matrices.

## Discover and ground first

- Inspect instructions, target platforms, layout/styling architecture, components and callers, fonts/media, supported targets,
  tests, adaptive compositions, accessibility, and performance budgets; reconcile findings against current source and rendered
  output first.
- Ground in primary specs and official docs (WCAG 2.2, MDN, Core Web Vitals, and each mobile/desktop/TV platform's official
  layout, accessibility, and HIG/TV guidelines) plus installed `modern-web-guidance` for client HTML/CSS/JS and
  `svelte-code-writer` when Svelte is used; consult relevant passages only.
- Project-authoritative colors, type roles, tokens, APIs, media, motion, and ownership take precedence over skill examples.
  Where required, keep `swiss-design` as the structural baseline alongside `frontend-design` and `apple-design`, adopting
  `swiss-design`'s grid and typographic discipline without importing `swiss-design`'s example font/palette, twelve-track grid,
  device prefixes, or nonbreaking value/unit pairs. Ground and critique a task-sized color/type/layout/interaction plan; a
  behavior fix preserves the existing design.

## Layout decision tree

1. **State the invariant:** what must stay together, may wrap/reflow, must stay readable/operable, and depends on container
   space, window/screen size, safe area, or input capability.
2. **Keep normal/intrinsic flow** when it works (web document flow; native stack/column flow).
3. **One-dimensional groups (Flex / Stack / Row-Column):** use intentional wrapping, basis/growth/shrink, and logical
   gaps/minimums so min-content constraints do not squeeze controls. Place a shrink boundary at the actual shrink boundary, not
   everywhere. Allow a value/unit pair to wrap when accepted rather than enforcing an unconditional nowrap rule.
4. **Two-dimensional alignment (Grid):** use repeating/auto-fitting tracks where items share aligned geometry; choose auto-fit
   vs auto-fill (adaptive column counts on native) deliberately and reuse parent tracks where supported. Guard content-derived
   minimums against narrow containers; keep authored editorial spans instead of replacing them with an automatic grid.
5. **Container-driven adaptation:** when flow cannot express a reusable composition transition, query an owned ancestor
   container/constraint with a usable default baseline (an element cannot container-query itself); derive transitions from
   readable content/control needs and test neighbors at different font scales.
6. **Viewport/window/screen queries:** reserve for app-shell architecture, navigation/sidebar/rail transitions, screen-bound
   overlays, short heights, and safe-zone/overscan margins. Branch on actual input capabilities
   (hover/pointer/touch/D-pad/keyboard) and user preferences rather than screen width.
7. **Bounded fluid spacing/display type:** apply only where beneficial; keep body/UI readability and target minimums fixed or
   scaled strictly with OS text preferences, and let blocks grow with content.
8. **Intentional 2D regions:** keep semantic tables, maps, charts, timelines, and code blocks locally scrollable, labeled, and
   keyboard/D-pad usable rather than downgrading tables into inferior cards.
9. **Imperative measurement last:** measure in code only when declarative layout cannot express the need or
   indicator/canvas/positioning requires it; batch reads/writes, bound observers, dispose cleanly, and keep measurement local
   rather than building a generic responsive engine.

Keep fixed icons, logos, artwork, aspect ratios, target minimums, app-shell modes, and dialog maximums where they are
legitimate; verify a safe escape/scroll path before changing any constraint.

## Typography and scaling decision tree

Semantic role/readability → fixed vs bounded-fluid/OS-scaled role → font stack → formats/styles/Unicode coverage/axes →
loaded/fallback metrics → optical sizing → measured loading/shift/payload → optimization if justified.

- **User zoom and OS text scaling:** verify browser zoom, text enlargement, OS text-size preferences, desktop font-scale
  settings, and TV viewing-distance legibility. Scale body and UI text with user preferences rather than pure viewport-width
  sizing or shrinking text to fit boxes. Test both computed enlargement and native OS/browser text settings; relative units or
  `clamp()` alone prove neither.
- **Weight/style, optical sizing, metrics:** verify variable axes and static fallback parity, and confirm which face actually
  rendered each glyph rather than inferring from downloaded files. Apply text balancing/pretty wrapping selectively to headings
  or short copy, preserve meaningful line-height, tracking, and reading measures, and resolve cramped containers through layout
  rather than shrinking type. Measure before adding metric overrides or restricting font synthesis, and test semantic
  bold/italic on real fallbacks; avoid automatic self-hosting, preloading every face, requesting all axes, or reordering a
  system-first stack.
- **Font economics:** inspect load/block/swap behavior, compressed or variable formats, subsets, request count, cache, and
  deduplicated preloads; measure font CLS directly rather than guessing from screenshots. Keep text readable and operable during
  delayed or failed loading.

## Content, source order, and internationalization

- Stress long names/labels, URLs/emails/IDs/hashes, large values/currencies/dates, extra actions/badges, validation,
  loading/error/empty, and async states with shrink boundaries, intrinsic tracks, flexible height, and owned wrapping. Keep
  essential text visible without clipping, clamping, or truncation; document intentional bounded summaries with full-text
  access.
- Keep reading and focus order meaningful (DOM order on web, accessibility traversal on mobile/desktop, directional focus on
  TV); audit visual reordering, absolute positioning, and duplicated responsive trees. Back any divergent visual/source order
  with interaction and accessibility evidence.
- Use logical start/end directions, locale/direction metadata, RTL mirroring, bidi isolation, and directional icons. Cover
  Arabic/Hebrew, mixed RTL/LTR, CJK, long compounds, and locale dates/numbers/currencies as fixtures; preserve explicit locale
  support rather than inventing translations or silently reinterpreting ambiguous input.

## Media and asynchronous stability

- Size each visual to its intrinsic aspect and role: intrinsic dimensions/aspect and accessible alternative → adaptive
  sizing/cropping/art direction → density/DPR-aware assets → justified priority/lazy strategy → loading/error geometry and
  labels.
- Reserve honest geometry for fonts, media, API data, skeletons, and banners; verify initial and settled frames, since ready
  assets prove neither styles, hydration, nor interactive initialization. Keep required controls immediately available rather
  than deferring them to improve a resource metric.

## Floating UI, scroll, safe areas, and input

- Reuse existing accessible positioning/portal/overlay primitives, tracing anchor, viewport/window bounds, stacking/z-order,
  flipping/shifting, collision padding, and available width/height **through to the actual user-scrollable descendant** (an
  available-size variable on an outer wrapper does not prove wheel/touch access). Keep close controls, selected/last items,
  filters, and required actions reachable at screen edges, short heights, overscan margins, and enlarged text; preserve focus
  trapping/return, keyboard/typeahead/D-pad navigation, and non-drag alternatives.
- Choose necessary scroll owners, constrain meaningful local overflow, and verify keyboard/wheel/touch/D-pad scrolling,
  chaining, restoration, and anchor offsets. Prevent scrollbar appearance/disappearance from causing layout shift (CLS) and
  preserve intentional scroll-snapping behavior. Keep sticky/fixed surfaces clear of focused content with owned clearance,
  preserve scroll-lock lifecycle, and fix overflow at its source rather than masking it with root clipping.
- Handle platform viewport geometry, system bars, safe areas, soft keyboards/IME, and overscan margins using the target
  platform's native primitives in [`references/platforms.md`](references/platforms.md), and match native input semantics (types,
  keyboards, autocomplete) to field meaning.

## Interaction, preferences, and motion

- Meet WCAG 2.2 AA as the minimum baseline and honor stronger project or platform rules, including coarse-pointer,
  platform-minimum, and high-visibility TV focus targets (exact minimums and focus cues in
  [`references/platforms.md`](references/platforms.md)). Support pointer, touch, keyboard, D-pad, and hybrid input independently
  of screen width; treat hover as optional enrichment and provide single-pointer, keyboard, and D-pad alternatives for dragging.
- Preserve immediate feedback, interruptibility, spatial consistency, and the project's existing motion language. Animate
  explicit, compositor-friendly properties only when motion aids comprehension, keeping ordinary wrapping instant and avoiding
  arbitrary timers, layout-heavy resize loops, blanket `transition: all`, or unnecessary animation dependencies. Support reduced
  motion, forced/high contrast, and transparency preferences on top of usable baselines; progressively supported preferences are
  enhancements, never prerequisites for usability.

## Testing and performance

Extend existing tests, stories, showrooms, and conformance architecture rather than creating a second pipeline. Treat static
pattern matches (nowrap, fixed dimensions, breakpoints, reorder, root clipping, pure-vw type, drag-only, `transition: all`) as
owner/reason review signals, not automatic bans.

- Sample critical viewport/window/screen **and independent container** dimensions densely, including awkward transition
  neighbors, wide ranges, and short/landscape ratios, and refine real failing intervals; sampled widths never prove every pixel
  combination.
- Exercise interactive states — focus, active, open, expanded, selected, disabled, loading, submitting, error, empty, populated,
  long-content, and badge/action states — not only resting screens.
- Verify text scaling, reflow, and input traversal against the target platform matrix in
  [`references/platforms.md`](references/platforms.md); a 320px viewport alone is not 400% zoom proof.
- Verify real interaction, scroll geometry, ancestor/descendant clipping, overlap, focus reachability, selected-tab visibility,
  last-item reachability, close/focus return, sticky focus clearance, and native/SSR forms — bounding boxes and axe alone are
  insufficient.
- Cover font states, locales/RTL, input capabilities, and accessibility preferences; keep physical-device and
  assistive-technology checks distinct from emulation and automation.
- Bind performance checks to the target platform's signals in [`references/platforms.md`](references/platforms.md).
  Lab/loopback proxies do not certify field INP or full-session CLS; never game checks by adding invasive telemetry, loosening
  budgets, or removing features.

## Done when

- Causal regression checks and required project/native checks pass on the final candidate.
- Responsive, accessibility, visual, and platform performance checks are verified on the final candidate.
- Original failure captures and immutable evidence are preserved (baselines are never overwritten and manifests are never
  regenerated to hide regressions).
- Every check result is labeled honestly as `physical`, `emulated`, or `automated`, with exact commands and outcomes recorded.
- Missing dimensions or unrun checks are reported as `UNAVAILABLE` (never `0` or pass), and every intentional exception or
  unresolved finding is explicitly documented.
