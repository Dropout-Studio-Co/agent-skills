# Platform Deltas for UI/UX Overhaul (`ds-ui-overhaul`)

Layout, scaling, typography, media/DPR, safe areas, input and accessibility primitives are canonical in
`~/.agents/skills/ds-responsive/references/platforms.md`; this file adds only what the overhaul adds:
motion/rendering budgets and rendered capture/verification per platform.

## Web (HTML/CSS/JS, SvelteKit, React, Vue, Astro)

- **Motion budget:** animate compositor-friendly properties (`transform`, `opacity`); no layout thrashing,
  no heavy `backdrop-filter` over scrolling content, no blanket `will-change`, no `transition: all`.
  Respect `@media (prefers-reduced-motion: reduce)`; keep interaction feedback interruptible.
- **Rendering budget:** hold production-build Core Web Vitals and long-task/memory stability; investigate
  avoidable main-thread work, hydration cost and excessive JS animation rather than tweaking scores.
- **Capture and logs:** `chrome-devtools-axi` (AXI Chrome, never personal Chrome) across desktop, tablet and
  mobile viewports plus interactive states and keyboard traversal; read console, network and hydration
  errors, and keep the trace/screenshot paths in the rendered-evidence manifest.

## Mobile (iOS SwiftUI/UIKit, Android Compose/Views, React Native, Flutter)

- **Frame budget:** hold 60/120fps during scroll, sheet and transition; keep sheet/drawer physics
  interruptible; avoid synchronous I/O, image decoding or heavy layout passes on the UI thread.
- **Memory/GPU budget:** no unbounded image caches, no oversized backdrop blurs, release offscreen decode
  buffers; watch thermal throttling and memory warnings on lower-end devices.
- **Capture and logs:** iOS Simulator and/or Android Emulator through simulator/emulator tools
  (`device_*` / `agent-device`) or the project harness, covering compact, large, landscape and enlarged text;
  capture screenshots plus device/app logs for jank, layout warnings and dropped frames.

## Desktop (macOS, Windows, Linux, Electron, Tauri, Rust/iced/wgpu, Qt, GTK)

- **Frame budget:** smooth frame pacing on live resize, scroll and playback; no unnecessary full-tree
  relayouts or redraw loops.
- **Memory/GPU budget:** bounded GPU/CPU use when idle or occluded; no leaked surfaces, textures or
  timers; verify steady memory across repeated open/close and resize cycles.
- **Capture and logs:** launch the built app, capture screenshots across window sizes and states, exercise
  keyboard flows, and inspect logs/metrics for frame drops, layout warnings and DPI-change artifacts.

## TV / 10-Foot UI (Samsung Tizen / Lightning / Blits, tvOS, Android TV, WebOS)

- **Frame budget:** constrained TVs (older Tizen WebEngines) miss frames easily; keep transitions short and
  cheap, avoid continuous animation behind focus moves, and test against the target device's real budget.
- **GPU/texture memory budget:** minimize simultaneous textures, avoid expensive blurs/filters and large
  overdraws, dispose offscreen media/textures promptly, and prefer solid/elevation focus cues.
- **Capture and logs:** TV emulator or physical TV through `tizen-screenshot` or the platform CLI, verifying
  focus traversal, Back-key stack and overscan; read runtime logs (`dlog` / `adb logcat`) for engine errors,
  dropped frames and memory pressure.
