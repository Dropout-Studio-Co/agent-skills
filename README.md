# agent-skills

A personal collection of 7 ready-made skills for AI coding assistants (like Claude Code and OpenCode). Each skill teaches your AI assistant how to handle a specific job from start to finish — like cleaning up unfinished work, upgrading dependencies, or improving a website's design.

> This is a personal workflow collection shared as-is, not a commercial product.

## Setup (1 Step)

Open your AI coding assistant and paste this prompt:

```text
Install all skills from https://github.com/beyourahi/agent-skills onto my computer:

1. Download or clone the repository to a temporary folder, copy every folder inside `skills/` into `~/.agents/skills/` (keep all skill folders together in that same directory), and remove the temporary folder when done.
2. If I use Claude Code (or `~/.claude` exists), create a symlink in `~/.claude/skills/<skill-name>` pointing to `~/.agents/skills/<skill-name>` for each individual skill folder — do not symlink the whole `skills` directory.
3. Check that `git` and `python3` (3.9 or newer) are installed, and tell me if anything is missing.
4. Confirm when all 7 skills are installed and ready to use.
```

That's it. Your AI assistant will download the files, put them in the right folders, and let you know when everything is ready.

## Included Skills

Once installed, type the phrase in the right column whenever you want to use a skill.

| Skill | What it does | What to type |
| --- | --- | --- |
| [`consolidate`](skills/consolidate/) | Gathers unfinished work from all branches, copies, and pull requests into `main`, verifies everything is safe, and cleans up leftovers. | `consolidate` |
| [`dependency-upgrade`](skills/dependency-upgrade/) | Safely updates your project's packages from start to finish — checks compatibility, updates code, runs tests, and prepares the change. | `/dependency-upgrade` |
| [`execution-protocol`](skills/execution-protocol/) | Runs a strict step-by-step plan, build, review, and merge workflow for coding tasks using Claude Code and OpenCode. | Runs automatically |
| [`frontend-ui-ux-overhaul`](skills/frontend-ui-ux-overhaul/) | Reviews your website or app's design, layout, accessibility, and motion, then applies the improvements. | `Run frontend-ui-ux-overhaul.` |
| [`intrinsic-responsive-ui`](skills/intrinsic-responsive-ui/) | Helps build layouts that adapt smoothly to any screen size, font size, or device. | `Use intrinsic-responsive-ui.` |
| [`safe-switch`](skills/safe-switch/) | Saves your current progress and hands it cleanly to a new chat session without losing context. | `Safe Switch` |
| [`sync-agent-instructions`](skills/sync-agent-instructions/) | Reviews and updates your project's AI instruction files (`AGENTS.md`, `CLAUDE.md`, and docs) so they stay accurate. | `/sync-agent-instructions` |

### Good to Know

- **Updating packages:** `dependency-upgrade` only makes changes when you ask for it by name (`/dependency-upgrade`). If you casually ask to "update my dependencies," it will only show you a plan. You can also run `/dependency-upgrade plan` anytime to preview changes first.
- **Using `execution-protocol`:** All other skills work with whichever AI assistant you already use. `execution-protocol` is the only one that needs extra tools signed in on your computer: Claude Code (`claude`), GitHub CLI (`gh`), and OpenCode (`opencode`). If you don't use those, you can ignore or remove the `execution-protocol` folder.

## License

MIT — see [LICENSE](./LICENSE).
