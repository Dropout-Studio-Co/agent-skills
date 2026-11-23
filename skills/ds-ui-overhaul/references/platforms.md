# Platform-Specific UI/UX Guidance (`ds-ui-overhaul`)

Consult only the section(s) matching the repository's actual target platform(s).

## Web (HTML/CSS/JS, SvelteKit, React, Vue, Astro, etc.)

- **Layout & responsiveness:** CSS normal flow, Flexbox, Grid, container queries, logical
  properties, `dvh`/`svh`/`lvh`, safe-area insets. Check 320px reflow, 200%/400% zoom, and
  pointer vs touch (`any-hover` / `any-pointer`).
- **Accessibility:** Semantic HTML, native controls over clickable `<div>`s, ARIA only when
  native semantics are insufficient, visible `:focus-visible`, focus trapping/return in dialogs,
  WCAG 2.2 AA contrast and target sizes (44x44px coarse pointer).
- **Motion & performance:** Animate compositor-friendly properties (`transform`, `opacity`); avoid
  layout thrashing, heavy `backdrop-filter` over scrolling content, and blanket `will-change`.
  Respect `@media (prefers-reduced-motion: reduce)`.
- **Rendered verification:** `chrome-devtools-axi` (AXI Chrome, never personal Chrome) across
  desktop, tablet/laptop, and mobile viewports plus interactive states, keyboard traversal, and
  console/hydration errors.
- **Site gate:** For `horcrux.app`, `dropoutstudio.co`, and `beyourahi.com`, Lighthouse 13 on
  production build (mobile + desktop, 4 categories, medians of 3 serial runs) is mandatory before
  merge.

## Mobile (iOS SwiftUI/UIKit, Android Compose/Views, React Native, Flutter)

- **Layout & ergonomics:** Respect safe areas (notch, Dynamic Island, home indicator, status/nav
  bars, foldables), compact/regular size classes, portrait + landscape, split-screen, and virtual
  keyboard / IME avoidance so active inputs and primary actions stay visible.
- **Touch & gestures:** Minimum 44x44pt (iOS) / 48x48dp (Android) hit targets, generous spacing
  between destructive and primary actions, system back-gesture/edge-swipe compatibility, haptics
  used with restraint.
- **Typography & scaling:** Support Dynamic Type (iOS) / `sp` font scaling (Android) without
  clipping or overlapping controls; allow multi-line wrapping and vertical growth.
- **Accessibility:** Meaningful accessibility labels, hints, traits/roles, logical VoiceOver /
  TalkBack traversal order, grouped composite cards, contrast in Light/Dark/High-Contrast modes,
  OS Reduce Motion / Animator Duration Scale.
- **Motion & performance:** Hold 60/120fps during scrolling and transitions; avoid synchronous I/O,
  image decoding, or heavy layout passes on the UI thread; keep sheet/drawer physics interruptible.
- **Rendered verification:** iOS Simulator and/or Android Emulator (via simulator/emulator tools
  such as `device_*` / `agent-device`, or the project test harness) across compact phone, large
  phone/tablet, landscape, dark/light, and enlarged text settings.

## Desktop (macOS, Windows, Linux, Electron, Tauri, Rust/iced/wgpu, Qt, GTK)

- **Windowing & scaling:** Test minimum window size, typical workspace size, ultrawide/maximized,
  live resize without jitter or lost controls, HiDPI / fractional scaling (1x/1.5x/2x), and
  multi-monitor behavior.
- **Input & navigation:** Full keyboard operability (Tab/Shift-Tab, arrow keys in lists/trees,
  Escape to dismiss, platform-idiomatic shortcuts Cmd vs Ctrl), clear focus indicators, context
  menus, drag-and-drop with keyboard alternatives, hover precision without jittery hover-scale.
- **Native integration:** Respect OS theme (light/dark/accent), system font metrics and scaling,
  window chrome/titlebar safe regions, native file/dialog conventions where appropriate.
- **Accessibility:** Native accessibility tree (NSAccessibility, UIAutomation, AT-SPI/AccessKit),
  contrast, reduced motion, screen-reader announcements for async status/errors.
- **Motion & performance:** Smooth frame pacing on resize/scroll/playback, bounded GPU/CPU usage
  when idle or occluded, no unnecessary full-tree relayouts or redraw loops.
- **Rendered verification:** Launch the built app, capture screenshots across window sizes and
  states, exercise keyboard flows, and inspect logs/metrics for frame drops or layout warnings.

## TV / 10-Foot UI (Samsung Tizen / Lightning / Blits, tvOS, Android TV, WebOS)

- **10-foot ergonomics:** Design for living-room viewing distance: larger minimum body/label sizes,
  strong contrast against dark/ambient rooms, low visual density, generous overscan/safe-zone
  margins (typically 5% / ~48-96px at 1080p) so nothing clips at screen edges.
- **D-pad & remote navigation:** Every interactive element must be reachable via a deterministic
  directional focus graph (Up/Down/Left/Right/Enter/Back). Never strand focus, never rely on
  hover or pointer coordinates, and maintain a clean Back-key navigation stack (modal → section →
  home → exit confirmation).
- **Focus visibility:** Focus state is the primary orientation cue on TV — make the focused item
  unmistakable (high-contrast ring/glow/elevation/label) and keep focused rows/cards scrolled
  comfortably within the safe viewport.
- **Hardware & GPU budgets:** Constrained TVs (e.g. older Tizen WebEngines) have tight RAM, GPU
  texture memory, and CPU budgets. Minimize simultaneous textures, avoid expensive blurs/filters,
  dispose offscreen media/textures promptly, and test under realistic frame budgets.
- **Rendered verification:** Capture screens on TV emulator or physical TV (e.g. `tizen-screenshot`
  or platform CLI), verify full D-pad traversal, Back-key stack, overscan safety, and runtime logs
  (`dlog` / `adb logcat`).
