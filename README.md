# agent-skills

A collection of 8 Dropout Studio (`ds-*`) skills for AI coding assistants (like Claude Code and OpenCode). Each skill works across web, mobile, native, desktop, TV, CLI, and backend projects — teaching your AI assistant how to handle a specific job from start to finish.

> This is a personal workflow collection shared as-is, not a commercial product.

## Setup (1 Step)

Open your AI coding assistant and paste this prompt:

```text
Install all skills from https://github.com/Dropout-Studio-Co/agent-skills onto my computer:

1. Download or clone the repository to a temporary folder, copy every folder inside `skills/` into `~/.agents/skills/` (keep all skill folders together in that same directory), and remove the temporary folder when done.
2. If I use Claude Code (or `~/.claude` exists), create a symlink in `~/.claude/skills/<skill-name>` pointing to `~/.agents/skills/<skill-name>` for each individual skill folder — do not symlink the whole `skills` directory.
3. Check that `git` and `python3` (3.9 or newer) are installed, and tell me if anything is missing.
4. Confirm when all 8 skills are installed and ready to use.
```

That's it. Your AI assistant will download the files, put them in the right folders, and let you know when everything is ready.

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
| [`ds-media-rename`](skills/ds-media-rename/) | Cleans and standardizes movie, TV show, and episode filenames (and season folders), infers your library's naming style, and flags duplicates with quality-to-size keep/remove recommendations without deleting files. | `/ds-media-rename` or `/ds-media-rename <path or drive>` |

### Good to Know

- **Updating packages:** `ds-deps-upgrade` only makes changes when you ask for it by name (`/ds-deps-upgrade`). If you casually ask to "update my dependencies," it will only show you a plan. You can also run `/ds-deps-upgrade plan` anytime to preview changes first.
- **Using `ds-dev-protocol`:** All other skills work with whichever AI assistant you already use. `ds-dev-protocol` is the only one that needs extra tools signed in on your computer: T3 Code (Antigravity, Claude and OpenCode providers; gates run as T3 `delegate_task` children), GitHub CLI (`gh`) for pull requests and checks, and OpenCode (`opencode`) for the implementer route. If you don't use those, you can ignore or remove the `ds-dev-protocol` folder.

## License

MIT — see [LICENSE](./LICENSE).
