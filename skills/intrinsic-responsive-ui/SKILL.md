---
name: intrinsic-responsive-ui
description: Project-agnostic intrinsic responsiveness, typography/font resilience, accessible interactions and responsive verification. Read for every frontend/UI task, including small fixes, audits, design-system work and new layouts; complements project design authority and Swiss structure without prescribing a brand or framework.
---

# Intrinsic Responsive UI

Related content stays in its preferred compact arrangement while it comfortably fits, then reflows against actual allocated space, content, font metrics, state and input capabilities. This is not a requirement to make everything fluid, eliminate every breakpoint, add container wrappers or redesign a product.

## Discover and ground first

Inspect project instructions, design/CSS architecture, reusable components and callers, fonts/media, supported browsers, existing tests, responsive compositions, accessibility and performance budgets. Reconcile earlier findings against current source and rendering before duplicating fixes.

Use current official framework/library documentation and browser compatibility evidence. Start client HTML/CSS/JS work with the installed modern-web guidance workflow. Svelte decisions use the official documentation/catalog/autofixer workflow when applicable; this skill is not a second framework manual. Primary references include [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [MDN](https://developer.mozilla.org/), and [Core Web Vitals](https://web.dev/articles/vitals); retrieve the relevant current passages, not whole documentation corpora.

Project-authoritative colors, type roles, tokens, APIs, media, motion and ownership win over skill examples. Swiss design remains the structural/art-direction baseline where required; intrinsic behavior does not mandate its example font/palette, twelve tracks, device prefixes or nonbreaking value/unit pairs. Retain the mandatory frontend-design + swiss-design + apple-design composition where required. Ground and critique a task-sized color/type/layout/interaction plan; a behavior fix normally preserves the existing plan rather than inventing one.

## Layout decision tree

1. State the invariant: what must stay together, may wrap, must remain readable/operable, and depends on container, viewport or capability.
2. Keep semantic normal flow when it already works.
3. Use Flexbox for one-dimensional groups: intentional wrapping, basis/growth/shrink and logical gaps/minimums. Group related content; prevent automatic min-content constraints from squeezing controls. Use min-inline-size:0 at the actual shrink boundary, not everywhere. A value/unit pair may wrap if that is its accepted contract; no unconditional nowrap rule.
4. Use Grid for repeated/two-dimensional alignment. Choose auto-fit versus auto-fill deliberately; use subgrid where supported and materially useful. A content-derived minimum can need min(100%, minimum) to permit a smaller single column. Preserve authored editorial spans and occupancy instead of replacing them with an automatic grid.
5. If flow cannot express a genuine reusable composition transition, query an owned container with a usable unqueried baseline. Do not assume an element can query/restyle itself. Derive transitions from readable content/control needs and test their neighbors at different fonts.
6. Keep viewport queries for actual page architecture, navigation/sidebar states, viewport-bound overlays and short heights. Use hover/pointer/any-hover/any-pointer and preference queries for capabilities, not viewport width as their proxy.
7. Use bounded fluid spacing/display type only where beneficial. Body/UI readability and target minimums may remain fixed. Permit content-dependent block growth.
8. Keep intentional two-dimensional tables/maps/charts/code locally scrollable, labeled and keyboard usable; do not turn semantic tables into inferior cards.
9. Measure with JavaScript only when CSS cannot express the actual need, or existing indicator/canvas/positioning behavior requires it. Preserve justified measurement; batch reads/writes, bound observers and dispose them. Do not build a generic responsive engine.

Fixed icons, logos, artwork, aspect ratios, target minimums, app-shell modes and dialog maximums can be legitimate. Inspect whether content has a safe escape/scroll path before changing a constraint.

## Typography and font decision tree

Semantic role/readability → fixed versus bounded-fluid role → actual selected font stack → delivered formats/styles/Unicode coverage/axes → loaded, delayed, fallback and failed metrics → optical sizing/synthesis needs → measured loading/shift/payload costs → delivery optimization if justified.

- Preserve user zoom and text preferences. Pure vw sizing or refitting smaller text is not enlarged-text acceptance. Test actual computed enlargement as well as native text settings; rem/clamp alone proves neither.
- Preserve semantic weight/style and deliberate manual opsz; verify variable wght/opsz/wdth/italic ranges and high-level static fallback parity. Downloaded/loaded font faces do not prove which face rendered a glyph.
- Keep meaningful line-height/tracking, reading measures, script coverage and mobile-editable ergonomics. Use balance for suitable short headings and pretty for suitable prose, not globally. Do not shrink type to repair boxes.
- Inspect font-display/FOIT/FOUT, WOFF2/static versus variable economics, subsets, request count, bytes, cache and duplicate styles/preloads. Do not self-host, preload every face, reorder an authoritative system-first stack or request all axes automatically.
- Measure before size-adjust/metric overrides or synthesis restrictions. Test semantic emphasis and real fallback before suppressing fabricated styles. Text must remain readable and operable during delayed/failed loading; measure properly scoped font CLS rather than guessing from final screenshots.

## Content, source order and internationalization

Stress realistic long names/labels, URLs/emails/IDs/hashes, large values/currencies/dates, extra actions/badges, validation, loading/error/empty and asynchronous states. Use shrink boundaries, intrinsic tracks, flexible height and owned overflow-wrap where appropriate. Essential text cannot disappear behind clipping, clamping or truncation; document intentional bounded summaries with full-text access.

Keep DOM reading/focus order meaningful. Audit order/reverse/dense placement, semantic absolute positioning and duplicate responsive DOM. Exceptional visual/source divergence needs explicit interaction/accessibility evidence, not a blanket prohibition on decorative placement.

Use logical layout, lang/dir, bidi isolation and appropriate directional icons. Include Arabic/Hebrew, mixed RTL/LTR, CJK, long compounds and locale dates/numbers/currencies as fixtures where relevant. Do not invent supported product translations or reinterpret ambiguous numeric input silently.

## Media and asynchronous stability

Intrinsic dimensions/aspect and accessible alternative → appropriate responsive sizing/object-fit/art direction → srcset/sizes/picture/DPR or chart/canvas resolution as needed → justified priority/lazy strategy → loading/error geometry and labels/tooltips. Do not force every visual to width:100%.

Reserve honest geometry for fonts/media/API data/skeletons/banners/notifications where feasible. Verify both initial and settled frames; ready images or SSR fit variables do not prove styles, hydration or interactive initialization. Do not defer required controls merely to improve a resource metric.

## Floating UI, scroll and mobile

Reuse existing accessible positioning/portal primitives. Trace anchor/viewport/stack ownership, flipping/shifting/collision padding and available width/block size **through to the actual user-scrollable descendant**. A library variable on an outer wrapper does not prove wheel/touch access. Keep close, selected/last items, filters and required actions reachable at edges, short heights and enlargement. Preserve focus trapping/return, keyboard/typeahead and drag alternatives.

Choose necessary scroll owners, constrain meaningful local overflow and verify keyboard scrolling/affordance, scroll chaining, restoration and anchor offsets. Sticky/fixed surfaces must not obscure focused content; use owned clearance/scroll-padding/scroll-margin as needed. Preserve body-lock lifecycle. Root overflow:hidden/clip is never proof of responsive correctness. Verify scrollbar appearance/disappearance and resulting layout shifts; use scrollbar-gutter or overscroll-behavior only where useful and supported, preserving intentional scroll snapping and native scrolling.

Use dvh/svh/lvh and safe-area treatment according to the intended experience, not mechanical substitutions. Verify browser chrome/virtual keyboard/focused actions where physical testing is available. Native type/inputmode/autocomplete/enterkeyhint/labels follow actual field meaning. Emulated WebKit is not physical Safari, pinch zoom or mobile-keyboard proof.

## Interaction, preferences and motion

WCAG 2.2 AA is the minimum release requirement; retain stronger project rules, including existing 44×44 coarse-pointer targets in both dimensions. Mouse/touch/keyboard/hybrid support is independent of width. Hover is optional enrichment. Provide single-pointer/keyboard alternatives for nonessential dragging.

Preserve useful immediate feedback, interruptibility, spatial consistency and existing motion language. Do not animate ordinary wrapping or introduce arbitrary timers, layout-heavy resize loops, transition:all or new spring dependencies. Support reduced motion/forced colors and relevant contrast/transparency preferences with robust baselines; progressively supported preferences cannot be prerequisites for usability.

## Testing and enforcement

Extend existing tests/stories/showrooms and conformance architecture, not a second pipeline. Static matches (nowrap, fixed dimensions, breakpoints, reorder, root clipping, pure-vw type, font weights/preloads, drag-only, transition-all) are owner/reason review signals, not automatic bans.

- Sample critical viewport **and independent container** widths densely, including awkward intervals/transition neighbors, supported wide ranges, short heights/landscape. Refine actual failing intervals; sampled widths never prove every pixel combination.
- Test relevant focus/active/open/expanded/selected/disabled/loading/submitting/error/empty/populated/long-content/action/badge states, not only resting pages.
- Separately test 320 CSS-pixel reflow, computed/native 200% enlargement, reliable literal 400% browser zoom or explicitly qualified equivalents, and WCAG spacing. A 320 viewport alone is not zoom proof.
- Cover loaded/delayed/fallback/blocked fonts, appropriate axes/emphasis/script states, locales/RTL and capabilities/preferences. Keep physical devices/assistive technology distinct from automation.
- Inspect descendant and ancestor clipping, local scroll/client geometry, overlap and focused hit visibility. Restore test-only root unclipping; exclude justified local 2D regions, screen-reader bridges and known offscreen animation states intentionally.
- Assert actual wheel/touch/keyboard last-item reachability, close/focus return, selected-tab visibility, native/SSR forms and sticky focus clearance. Bounding boxes and axe alone are insufficient.
- Use strategic visual baselines with controlled readiness/font state and supported engines. Preserve original failures and immutable evidence; never overwrite old captures or regenerate manifests to hide loss.

## Performance and completion

Recheck current official LCP/INP/CLS definitions and product standards before gates. Bind production-build lab results to actual routes/resources/interactions and repeatable conditions; use existing approved field/RUM p75 data where available. Loopback, Lighthouse responsiveness proxies or event samples do not certify field INP/full-session CLS. Missing data/support is UNAVAILABLE, never zero. No invasive new telemetry, budget increase or feature removal to game checks.

A scoped UI fix is done only after causal regression checks, required native checks, and actual responsive, accessibility, visual and performance evidence on the final candidate. Record commands/results, intentional exceptions, unavailable dimensions and unresolved findings honestly.
