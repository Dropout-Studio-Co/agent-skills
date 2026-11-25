---
name: ds-media-cleanup
description: Clean up movie and TV libraries — standardize movie, TV show, and episode filenames (and season folders), detect duplicates with quality-to-size keep/remove recommendations, and report concisely. Use when asked to clean up, rename, organize, or deduplicate downloaded movies or TV series in the current directory or a specified drive/path.
argument-hint: "Optional: target directory, drive, or volume path (defaults to current working directory)"
license: MIT
---

# Media Cleanup (`ds-media-cleanup`)

Clean and standardize movie, TV show, and episode filenames (and folder layout where appropriate), flag duplicates without deleting them, and return a strictly concise, jargon-free summary.

Consult [`references/naming-and-jargon.md`](references/naming-and-jargon.md) for release-tag stripping rules, cross-OS character sanitization, sidecar subtitle pairing, and the duplicate quality-to-size rubric.

## 1. Resolve and Validate Target

- **Target path:** Use the directory, drive, or volume passed as an argument; when omitted, use the current working directory.
- **Accept flexible inputs:** Full paths, relative paths, drive letters, or mounted volume names (resolve dynamically from the current OS — never assume a hardcoded mount point or drive letter).
- **Preflight check:** Verify the target exists, is readable, and is writable. If missing, unmounted, read-only, or containing no video files, stop immediately and return a single-line plain-language failure message.
- **Media scope:** When pointed at a drive or volume root, locate the movie/TV library folder(s) rather than walking the entire drive. Touch only movie and TV video files (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`, `.ts`, `.wmv`) and their matching sidecar files (`.srt`, `.ass`, `.ssa`, `.sub`, `.idx`, `.vtt`, `.nfo`, artwork). Skip OS/metadata entries (`._*`, `.DS_Store`, `$RECYCLE.BIN`, `.Trashes`, `.Spotlight-V100`, `System Volume Information`), backup folders, and non-library video folders (such as camera exports or personal project footage).

## 2. Infer Target Naming Convention

Establish the naming structure before renaming any file:

1. **Inspect existing library files:** Scan already-clean movies, TV show folders, season folders, and episode filenames in the target path to infer the dominant convention:
   - Movie layout (flat in media root vs. per-movie folder) and pattern (e.g., `<Title> - <YYYY>.<ext>` vs. `<Title> (<YYYY>).<ext>`).
   - TV layout (`<Show Name> (<YYYY>)/Season <NN>/` vs. flat show folder).
   - Episode pattern (e.g., `<Show Name> - s01e01 - <Episode Title>.<ext>` vs. `<Show Name> - S01E01.<ext>`, season/episode casing, and whether episode titles are kept — when mixed, preserve titles where present and omit where absent).
2. **Optional memory check:** If a local mind palace or personal notes repository is already accessible in the environment, check it for any recorded media-naming preference. Skip silently and never block, fetch remotely, or fail if local files or GitHub/network access are missing or unavailable — the skill must work fully standalone.
3. **Universal fallback:** When no existing convention is present (for example, a folder containing only raw downloads), default to:
   - **Movies:** `<Title> (<YYYY>).<ext>`
   - **TV shows:** `<Show Name> (<YYYY>)/Season <NN>/<Show Name> - S<NN>E<NN> - <Episode Title>.<ext>` (omit ` - <Episode Title>` when no episode title is available).

An inferred library convention or recorded user preference always wins over the fallback default. If both exist and differ, follow the target library's clearly established convention unless the user specifies otherwise.

## 3. Detect Duplicates Before Renaming

- Group all discovered video files by canonical identity (normalized title + year for movies; normalized show + season + episode for TV) before running any renames.
- **Never delete duplicates automatically.**
- **Prevent collisions:** When two or more files represent the same movie or episode, keep every copy intact and never overwrite one with another. Rename non-colliding files normally; for a duplicate set, either keep the colliding files untouched or disambiguate them safely without losing any file, then report the set in Step 5.
- Compare each duplicate set using file size and inspectable quality signals (resolution, codec efficiency, bitrate/size ratio, audio/subtitle completeness via filename cues or `ffprobe` if installed). Recommend the file that gives the **best reasonable balance between good quality and small file size** — avoid keeping an unnecessarily huge file when a much smaller file delivers solid quality, and avoid keeping a visibly low-quality rip when a reasonably sized clean copy exists.

## 4. Rename and Organize Safely

- Strip release jargon (resolution, source, codec, HDR, audio, streaming tags, release groups, site prefixes) and replace dot/underscore word separators with clean spaces per [`references/naming-and-jargon.md`](references/naming-and-jargon.md).
- Preserve legitimate title numbers, years inside titles (e.g., `Blade Runner 2049`), and multi-episode ranges (e.g., `S01E01-E02`).
- Sanitize filenames for cross-OS compatibility (remove or replace `: * ? " < > |`, trim trailing dots/spaces).
- Move or rename paired sidecar subtitles and metadata alongside their video file, preserving language/forced suffixes (e.g., `.en.srt`, `.en.forced.srt`).
- **Leave already-clean files untouched:** Rename or move only files that violate the inferred structure (release jargon, missing `Season <NN>` folder, wrong `sXXeYY`/`SXXEYY` casing, or illegal OS characters); skip minor stylistic nitpicks (article casing, apostrophes, subtitle separators) on already-conforming filenames.
- Execute non-clobbering renames only (check destination absence before moving; handle case-only renames on case-insensitive filesystems via a two-step temporary name). Remove empty download-release wrapper folders only if they contained solely the moved media/sidecars and no other user files.
- **Completion criterion:** Every non-colliding movie and TV episode in scope matches the target convention, every sidecar stays paired, and zero files were overwritten or deleted.

## 5. Output Contract (Strictly Concise, Jargon-Free)

Keep output short, plain-language, and free of technical jargon (avoid codec/container/filesystem dumps unless a single plain word like `1080p` or `4K` clarifies a duplicate choice):

- **Success (no duplicates):** Return **one single line** confirming everything is done, with no extra explanation, file list, or recap.
  - Example: `Done — all movies and TV episodes are renamed and organized.`
- **Failure:** Return **one single line** explaining what went wrong in plain language, with no stack traces or technical jargon.
  - Example: `Couldn't rename the files because the drive is read-only.`
- **Duplicates found:** Start with the single-line status, then list each duplicate set in a compact comparison with a clear **Keep** and **Remove** recommendation based on quality-to-size balance:

```text
Done — renamed everything and found 1 duplicate to review (nothing was deleted).

- Inception (2010)
  - Keep: Inception - 2010.mkv (2.4 GB, crisp 1080p — best quality for the size)
  - Remove: Inception.2010.2160p.REMUX.mkv (48 GB, much larger than needed)
```
