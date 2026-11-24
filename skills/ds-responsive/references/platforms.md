# Platform Mapping (`ds-responsive`)

The single canonical platform mapping for `ds-responsive`. Use it to translate the principles into the
target platform's native primitives, exact scale targets, performance signals, and verification checks;
`SKILL.md` stays platform-agnostic.

## Web (CSS / HTML / Browser)

- **Layout & shrink boundaries:** normal flow, Flexbox (`flex-wrap`, `min-inline-size: 0` at the real
  shrink boundary), Grid (`repeat(auto-fit|auto-fill, minmax(min(100%, X), 1fr))`, `subgrid`), container
  queries (`@container`), logical properties (`inline-size`, `margin-block`, `inset-inline`).
- **Viewport, scroll & safe areas:** `dvh` / `svh` / `lvh`, `env(safe-area-inset-*)`, `scroll-padding-*`,
  `scroll-margin-*`, `scrollbar-gutter`, `overscroll-behavior`. Reserve scrollbar space or use
  `scrollbar-gutter` so scrollbar appearance/disappearance does not trigger CLS, and preserve intentional
  `scroll-snap-type` / `scroll-snap-align` behavior.
- **Typography & font economics:** `rem`/`clamp()` (never pure `vw` for text), `text-wrap: balance|pretty`
  selectively, `font-display` and FOIT/FOUT behavior, WOFF2 subsetting, static vs variable weight axes,
  deduplicated preloads, measured font CLS and fallback metrics.
- **Media & DPR:** `srcset` / `sizes` / `<picture>` for art direction and density, `aspect-ratio`,
  `object-fit`, reserved geometry for loading/error states.
- **Targets, input & preferences:** WCAG 2.2 AA `24x24px` minimum baseline and `44x44px` minimum
  coarse-pointer targets; `@media (any-hover: hover)`, `(any-pointer: coarse|fine)`,
  `@media (prefers-reduced-motion: reduce)`, `(forced-colors: active)`, `(prefers-contrast: more)`.
  Match HTML input semantics (`type`, `inputmode`, `autocomplete`, `enterkeyhint`) to field meaning and
  preserve keyboard operability.
- **Accessibility semantics & focus:** semantic HTML first, ARIA only where native semantics fail,
  visible `:focus-visible`, focus trapping/return in dialogs, reading/focus order from DOM order.
- **Performance signals:** production-build Core Web Vitals (LCP/INP/CLS) and approved RUM; lab/loopback
  proxies do not certify field INP or full-session CLS.
- **Verification:** 320 CSS-pixel reflow, 200% computed and native text enlargement, 400% browser zoom,
  WCAG 2.2 text spacing, Tab/Escape/focus return, reduced-motion/forced-colors/contrast checks, and
  production-build Core Web Vitals.

## Mobile (iOS / Android / React Native / Flutter)

- **Layout & shrink boundaries:** SwiftUI `HStack`/`VStack`/`LazyVGrid`/`ViewThatFits`/`GeometryReader`
  with `layoutPriority`; Jetpack Compose `Row`/`Column`/`FlowRow`/`BoxWithConstraints`/`WindowSizeClass`
  with `weight(1f, fill = false)`; Flutter `Row`/`Column`/`Wrap`/`Flex`/`LayoutBuilder`/`MediaQuery` with
  `Expanded`/`Flexible`; React Native Flexbox with `useWindowDimensions` and `SafeAreaView`. Constrain
  flexible children at the real shrink boundary, not whole pages.
- **Scaling & size classes:** Dynamic Type (`@ScaledMetric`, no fixed line-height clipping) on iOS, `sp`
  and `fontScale` on Android, compact/regular size classes, foldable hinges, portrait + landscape,
  split-screen.
- **Typography & font economics:** system text styles and Dynamic Type first; bundled fonts subset with
  complete glyph coverage, variable axes verified, no duplicate weight/style files, no fixed
  line-height that clips enlarged text.
- **Media & DPR:** 1x/2x/3x assets or vectors, density-aware decoding, downsampling off the main thread,
  reserved geometry before async images land.
- **Safe areas, IME & input semantics:** status/nav bars, notch, Dynamic Island, home indicator, rounded
  corners, fold hinges, and keyboard/IME insets so focused inputs and submit buttons never sit behind
  the keyboard. Match native input semantics (`keyboardType`, `textContentType`, `imeOptions`) to field
  meaning.
- **Targets, semantics & focus:** `44x44pt` (iOS) and `48x48dp` (Android) minimum hit targets; meaningful
  labels, hints and traits/roles; logical VoiceOver/TalkBack traversal and grouped composite cards;
  Light/Dark/High-Contrast contrast; OS Reduce Motion and Animator Duration Scale.
- **Performance signals:** frame pacing/jank, cold and warm start latency, memory and thermal budgets.
- **Verification:** compact phone, large phone, tablet/split-screen, portrait + landscape, largest
  accessibility text size (Dynamic Type / Font Scale), Light + Dark mode, RTL mirroring, screen-reader
  traversal order, Reduce Motion behavior, and frame/startup/memory checks.

## Desktop (macOS / Windows / Linux / Electron / Tauri / Rust iced / Qt / GTK)

- **Layout & shrink boundaries:** flexible split panes, resizable sidebars/inspectors, explicit shrink
  boundaries and bounded min-widths on flexible panes, enforced min/max window sizes, responsive toolbar
  overflow, scrollable regions with sticky headers and clearance, bounded dialog maximums.
- **Scaling & DPI:** logical vs physical pixels (1x / 1.25x / 1.5x / 2x), OS text/font-scale settings,
  window position and size restoration across monitor disconnect and DPI change.
- **Typography & font economics:** system font stacks with metric-compatible fallbacks, bundled font
  subsets where licensed, variable font axes honored, no synthesized-bold/italic substitutes.
- **Media & DPR:** vector or multi-DPI icon sets, 1x/2x raster pairs, crisp fractional-scale rendering,
  no upscaled bitmap UI.
- **Safe areas, input & preferences:** window chrome/titlebar safe regions, native file/dialog
  conventions, `>=24x24pt` comfortable pointer click targets, full keyboard traversal (Tab/Shift-Tab,
  arrows in lists/trees, Escape to dismiss, Cmd vs Ctrl shortcuts), clear keyboard focus rings,
  drag-and-drop with keyboard alternatives, hover precision without hover-scale, and OS reduced-motion,
  high-contrast, and accent preferences.
- **Accessibility semantics & focus:** native accessibility tree (NSAccessibility, UIAutomation,
  AT-SPI/AccessKit), screen-reader announcements for async status and errors, always-visible focused row
  in scrollable lists/tables.
- **Performance signals:** idle and scroll frame pacing, live drag-resize fluidity, memory stability.
- **Verification:** minimum window size, typical workspace size, maximized/ultrawide, live drag resize,
  OS text/DPI scaling, reduced-motion/high-contrast checks, keyboard-only traversal, and frame pacing.

## TV / 10-Foot UI (Tizen / Lightning / Blits / tvOS / Android TV / webOS)

- **Layout & shrink boundaries:** safe-zone/overscan padding (~5% margin), horizontal rails/shelves with
  predictable card geometry, focused-item centering or fixed-rail scroll, explicit focus-graph neighbors,
  low visual density per screen.
- **Scaling & targets:** 1080p and 4K layouts that scale without reflow surprises, 10-foot viewing-distance
  legibility floor (`>=24px` / `18sp` body at 1080p; no low-contrast muted text), and clear 10-foot focus
  target separation with high-contrast ring/glow/elevation and an active label.
- **Typography & font economics:** large minimum body/label sizes (`>=24px` / `18sp` body at 1080p),
  strong contrast for dim rooms, bundled font subsets with full glyph coverage, no thin weights or
  hairline strokes at 10 feet.
- **Media & DPR:** 1x/2x texture sets within GPU memory, minimal simultaneous textures, no expensive
  blurs/filters, prompt disposal of offscreen media and textures.
- **Safe areas, input & preferences:** overscan safe zones, deterministic D-pad graph
  (Up/Down/Left/Right/Enter/Back), no hover-only or pointer-only affordances, clean Back-key stack
  (modal → section → home → exit), no focus traps or dead ends; honor platform reduced-motion and
  high-contrast preferences where exposed.
- **Accessibility semantics & focus:** focus is the orientation cue, readable contrast at distance,
  audible/spoken labels where the platform exposes them, no reliance on color alone.
- **Performance signals:** frame budget (smooth 60fps or target refresh rate during rail scroll and focus
  transitions) and GPU/texture memory ceiling.
- **Verification:** 1080p and 4K scaling, overscan safe-zone check, full D-pad traversal across every
  screen/modal, Back-key recovery, reduced-motion/high-contrast check where supported, and GPU
  texture/memory plus frame-budget check on target TV or emulator.
