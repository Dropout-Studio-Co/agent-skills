# Safety Classification, Sizing & Plain-Language Guide

Reference for [`SKILL.md`](../SKILL.md). Apply this filter to every candidate from both passes. When a candidate is ambiguous, leave it out: a missed recommendation costs nothing; a wrong one costs the user data.

## 1. Safe to Recommend

An item qualifies only when **all** of these are true:

- It is a **cache, log, temporary file, trash/recycle-bin item, regenerable build artifact, or a clearly identifiable setup installer**.
- The application or tool that owns it can recreate it on demand, or the user has already discarded it.
- It lives in a location listed in [`os-locations.md`](os-locations.md) for the detected host OS, or Pass B proved it is one of the categories above.
- The path and its purpose are unambiguous from the name and location.
- Removing it cannot remove personal data, installed software, account state, or a running service.

Typical safe groups:

- Browser **cache** folders only, never profiles, sessions, cookies, history, bookmarks, saved passwords, or extensions data.
- Package-manager download caches (`apt`, `dnf`, `pacman`, `flatpak`, `snap`, Homebrew, npm, pnpm, yarn, bun, deno, pip, uv, poetry, conda).
- Build and tool caches (Xcode DerivedData and device support, Gradle, Maven local repository cache, Cargo registry cache, Go build cache, Playwright and Cypress browsers).
- Container **reclaimable** build cache and dangling images, as reported by `docker system df` or `podman system df` — never active images in use or any volume.
- Logs, crash reports, coredumps, update download caches, and temporary directories.
- Time Machine **local snapshots** (recommend thinning only) and `Windows.old` (recommend the built-in cleanup only).
- Leftover setup installers in Downloads (`.dmg`, `.pkg`, `.iso`, `.msi`, `.exe`, `.deb`, `.rpm`) when the filename clearly identifies an installer rather than a personal archive.
- AI/ML model downloads that are clearly unused duplicates of a currently referenced model.

## 2. Never Recommend (Hard Exclusions)

Never list any of the following, even when it is large. This list wins over every other rule:

- **Operating-system core and protected paths:** macOS System and `/System/Volumes/Preboot`, SIP-protected locations, Linux `/boot`, `/usr`, `/lib`, `/etc`, `/bin`, `/sbin`, Windows `C:\Windows\System32`, `WinSxS`, `C:\Program Files`, `C:\Program Files (x86)`, and any system-protected folder.
- **Swap, sleep, and memory files:** `swapfile`, `swap`, `pagefile.sys`, `hiberfil.sys`, `sleepimage`, `/private/var/vm/`, and any paging or hibernation file.
- **Personal data:** documents, photos, videos, music, Downloads content that is not a setup installer, desktop files, email stores, chat histories, calendars, contacts, and notes.
- **Projects and source control:** source trees, `.git` repositories, `.hg`/`.svn` metadata, workspace files, and build outputs that are not clearly regenerable caches (when in doubt, exclude).
- **Databases and application state:** database files and directories, application support data, save games, sync state, virtual machines, and disk images the user created.
- **Containers and volumes:** active container volumes, running images, and raw engine disk files. Report only the engine's stated reclaimable amount.
- **Browser profiles and secrets:** browser profile folders, cookies, history, bookmarks, passwords, autofill data, extensions, and session stores.
- **Credentials and keys:** SSH and GPG keys, keychains, password-manager data, tokens, certificates, `.env` files, `.dev.vars`, `.npmrc`/`.pypirc` credentials, and cloud CLI credentials.
- **Cloud placeholders:** iCloud Drive, OneDrive, Dropbox, Google Drive, and similar placeholder or streamed files; inspecting or "freeing" them can force a re-download or data loss.
- **Backups:** Time Machine backups, backup destinations, restore points, and recovery partitions.
- **Anything unverified or ambiguous:** an unknown folder, an unfamiliar large file, a cache whose owner cannot be identified, or an item the user did not clearly consent to remove. Exclude when unsure.

## 3. Double-Counting, Links, Sparse Files & Cloud

Report each reclaimable byte exactly once:

- **Parent/child overlap:** never count a parent and a child together. If `~/Library/Caches` is reported, drop its subfolders; if a deep child is the real candidate, report the child and drop the parent. Keep the largest safe item only.
- **Symlinks and APFS firmlinks:** use `du -x` (or the Windows equivalent that does not follow reparse points) and never follow symlinks. The macOS data/system firmlinks and any symlinked cache aliases can otherwise make one folder appear twice; collapse repeated real paths and report a firmlink target once.
- **Hard links and filesystem clones:** on-disk block counts already share blocks for clones, but hard-linked files can be counted per name. Deduplicate by device and inode where the OS exposes it; never sum apparent sizes.
- **Sparse files and disk images:** use allocated blocks (`du`, `du -P` where supported), never apparent size. For containers and virtual machines, use the engine's own reclaimable figure (`docker system df`) rather than the sparse disk-image size.
- **Cloud placeholders:** inspect block metadata and sizes only. Never open, read, or download a placeholder to measure it; a "0-byte" or tiny placeholder is not reclaimable local space, and hydrating it would consume space instead.
- **Minimum reporting floor:** list items of at least 25 MB individually. When fewer than five items reach 25 MB, lower the floor to 1 MB so the report is still useful. Never pad the list below the floor.
- **Sorting:** after deduplication and filtering, sort strictly descending by space freed, largest to smallest.
- **Volatile files:** re-check that each reported path still exists before presenting it; silently drop anything that vanished during the scan.

## 4. Plain-Language Translation

The report must be readable by someone who does not know systems jargon. Translate each item into three parts:

| Part | Write it like this | Avoid |
| --- | --- | --- |
| **What to delete** | The recognizable name and its location, e.g. "Chrome's saved web page cache" | Raw paths alone, checksums, inode numbers |
| **What it is** | One plain sentence: "Temporary copies of web pages Chrome keeps to load sites faster; Chrome rebuilds them automatically." | "Blob store", "inode", "CoW clone", "LRU eviction" |
| **Space freed** | A human size: "1.4 GB" | Byte counts, `du` output columns |

Terms to translate:

- "cache" → "temporary copies an app keeps to run faster; it recreates them automatically".
- "build artifacts" / "DerivedData" → "leftover files from building software; the next build recreates them".
- "dangling images" → "old container images nothing is using".
- "local snapshot" → "a temporary restore point the system keeps on this disk".
- "log" → "a record of past activity the app no longer needs".
- "recycle bin" / "trash" → "files you already deleted that still take up space until the bin is emptied".

Keep the list compact: one item per block, largest first, with the three parts clearly labeled. Do not add technical asides or command output.
