# Platform Mapping (`ds-responsive`)

Use this reference to translate `ds-responsive` principles into the target platform's native
primitives and verification checks.

## Web (CSS / HTML / Browser)

- **Layout primitives:** Normal flow, Flexbox (`flex-wrap`, `min-inline-size: 0`), CSS Grid
  (`repeat(auto-fit|auto-fill, minmax(min(100%, X), 1fr))`, `subgrid`), Container Queries
  (`@container`), logical properties (`inline-size`, `margin-block`, `inset-inline`).
- **Viewport & safe areas:** `dvh` / `svh` / `lvh`, `env(safe-area-inset-*)`, `scroll-padding-*`,
  `scroll-margin-*`, `scrollbar-gutter`, `overscroll-behavior`.
- **Capabilities & preferences:** `@media (any-hover: hover)`, `(any-pointer: coarse)`,
  `(prefers-reduced-motion: reduce)`, `(forced-colors: active)`, `(prefers-contrast: more)`.
- **Typography & media:** `rem`/`clamp()` (never pure `vw`), `text-wrap: balance|pretty`,
  `font-display`, WOFF2 subsetting, `srcset`/`sizes`/`<picture>`, `aspect-ratio`, `object-fit`.
- **Verification:** 320 CSS-pixel reflow, 200% computed/native text enlargement, 400% browser zoom,
  WCAG 2.2 text spacing, keyboard Tab/Escape/focus-return, Core Web Vitals (LCP/INP/CLS).

## Mobile (iOS / Android / React Native / Flutter)

- **Layout primitives:** SwiftUI `HStack`/`VStack`/`LazyVGrid`/`ViewThatFits`/`GeometryReader`;
  Jetpack Compose `Row`/`Column`/`FlowRow`/`BoxWithConstraints`/`WindowSizeClass`; Flutter
  `Row`/`Column`/`Wrap`/`Flex`/`LayoutBuilder`/`MediaQuery`; React Native Flexbox +
  `useWindowDimensions` + `SafeAreaView`.
- **Safe areas & IME:** System bars, notches, Dynamic Island, rounded corners, foldable hinges,
  and keyboard/IME insets so focused inputs and submit buttons never hide behind the keyboard.
- **Typography & targets:** iOS Dynamic Type (`@ScaledMetric`, no fixed line-height clipping);
  Android `sp` + `fontScale`; minimum 44x44pt (iOS) / 48x48dp (Android) hit targets.
- **Verification:** Compact phone, large phone, tablet/split-screen, portrait + landscape,
  largest accessibility text size, RTL mirroring, VoiceOver/TalkBack focus order, Reduce Motion.

## Desktop (macOS / Windows / Linux / Electron / Tauri / Rust iced)

- **Layout primitives:** Flexible split panes, resizable sidebars/inspectors, min/max window
  constraints, responsive toolbar overflow, scrollable content regions with sticky headers and
  scroll clearance.
- **DPI & multi-monitor:** Logical vs physical pixels (1x / 1.25x / 1.5x / 2x scaling), crisp
  vector/multi-DPI icons, window restoration on monitor disconnect/DPI change.
- **Input & focus:** Full keyboard traversal, visible focus rings, native shortcut conventions,
  scrollable lists/tables that keep the focused row visible.
- **Verification:** Minimum window size, typical workspace size, maximized/ultrawide, live drag
  resize, OS text/DPI scaling, keyboard-only traversal, idle/scroll frame pacing.

## TV / 10-Foot UI (Tizen / Lightning / Blits / tvOS / Android TV)

- **Layout primitives:** Safe-zone/overscan padding (~5% margin), horizontal rails/shelves with
  predictable card geometry, fixed-rail or focused-item centering scroll, explicit focus-graph
  neighbors.
- **Typography & contrast:** 10-foot legibility (avoid tiny body copy or low-contrast muted text),
  clear focus highlight (elevation, high-contrast ring/border, active label), minimal visual
  clutter per screen.
- **Input & navigation:** D-pad directional focus (Up/Down/Left/Right/Enter/Back), no hover-only
  or pointer-only affordances, deterministic Back-key stack, no focus traps or dead ends.
- **Verification:** 1080p and 4K scaling, overscan safe-zone check, full D-pad traversal across
  every screen/modal, Back-key recovery, GPU texture/memory and frame-budget check on target TV
  or emulator.
