# OS Locations & Read-Only Probes

Reference for [`SKILL.md`](../SKILL.md). Use only the section for the detected host OS. Every command here inspects sizes and names only; none of them deletes, moves, or writes anything. Prefer `du`/`Get-ChildItem` block measurements over apparent file sizes.

Always quote paths, put `--` before a path that starts with a dash, and never evaluate or unquoted-expand a discovered name. Skip any location that does not exist, and skip any tool that is not installed.

Every Pass B probe stays on one filesystem (`-x` / `-xdev`) and caps depth (`-d 3` or `max-depth=3`) so a whole-disk sweep stays bounded.

## 1. Detect the Host OS and Volumes

- **macOS:** `sw_vers` and `uname -s` report macOS/Darwin.
- **Linux:** `uname -s` reports Linux; `/etc/os-release` names the distribution.
- **Windows:** `$PSVersionTable` plus `Get-CimInstance Win32_OperatingSystem` in PowerShell.
- **WSL:** `uname -s` reports Linux while `WSL_DISTRO_NAME` is set and `%USERPROFILE%` is reachable from Windows; treat it as Linux inside the distro plus a Windows-side pass.
- **Volumes:** macOS/Linux `df -h` (exclude `tmpfs`, `devtmpfs`, `proc`, `sysfs`, `squashfs`, and network/FUSE mounts); Windows `Get-Volume` and `Get-PSDrive -PSProvider FileSystem`.

## 2. macOS (`~` is `$HOME`, never a literal home path)

**Pass A — known cleanup locations**

**System, user, and installer leftovers**
- `~/Library/Caches/` — per-app caches (largest subfolders first).
- `/Library/Caches/` — system-wide app caches (may be permission-restricted).
- `~/.Trash/` and `/Volumes/*/.Trashes/` — trash on mounted local volumes; recommend emptying only, never empty it.
- `~/Library/Logs/`, `/Library/Logs/`, `/private/var/log/` — application and system logs.
- `~/Library/Application Support/CrashReporter/`, `~/Library/Logs/DiagnosticReports/`, `/Library/Logs/DiagnosticReports/` — crash reports.
- `~/Library/Containers/*/Data/Library/Caches/` — sandboxed app caches.
- `~/Downloads/` — identify leftover installers by extension `.dmg`, `.pkg`, `.iso`, `.mpkg`, `.zip` only when the name clearly shows a setup installer.
- `tmutil listlocalsnapshots /` and `tmutil listlocalsnapshots /System/Volumes/Data` — Time Machine local snapshots (list only; recommend thinning, never thin or delete).
- `/Library/Updates/`, `~/Library/Caches/com.apple.*/` — downloaded system/update caches.
- `/private/var/vm/` — sleep image and swap files; **never recommend removing these**.

**Browsers — cache folders only, never profiles, cookies, history, bookmarks, or passwords**
- Safari: `~/Library/Caches/com.apple.Safari/`.
- Chrome/Chromium/Edge/Brave: `~/Library/Caches/Google/Chrome/`, `~/Library/Caches/Chromium/`, `~/Library/Caches/Microsoft Edge/`, `~/Library/Caches/BraveSoftware/`.
- Firefox: `~/Library/Caches/Firefox/`.

**Apps (caches only)**
- Electron and messaging: `~/Library/Caches/Slack/`, `~/Library/Caches/discord/`, `~/Library/Caches/Microsoft Teams/`, `~/Library/Caches/com.microsoft.teams2/`, `~/Library/Caches/zoom.us/`.
- Media and editing: `~/Library/Caches/Spotify/`, `~/Library/Caches/com.apple.Music/`, `~/Library/Caches/com.apple.Photos/` (cache only), Adobe media cache folders under `~/Library/Caches/Adobe/`.

**Developer, SDK, and package caches**
- Xcode: `~/Library/Developer/Xcode/DerivedData/`, `~/Library/Developer/Xcode/iOS DeviceSupport/`, `~/Library/Developer/Xcode/watchOS DeviceSupport/`, `~/Library/Developer/CoreSimulator/Caches/`, `~/Library/Developer/CoreSimulator/Devices/` (only unavailable simulators the user confirms are stale).
- Swift/Clang: `~/Library/Caches/org.swift.swiftpm/`, `~/Library/Caches/clang/`.
- Homebrew: `brew --cache` (inspect the returned cache folder), `~/Library/Caches/Homebrew/`.
- Node and JS: npm cache at `~/.npm/_cacache/`, pnpm store at `~/.pnpm-store/`, yarn cache at `~/.cache/yarn/`, bun cache at `~/.bun/install/cache/`, deno cache at `~/Library/Caches/deno/`, Playwright browsers at `~/Library/Caches/ms-playwright/`, Cypress cache at `~/Library/Caches/Cypress/`.
- Python: `~/Library/Caches/pip/`, `~/Library/Caches/uv/`, `~/Library/Caches/pypoetry/`, `~/Library/Caches/conda/`, `~/miniconda3/pkgs/` or `~/anaconda3/pkgs/` (package cache only).
- Rust, Go, and JVM: Cargo registry cache at `~/.cargo/registry/cache/`, Go build cache at `~/Library/Caches/go-build/`, Gradle caches at `~/.gradle/caches/`, Maven local repository cache at `~/.m2/repository/`, JetBrains caches at `~/Library/Caches/JetBrains/`.
- Containers: `docker system df` for reclaimable build cache and dangling images (report the reclaimable figure, never the sparse disk-image size); `podman system df` when Podman is present. **Never recommend Docker.raw or any active volume.**
- AI and ML: `~/.cache/huggingface/`, `~/Library/Caches/huggingface/`, `~/.cache/torch/`, `~/.ollama/models/` (only clearly unused model downloads).

**Pass B probe (bounded)**
- `du -x -d 3 / 2>/dev/null | sort -n | tail -n 40` — top directories on one filesystem.
- `du -x -d 3 "$HOME" 2>/dev/null | sort -n | tail -n 40` — top home directories.
- `find "$HOME/Downloads" -maxdepth 1 -type f -size +25M -print` — large downloads to classify.

## 3. Linux (including WSL inside the distro)

**Pass A — known cleanup locations**

**System, user, and installer leftovers**
- `/var/cache/apt/archives/`, `/var/lib/apt/lists/` — Debian/Ubuntu package and index caches.
- `/var/cache/dnf/`, `/var/cache/yum/` — Fedora/RHEL package caches.
- `/var/cache/pacman/pkg/` — Arch package cache.
- `/var/lib/flatpak/repo/tmp/`, `~/.cache/flatpak/` — Flatpak cache and temporary objects (never remove installed applications).
- `/var/lib/snapd/cache/`, `~/.cache/snapd/` — snap download cache.
- `/var/log/`, `~/.cache/` logs, `/var/crash/`, `/var/lib/systemd/coredump/` — logs and crash dumps.
- `journalctl --disk-usage` — systemd journal size (inspect only; recommend vacuuming to the user, never run it).
- `~/.local/share/Trash/`, `/root/.local/share/Trash/` (permission-restricted) — trash; recommend emptying only.
- `/tmp/`, `/var/tmp/` — temporary files older than the current session.
- `/var/cache/` other packager caches, `/var/tmp/flatpak-cache-*`.
- `~/Downloads/` — leftover installers by extension `.deb`, `.rpm`, `.iso`, `.AppImage`, `.run`, `.tar.gz` only when clearly a setup installer.

**Browsers — cache folders only, never profiles, cookies, history, bookmarks, or passwords**
- Chrome/Chromium/Edge/Brave: `~/.cache/google-chrome/`, `~/.cache/chromium/`, `~/.cache/microsoft-edge/`, `~/.cache/BraveSoftware/`.
- Firefox: `~/.cache/mozilla/firefox/`.

**Apps (caches only)**
- Electron and messaging: `~/.config/Slack/Cache/`, `~/.config/discord/Cache/`, `~/.config/Code/Cache/`, `~/.config/Code/CachedData/`.
- Media: `~/.cache/spotify/`, `~/.cache/thumbnails/`.

**Developer, SDK, and package caches**
- JS: `~/.npm/_cacache/`, `~/.pnpm-store/`, `~/.cache/yarn/`, `~/.bun/install/cache/`, `~/.cache/deno/`, `~/.cache/ms-playwright/`, `~/.cache/Cypress/`.
- Python: `~/.cache/pip/`, `~/.cache/uv/`, `~/.cache/pypoetry/`, `~/.cache/conda/`, `~/miniconda3/pkgs/`.
- Native and JVM: `~/.cargo/registry/cache/`, `~/.cache/go-build/`, `~/.gradle/caches/`, `~/.m2/repository/` (cache only), `~/.cache/JetBrains/`.
- Android: `~/.android/cache/`, `~/.gradle/`, `~/Android/Sdk/.temp/`, `~/Android/Sdk/system-images/` (only unused images the user confirms).
- Containers: `docker system df` for reclaimable build cache and dangling images; `podman system df` when Podman is present. **Never recommend an active volume or the raw storage file.**
- AI and ML: `~/.cache/huggingface/`, `~/.cache/torch/`, `~/.ollama/models/` (only clearly unused model downloads).

**Pass B probe (bounded)**
- `du -x -d 3 / 2>/dev/null | sort -n | tail -n 40`.
- `du -x -d 3 "$HOME" 2>/dev/null | sort -n | tail -n 40`.
- `find / -xdev -maxdepth 3 -type f -size +500M -print 2>/dev/null | head -n 40`.

## 4. Windows (PowerShell; use `%USERPROFILE%`, `%LOCALAPPDATA%`, `%APPDATA%`, `%TEMP%`)

**Pass A — known cleanup locations**

**System, user, and installer leftovers**
- `$env:TEMP` and `$env:LOCALAPPDATA\Temp` — user temporary files.
- `C:\Windows\Temp\` — system temporary files (may be permission-restricted).
- `C:\$Recycle.Bin\` — Recycle Bin; recommend emptying only, never empty it.
- `C:\Windows.old\` — previous Windows installation (safe only after the upgrade window has passed; recommend the built-in cleanup, never delete manually).
- `C:\Windows\SoftwareDistribution\Download\` — Windows Update download cache.
- `C:\Windows\Logs\`, `%LOCALAPPDATA%\CrashDumps\` — logs and crash dumps.
- `%USERPROFILE%\Downloads\` — leftover installers by extension `.msi`, `.exe`, `.iso`, `.msix`, `.zip` only when clearly a setup installer.
- `C:\hiberfil.sys`, `C:\pagefile.sys`, `C:\swapfile.sys` — **never recommend removing these**; offer the supported settings path instead.
- `Get-Volume` — free/total per local volume; `Get-ChildItem -Directory | Measure-Object -Property Length -Sum` sizes folders.

**Browsers — cache folders only, never profiles, cookies, history, bookmarks, or passwords**
- Chrome/Chromium/Edge/Brave: `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache\`, `%LOCALAPPDATA%\Chromium\User Data\Default\Cache\`, `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache\`, `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Cache\`.
- Firefox: `%LOCALAPPDATA%\Mozilla\Firefox\Profiles\*\cache2\`.

**Apps (caches only)**
- Electron and messaging: `%APPDATA%\Slack\Cache\`, `%APPDATA%\discord\Cache\`, `%APPDATA%\Microsoft\Teams\Cache\`, `%LOCALAPPDATA%\Microsoft\Teams\`.
- Media: `%LOCALAPPDATA%\Spotify\Data\`, `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db`.

**Developer, SDK, and package caches**
- JS: `%LOCALAPPDATA%\npm-cache\`, `%LOCALAPPDATA%\pnpm-store\`, `%LOCALAPPDATA%\Yarn\Cache\`, `%USERPROFILE%\.bun\install\cache\`, `%LOCALAPPDATA%\deno\`, `%LOCALAPPDATA%\ms-playwright\`, `%LOCALAPPDATA%\Cypress\Cache\`.
- Xcode is not applicable; Apple tooling runs only on macOS.
- Python: `%LOCALAPPDATA%\pip\Cache\`, `%LOCALAPPDATA%\uv\cache\`, `%LOCALAPPDATA%\pypoetry\Cache\`, `%USERPROFILE%\miniconda3\pkgs\`.
- Native and JVM: `%USERPROFILE%\.cargo\registry\cache\`, `%LOCALAPPDATA%\go-build\`, `%USERPROFILE%\.gradle\caches\`, `%USERPROFILE%\.m2\repository\` (cache only), `%LOCALAPPDATA%\JetBrains\`.
- Android: `%USERPROFILE%\.android\cache\`, `%USERPROFILE%\.gradle\`, `%LOCALAPPDATA%\Android\Sdk\.temp\`.
- Containers: `docker system df` for reclaimable build cache and dangling images; `podman system df` when Podman is present. **Never recommend an active volume or the virtual disk file.**
- AI and ML: `%USERPROFILE%\.cache\huggingface\`, `%USERPROFILE%\.cache\torch\`, `%USERPROFILE%\.ollama\models\` (only clearly unused model downloads).

**Pass B probe (bounded)**
- `Get-ChildItem -Path C:\ -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object { [PSCustomObject]@{ Path = $_.FullName; GB = [math]::Round((Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1GB, 1) } } | Sort-Object GB -Descending | Select-Object -First 20`.
- `Get-ChildItem -Path $env:USERPROFILE -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object { [PSCustomObject]@{ Path = $_.FullName; GB = [math]::Round((Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1GB, 1) } } | Sort-Object GB -Descending | Select-Object -First 20`.

## 5. WSL and Secondary Local Volumes

- **WSL:** run the Linux section inside the distro for caches, Package manager caches, logs, and trash; the distro's `ext4.vhdx` is **never** a safe recommendation. On the Windows side, check `%TEMP%`, `%LOCALAPPDATA%\Temp`, browser caches, Package manager caches, and `%USERPROFILE%\Downloads\` installers.
- **Secondary or external local volumes:** mount read-only if possible, then run a bounded Pass B rooted at the mount (`du -x -d 3 <mount>`, `-x` keeps the scan on that volume). Include only local writable filesystems the user owns; never scan network shares, cloud mounts, or FUSE filesystems unless explicitly targeted.
- **Time Machine / backup destinations:** list sizes only. Never recommend removing a backup volume's contents.
