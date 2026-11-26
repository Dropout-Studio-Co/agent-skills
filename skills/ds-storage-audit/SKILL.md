---
name: ds-storage-audit
description: Audit a computer's storage and report what is safe to remove, how much space each item frees, and the total reclaimable space — without ever deleting anything. Use when asked to audit storage, find what is using disk space, clean up a full or slow drive, or free up space on macOS, Linux, Windows, or WSL.
argument-hint: "Optional: a path, drive, or volume to audit (defaults to the whole machine)"
license: MIT
---

# Storage Audit (`ds-storage-audit`)

Find the storage that can be safely reclaimed on this machine and report it in plain language. This skill is strictly read-only: it inspects sizes and names only and never deletes, moves, renames, truncates, or writes anything.

**Input:** an optional path, drive, or volume. **Output:** one plain-language report of safe-to-remove items, presented as one sorted numbered (ordered) list where each item gives what to delete, what it is, and how much space it frees.

Consult [`references/os-locations.md`](references/os-locations.md) for the exhaustive per-OS inventory and read-only probe commands, and [`references/safety-classification.md`](references/safety-classification.md) for the safe/never-recommend rules, sizing rules, and jargon translation.

## 1. Detect the Host OS, Volumes & Scope

- **Detect the host OS first:** macOS, Linux, Windows, or WSL. Every later path and command must match the detected OS; never apply one OS's locations to another. On WSL, audit both the Linux side and the Windows-side user folders.
- **Inventory volumes:** list mounted local writable filesystems and record total, used, and free space for each. Skip pseudo-filesystems (`proc`, `sysfs`, `devtmpfs`, `tmpfs`, `squashfs`) and skip network or FUSE mounts unless the user explicitly targets one.
- **Resolve scope:** use the optional path, drive, or volume argument when given; otherwise audit the entire machine — all mounted local writable filesystems. Keep the scope fixed for the whole audit.
- **Validate an explicit target:** confirm it exists, is a directory or volume root, and is readable. When it is a file rather than a folder, audit only that file's containing area or explain plainly that a folder or drive is expected.
- **Fail once, plainly:** if an explicit target is missing, unmounted, or unreadable, stop immediately with one plain-language sentence and run nothing else.
- **Note the permission posture:** do not ask for administrator rights. Some locations will be unreadable; that is expected and belongs in the closing note, not a reason to stop.
- **Completion criteria:** host OS identified, every mounted local volume listed with total/used/free, and the scope fixed to either a verified readable target or the whole machine.

## 2. Run the Exhaustive Two-Pass Scan

Run **Pass A** and **Pass B** every time; each catches what the other misses.

### Pass A — known cleanup locations

Walk the OS, user, app, browser, developer, container, SDK, package, and installer locations appropriate to the detected host OS, exactly as listed in [`references/os-locations.md`](references/os-locations.md):

- **Operating-system and user leftovers:** caches, trash and recycle bins, logs, crash reports, temporary folders, update caches, and local snapshots.
- **Browsers:** cache folders only — never profiles, cookies, history, bookmarks, or saved passwords.
- **Applications:** Electron, messaging, media, and editor caches, never application data.
- **Developer, SDK, package, and container caches:** Xcode and simulator caches, Android/Gradle/Maven, npm/pnpm/yarn/bun/deno, Playwright/Cypress, pip/uv/poetry/conda, Cargo/Go/Homebrew, Docker/Podman reclaimable build cache and dangling images, and unused AI model downloads.
- **Installers:** leftover setup files in Downloads (`.dmg`, `.pkg`, `.iso`, `.msi`, `.exe`, `.deb`, `.rpm`) only when the name clearly shows a setup installer.

### Pass B — bounded whole-disk discovery

Run a top-down, depth-limited scan of the local filesystems in scope to catch large non-standard candidates outside the checklist — for example a stale build cache in a non-standard folder, an orphaned log directory, or a leftover setup installer:

- Stay on one filesystem (`-x` or `-xdev`), cap depth (`-d 3` or `--max-depth=3`), and aggregate by directory rather than listing individual files.
- Compare what you find against the safe categories and the hard exclusions in [`references/safety-classification.md`](references/safety-classification.md). Large alone is never enough to recommend something.
- Treat a candidate found by Pass B as a lead to classify, not an automatic recommendation.

### Scan discipline

- **Bound every probe:** give each probe a short timeout. If a probe times out, record the area as skipped for the closing note and continue; never abort the audit.
- **Tolerate noise:** ignore files that disappear during traversal, suppress error chatter from unreadable paths, and guard every ecosystem probe with an availability check (`command -v` or `Get-Command`) so absent tools are skipped silently.
- **Read names and sizes only:** never open, print, or copy the contents of a discovered file.
- **Completion criteria:** Pass A covered every applicable location for the detected OS, Pass B covered the whole scope at bounded depth, and every timeout, missing tool, and unreadable area is recorded for the closing note.

## 3. Safety Filter, Deduplicate & Size

### Keep only safe items

Apply [`references/safety-classification.md`](references/safety-classification.md) and retain an item only when it is a verified cache, log, temporary file, trash/recycle-bin item, regenerable build artifact, or clearly identifiable setup installer. **Exclude when unsure.** A missed recommendation costs nothing; a wrong one costs the user data.

### Enforce the hard exclusions

Never recommend operating-system core files, system-protected paths, swap/sleep/hibernation/page files, personal documents, photos, media, projects, `.git` repositories, databases, active container volumes, browser profiles, cookies, bookmarks, passwords, credentials, keys, keychains, `.env` files, backups, cloud placeholders, or any unverified or ambiguous folder.

### Remove double-counting

- Never count a parent and its child together; report the largest safe item once and drop any item contained in another reported item.
- Collapse repeated paths reached through APFS firmlinks or symlinks, and never follow symlinks while measuring.
- Deduplicate hard links by device and inode where the OS exposes it, and never inflate results with filesystem clones.

### Measure real reclaimable bytes

Measure on-disk blocks on a single filesystem (`-x`, `du -P`). Do not use apparent sizes for sparse files, disk images, or cloud placeholders; do not hydrate a cloud placeholder to measure it. For containers, use the engine's own reclaimable figure (`docker system df` or `podman system df`) rather than the sparse disk-image size.

### Apply the reporting floor and sort

- List items of at least 25 MB individually. When fewer than five items reach 25 MB, include items down to 1 MB so the report is still useful.
- Re-check that each reported path still exists; silently drop anything that vanished during the scan before totals are computed.
- Sort the final list strictly descending by exact reclaimable bytes (largest to smallest), breaking ties in alphabetical order by item name.

**Completion criteria:** every retained item is verifiably safe, every excluded or ambiguous item is absent, no parent/child overlap remains, cloud placeholders were not hydrated, and the list is sorted largest to smallest by exact bytes.

## 4. Present the Plain-Language Report

Return one plain-language report built around a single numbered (ordered) list. Do not dump raw command output, file listings, or technical jargon.

### List presentation

Every audit that has at least one qualifying item renders exactly one sequential 1-based Markdown numbered (ordered) list (`1.`, `2.`, `3.`, ...) with one single-line item per entry, formatted as:

`1. **<What to delete>** — <What it is> — **<Space freed>**`

- **What to delete**: the recognizable name plus a concise location or path, for example "Chrome's web page cache (`~/Library/Caches/Google/Chrome`)". Never show a raw bare path on its own. On a multi-volume audit, include the volume name so every item stays unambiguous.
- **What it is**: one concise plain-language sentence explaining what the item is and why removing it is safe. No jargon.
- **Space freed**: the reclaimable size in consistent human units such as `6.2 GB` or `420 MB`.

### Report order

1. **Open with context:** state the total space that could be reclaimed, then the current free and total space for each audited local volume.
2. **Confirm the boundary:** state explicitly that nothing was deleted and that this was an inspection only.
3. **Present the list:** one unified numbered list whose items are sorted strictly descending by exact reclaimable bytes (largest to smallest), breaking ties in alphabetical order by item name. On multi-volume audits, merge every volume's items into this one sorted list; do not emit one list per volume.
4. **Add the Total line:** finish with a single unnumbered bold `**Total**` line directly below the list — `**Total** — Sum of the listed items — **<size>**` — whose size equals the sum of the displayed items and matches the opening reclaimable total. The Total line always stays below the list and is never numbered or sorted into the items.
5. **Close with limitations:** add one brief closing note below the list only when some areas could not be inspected, naming the permission-restricted or timed-out locations plainly. Those areas appear only in that note, never as items in the safe-to-delete list, and the note is omitted when everything was readable.

### Item discipline

Keep every item single-line and scannable:

- Collapse newlines and control characters in discovered names to single spaces so a name cannot split an item or inject extra list items.
- Escape or neutralize Markdown formatting characters such as `*`, backticks, or a leading list marker so a discovered name cannot alter the list structure.
- Use no raw command output, nested blocks, or multi-line text inside an item.

### Example shape

```text
You can free about 14.7 GB. This disk has 42 GB free of 250 GB. Nothing was deleted — this was an inspection only.

1. **Chrome's web page cache** — Temporary copies of web pages Chrome keeps to load sites faster; Chrome rebuilds them automatically. — **6.2 GB**
2. **Old iPhone development support files** — Copies of device support files from older Xcode versions; Xcode recreates them when needed. — **5.4 GB**
3. **Downloaded app updates no longer needed** — Installer packages for updates that have already been installed. — **3.1 GB**

**Total** — Sum of the listed items — **14.7 GB**
```

### Edge and failure cases

- **Clean machine (0 qualifying items):** omit the numbered list and the Total line entirely — never render an empty or placeholder list. Say the storage is already clean, report the free/total context, confirm nothing was deleted, and name any restricted locations.
- **Single qualifying item:** render the list with its single `1.` item and the unnumbered bold `**Total**` line.
- **Multi-volume audits:** merge every volume's items into one sorted numbered list and include volume context in the "What to delete" part.
- **Restricted, permission-denied, or timed-out areas:** finish the accessible audit first, then name them only in the brief closing note below the list. Never add them as list items and never escalate privileges.
- **Vanished items:** re-check each path before numbering and totaling; drop anything that vanished so the numbering stays sequential and the Total reflects only items that still exist.
- **Large item counts:** keep everything in one unified descending numbered list; never silently truncate the list.
- **Invalid explicit target:** fail once in plain language before scanning and render no list.
- **Interrupted run:** the audit is stateless and read-only, so cancelling leaves zero leftovers and a re-run is safe and idempotent.

**Completion criteria:** every qualifying item appears as a single-line numbered entry in one sequential list sorted strictly descending by exact bytes with alphabetical tie-breaking; the unnumbered bold Total line equals both the sum of the displayed items and the opening reclaimable total; total reclaimable, free/total context, and the no-deletion confirmation are present; restricted or timed-out areas appear only in the closing note below the list; a clean machine renders no list at all.

## Hard Guardrails

- **Read-only, always:** never delete, move, rename, truncate, prune, compact, empty a trash or recycle bin, or write a temporary or state file. Report only.
- **Least privilege:** run strictly as the invoking user. Never ask for or use administrator rights, password prompts, elevation dialogs, or `sudo`.
- **No secret exposure:** never read or print the contents of user files, `.env` files, keys, keychains, browser credential stores, or password managers. Inspect names and sizes only.
- **Safe command handling:** quote every path, place `--` before paths that start with a dash, and never use `eval` or unquoted expansion of discovered names.
- **Fully offline:** make no network requests and fetch nothing.
