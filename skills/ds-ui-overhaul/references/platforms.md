# Platform Deltas for UI/UX Overhaul (`ds-ui-overhaul`)

Layout, scaling, typography, media/DPR, safe areas, input and accessibility primitives are canonical in
`~/.agents/skills/ds-responsive/references/platforms.md`; this file adds only what the overhaul adds:
motion/rendering budgets, platform-specific UX checks, and rendered capture/verification per platform.

## Web (HTML/CSS/JS, SvelteKit, React, Vue, Astro)

- **Motion budget:** animate compositor-friendly properties (`transform`, `opacity`); keep interaction
  feedback interruptible and honor `@media (prefers-reduced-motion: reduce)`. Avoid layout thrashing, heavy
  `backdrop-filter` over scrolling content, blanket `will-change`, and `transition: all`.
- **Rendering budget:** hold production-build Core Web Vitals and long-task/memory stability; investigate
  avoidable main-thread work, hydration cost, and excessive JS animation rather than tweaking scores.
- **Capture and logs:** use `chrome-devtools-axi` (AXI Chrome, never personal Chrome) across desktop, tablet,
  and mobile viewports plus interactive states and keyboard traversal. List screenshot/recording entries as
  absolute or `~`-prefixed media paths in the rendered-evidence manifest, and write console, network, and
  hydration errors inline in the manifest text (non-media files are not copied by `review_task.py`).

### Lighthouse 13 site gate

Required before merge for UI changes to `horcrux.app`, `dropoutstudio.co`, and `beyourahi.com`:

- Run Lighthouse 13 on the production build of the affected pages at mobile and desktop for all four
  categories (`performance`, `accessibility`, `best-practices`, `seo`).
- Take the median of three serial runs per page and viewport, and compare each against the repository's
  thresholds (a missing threshold is a gap to report, not a waiver).
- Record candidate commit/build, URL, viewport, median category scores, and report/evidence details
  **inline** in the rendered-evidence manifest (non-media report files are not copied automatically).
- A failing or missing Lighthouse 13 result is an Important finding and blocks delivery.

## Mobile (iOS SwiftUI/UIKit, Android Compose/Views, React Native, Flutter)

- **Frame budget:** hold 60/120fps during scroll, sheet, and transition; keep sheet/drawer physics
  interruptible; avoid synchronous I/O, image decoding, or heavy layout passes on the UI thread.
- **Memory/GPU budget:** bound image caches, avoid oversized backdrop blurs, release offscreen decode
  buffers, and watch thermal throttling and memory warnings on lower-end devices.
- **Ergonomics and feedback:** keep clear spacing between destructive and primary actions, preserve system
  back-gesture and edge-swipe compatibility, and use restrained haptics tied to real confirmation or state
  boundaries.
- **Capture and logs:** use iOS Simulator and/or Android Emulator through simulator/emulator tools
  (`device_*` / `agent-device`) or the project harness, covering compact, large, landscape, dark/light mode,
  and enlarged text; list absolute or `~`-prefixed screenshot/recording paths and summarize device/app logs
  (jank, layout warnings, dropped frames) inline in the rendered-evidence manifest.

## Desktop (macOS, Windows, Linux, Electron, Tauri, Rust/iced/wgpu, Qt, GTK)

- **Frame budget:** hold smooth frame pacing on live resize, scroll, and playback; avoid unnecessary
  full-tree relayouts or redraw loops.
- **Memory/GPU budget:** bound GPU/CPU use when idle or occluded; prevent leaked surfaces, textures, or
  timers; verify steady memory across repeated open/close and resize cycles.
- **Desktop integration:** verify OS theme adaptation (light, dark, and accent colors), context menus, and
  multi-monitor behavior (mixed DPI, window moves, and secondary-display placement).
- **Capture and logs:** launch the built app, capture screenshots across window sizes, OS themes, displays,
  and states, exercise keyboard and context-menu flows, and write log/metric findings (frame drops, layout
  warnings, DPI-change artifacts) inline in the rendered-evidence manifest.

## TV / 10-Foot UI (Samsung Tizen / Lightning / Blits, tvOS, Android TV, WebOS)

- **Frame budget:** constrained TVs (older Tizen WebEngines) miss frames easily; keep transitions short and
  cheap, avoid continuous animation behind focus moves, and test against the target device's real budget.
- **GPU/texture memory budget:** minimize simultaneous textures, avoid expensive blurs/filters and large
  overdraws, dispose offscreen media/textures promptly, and prefer solid/elevation focus cues.
- **Capture and logs:** use a TV emulator or physical TV through `tizen-screenshot` or the platform CLI,
  verifying focus traversal, Back-key stack, and overscan; summarize runtime logs (`dlog` / `adb logcat`)
  for engine errors, dropped frames, and memory pressure inline in the rendered-evidence manifest.
