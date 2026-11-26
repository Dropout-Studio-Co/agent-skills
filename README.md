# ds-agent-skills

A collection of 9 Dropout Studio (`ds-*`) skills for AI coding assistants (like Claude Code and OpenCode). Each skill works across web, mobile, native, desktop, TV, CLI, and backend projects — teaching your AI assistant how to handle a specific job from start to finish.

> This is a personal workflow collection shared as-is, not a commercial product.

## Setup (1 Step)

Open your AI coding assistant and paste this prompt to install or update the skills:

```text
Install or update all skills from https://github.com/Dropout-Studio-Co/ds-agent-skills onto my computer. Resolve paths for this OS rather than assuming `~` expands: the target skills directory is `~/.agents/skills/` on macOS/Linux or `C:\Users\<you>\.agents\skills\` on Windows (one folder per skill, all siblings).

1. Clone https://github.com/Dropout-Studio-Co/ds-agent-skills to a temporary folder.
2. List every skill folder inside `skills/` in the cloned repository (derive the list from `skills/` — do not assume a fixed count).
3. For each skill folder, check whether `<skills-dir>/<skill-name>/` already exists (creating `<skills-dir>` if needed):
   - If missing, install it by copying the repository's skill folder into `<skills-dir>/<skill-name>/`.
   - If it already exists, replace the entire folder with the repository version (delete the existing folder first, then copy) so files deleted upstream do not survive. Existing local edits inside those skill folders will be lost.
4. Delete the temporary folder.
5. Verify that every skill folder from `skills/` exists in `<skills-dir>` and is non-empty.
6. Optional (Claude Code): if the `.claude` folder exists in my home directory (`~/.claude` on macOS/Linux, `C:\Users\<you>\.claude` on Windows), create or update a symlink at `<claude-dir>/skills/<skill-name>` pointing to `<skills-dir>/<skill-name>` for each individual skill folder — never symlink the whole `skills` directory. On Windows, symlinks require Developer Mode or an elevated shell; report if symlink creation fails instead of failing silently.
7. Check that `git` and `python3` (3.9 or newer) are installed, and report anything missing instead of failing silently.
8. Report one line per skill from `skills/` as `installed`, `updated`, or `failed` (with the reason).
```

That's it. Paste the same prompt anytime to install missing skills or refresh existing ones — your AI assistant will replace each skill folder with the latest version and report the result per skill.

## Included Skills

Once installed, type the phrase in the right column whenever you want to use a skill. Skills are grouped by what they do.

### Workflow & Sessions

| Skill | What it does | What to type |
| --- | --- | --- |
| [`ds-dev-protocol`](skills/ds-dev-protocol/) | Runs a strict step-by-step plan, build, review, and merge workflow for coding tasks in T3 Code (Antigravity, Claude and OpenCode providers), with OpenCode for the implementer. | Runs automatically |
| [`ds-handoff`](skills/ds-handoff/) | Produces a copyable session handoff (no args) or hands off and continues in a fresh session with a next-step directive (with args). | `/ds-handoff` or `/ds-handoff <next task>` (or `Safe Switch` when routed) |
| [`ds-consolidate`](skills/ds-consolidate/) | Gathers unfinished work from all branches, copies, worktrees, stashes, and pull requests into the default branch, verifies everything is safe, and cleans up leftovers. | `consolidate` or `/ds-consolidate` |

### UI & Design

| Skill | What it does | What to type |
| --- | --- | --- |
| [`ds-ui-overhaul`](skills/ds-ui-overhaul/) | Reviews and improves your app's UI, UX, layout, accessibility, and motion across web, mobile, native, desktop, and TV platforms. | `Run ds-ui-overhaul.` |
| [`ds-responsive`](skills/ds-responsive/) | Builds adaptive, responsive layouts, text scaling, input support, and accessibility across web, mobile, native, desktop, and TV screens. | `Use ds-responsive.` |

### Maintenance & Docs

| Skill | What it does | What to type |
| --- | --- | --- |
| [`ds-deps-upgrade`](skills/ds-deps-upgrade/) | Safely updates your project's packages from start to finish across web, mobile, desktop, TV, and backend ecosystems — checks compatibility, updates code, runs tests, and prepares the change. | `/ds-deps-upgrade` |
| [`ds-agent-docs`](skills/ds-agent-docs/) | Reviews and updates your project's AI instruction files (`AGENTS.md`, `CLAUDE.md`, and docs) so they stay accurate. | `/ds-agent-docs` |

### Media & Utilities

| Skill | What it does | What to type |
| --- | --- | --- |
| [`ds-media-cleanup`](skills/ds-media-cleanup/) | Cleans up movie and TV libraries — standardizes movie, TV show, and episode filenames (and season folders), infers your library's naming style, and flags duplicates with quality-to-size keep/remove recommendations without deleting files. | `/ds-media-cleanup` or `/ds-media-cleanup <path or drive>` |
| [`ds-storage-audit`](skills/ds-storage-audit/) | Audits your computer's storage — finds what is safe to remove, explains what each item is, and reports how much each one frees plus the total reclaimable space, without deleting anything. | `/ds-storage-audit` or `/ds-storage-audit <path or drive>` |

### Good to Know

- **Updating packages:** `ds-deps-upgrade` only makes changes when you ask for it by name (`/ds-deps-upgrade`). If you casually ask to "update my dependencies," it will only show you a plan. You can also run `/ds-deps-upgrade plan` anytime to preview changes first.
- **Using `ds-dev-protocol`:** All other skills work with whichever AI assistant you already use. `ds-dev-protocol` is the only one that needs extra tools signed in on your computer: T3 Code (Antigravity, Claude and OpenCode providers; gates run as T3 `delegate_task` children), GitHub CLI (`gh`) for pull requests and checks, and OpenCode (`opencode`) for the implementer route. If you don't use those, you can ignore or remove the `ds-dev-protocol` folder.

## License

MIT — see [LICENSE](./LICENSE).
