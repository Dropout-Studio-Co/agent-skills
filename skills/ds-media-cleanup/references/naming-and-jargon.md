# Naming, Release Jargon & Duplicate Rubric

Reference for [`SKILL.md`](../SKILL.md). Consult when parsing messy release filenames, pairing sidecars, sanitizing characters, or comparing duplicate copies.

## 1. Release Jargon to Strip

Remove technical release tokens once title, year, and season/episode markers are extracted:

- **Resolution:** `480p`, `576p`, `720p`, `1080p`, `1080i`, `2160p`, `4K`, `UHD`, `SD`
- **Source / rip type:** `WEB-DL`, `WEBRip`, `WEB`, `BluRay`, `BDRip`, `BRRip`, `REMUX`, `HDRip`, `DVDRip`, `HDTV`, `PDTV`, `CAM`, `TS`, `HDCAM`, `AMZN`, `NF`, `DSNP`, `ATVP`, `HMAX`, `MAX`, `PMTP`, `STAN`, `IT` (strip short service tags like `MAX` or `IT` only in the release-tag segment after the year or episode code, never inside the title itself)
- **Video codec / HDR:** `x264`, `x265`, `H.264`, `H264`, `H.265`, `H265`, `HEVC`, `AV1`, `XviD`, `DivX`, `10bit`, `8bit`, `HDR`, `HDR10`, `HDR10+`, `DV`, `DoVi`, `Dolby Vision`, `SDR`, `HLG`, `Hybrid`, `PROPER`, `REPACK`, `INTERNAL`, `LIMITED`, `EXTENDED` (keep edition tags like `Director's Cut` or `Extended` only if two distinct editions are intentionally kept or the library convention keeps them)
- **Audio & subtitles:** `AAC`, `AAC2.0`, `AAC5.1`, `AC3`, `EAC3`, `DDP`, `DDP5.1`, `DD5.1`, `DTS`, `DTS-HD`, `DTS-HD.MA`, `TrueHD`, `Atmos`, `FLAC`, `Opus`, `MP3`, `2.0`, `5.1`, `7.1`, `2CH`, `6CH`, `8CH`, `Dual Audio`, `Multi`, `MSubs`, `ESub`, `Subbed`, and trailing language tags (`English`, `Hindi`, etc.) when appearing in the release-tag segment after the year or episode code.
- **Groups & wrappers:** Trailing `-GROUP`, spaced ` - Group`, or dotted `-Group.tld` tags (`-YTS`, `-RARBG`, `-PSA`, `-QxR`, `-NTb`, `-FLUX`, `-SPARKS`, `-TGx`, `-EVO`, `-MeGusta`, `-Pahe.in`, `-d3g`), bracketed tags (`[YTS.MX]`, `[1080p]`, `[PSA]`, `[TGx]`, `[Telly]`), and site prefixes (`www.SiteName.com - `).

## 2. Parsing Edge Cases

- **Numbers in titles:** Do not treat a year that is part of the title as the release year when a later 4-digit release year is present (e.g., `Blade.Runner.2049.2017.1080p.mkv` → title `Blade Runner 2049`, year `2017`; `1917.2019.1080p.mkv` → title `1917`, year `2019`).
- **Season/episode formats:** Recognize `S01E02`, `s01e02`, `1x02`, `Season 1 Episode 2`, `E02` inside a `Season 01` folder, multi-episode files (`S01E01E02`, `S01E01-E02`), and specials (`S00E01`). Normalize to the inferred library pattern (zero-padded two-digit season and episode numbers).
- **Separators:** Convert `.` and `_` used as word separators into single spaces; preserve intentional punctuation inside titles (e.g., `What If...`, `Mr. Robot`, `Dr. Strangelove`, contractions like `Don't`).
- **Title casing:** Preserve standard title case and acronyms (`FBI`, `CIA`, `II`, `III`, `IV`, `MCU`).

## 3. Cross-OS Filename Sanitization

Ensure every renamed file and folder works cleanly across macOS, Windows, Linux, exFAT, and NTFS:

- Replace or remove illegal characters: `:`, `*`, `?`, `"`, `<`, `>`, `|`, `\`, `/` (within a single filename segment).
  - For colons in subtitles (e.g., `Alita: Battle Angel` or `Avengers: Endgame`), match the library's existing style (either omit the colon as `Avengers Endgame` or replace with ` - `).
- Strip leading/trailing whitespace and trailing periods (Windows/exFAT disallow trailing dots on filenames and folder names).
- Collapse repeated spaces into one space.
- On case-insensitive filesystems (macOS APFS default, Windows NTFS, exFAT), rename case-only changes in two steps (`old` → `old.__tmp_rename__` → `New`).

## 4. Sidecar & Companion Files

When renaming `<stem>.<video_ext>` to `<new_stem>.<video_ext>`:

- Rename matching sidecar files in the same folder that share `<stem>` (`.srt`, `.ass`, `.ssa`, `.sub`, `.idx`, `.vtt`, `.nfo`, `-poster.jpg`, `-fanart.jpg`).
- Preserve language and flag suffixes on subtitles:
  - `Movie.2024.1080p.en.srt` → `Movie - 2024.en.srt`
  - `Movie.2024.1080p.en.forced.srt` → `Movie - 2024.en.forced.srt`
- Ignore and never delete unrelated documents, archives, or non-media folders.

## 5. Duplicate Comparison Rubric (Quality-to-Size Balance)

When two or more files represent the same movie or episode, never delete either file. Compare them and recommend **Keep** vs. **Remove** using practical watchability per gigabyte:

1. **Prefer solid quality at a sensible size:** A clean 1080p encode (typically ~1.5–5 GB for a movie, ~300 MB–1.5 GB for an episode) usually beats a massive 30–70 GB remux for everyday portable playback.
2. **Avoid visibly degraded rips:** If one copy is a tiny CAM/TS/480p or heavily crushed sub-500 MB movie rip and the other is a clean 1.5–4 GB 1080p copy, recommend keeping the clean 1080p copy.
3. **Modern codecs win at equal clarity:** When both files look equally sharp (same resolution), prefer the smaller modern encode (e.g., HEVC/H.265 or AV1 over an oversized older H.264 file) unless compatibility notes say otherwise.
4. **Account for completeness:** If `ffprobe` or filenames show one copy has broken/missing audio or lacks needed subtitles while the other is complete, factor that into the recommendation.
5. **Explain in plain language:** In the final response, summarize each file using only size and a short plain-language quality cue (e.g., `2.4 GB, crisp 1080p` vs. `48 GB, oversized 4K copy`) — no raw `ffprobe` dumps or codec jargon.
