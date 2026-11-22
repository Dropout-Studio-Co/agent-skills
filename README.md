# agent-skills

My AI-agent skills, kept in one place: development, automation, code quality and workflow management.

Eight skills I use across coding harnesses. They live here so they survive a
reinstall, stay reviewable, and move to another machine in one copy. Each folder is a standard
Agent Skill: a `SKILL.md` plus the scripts, references and tests it needs. This is a personal
workflow repository, not a supported product.

## Skills

| Skill                                                        | What it does                                                                                                                                                                                         |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`consolidate`](skills/consolidate/)                         | Gets every unfinished branch, worktree, clone, stash and PR into `main`, verifies the result, then deletes only what is proven to be in main, after a restore point.                                  |
| [`dependency-upgrade`](skills/dependency-upgrade/)           | Upgrades a repository's dependencies end to end in an isolated worktree: research, plan, migrate, test, review, verify, deliver.                                                                     |
| [`execution-protocol`](skills/execution-protocol/)           | Applies an always-on protocol to every development task: Opus 5.5 conducts in Claude Code and plans/gates through `scripts/gate.sh`; DeepSeek V4.1 Flash High implements through `scripts/implement.sh` (Sonnet 5.5 High only as its fallback); merges go through `scripts/premerge-and-merge.sh`. |
| [`frontend-ui-ux-overhaul`](skills/frontend-ui-ux-overhaul/) | Audits and implements repository-wide frontend, responsive, accessibility, motion and design-system improvements.                                                                                    |
| [`intrinsic-responsive-ui`](skills/intrinsic-responsive-ui/) | Guides fluid, container-aware responsive layouts built on intrinsic sizing rather than breakpoint patches.                                                                                            |
| [`review-loop`](skills/review-loop/)                         | Runs an independent, evidence-backed review of a finished change before it lands, with risk tiers and a three-round cap.                                                                             |
| [`safe-switch`](skills/safe-switch/)                         | Captures verified task state and hands the current work off losslessly to a fresh session using the current harness, model and effort, on explicit request only.                                      |
| [`sync-agent-instructions`](skills/sync-agent-instructions/) | Audits and syncs a repository's cross-agent instructions, rules, skills, subagents and core docs in one unified workflow: full cross-agent audit plus evidence-backed, gated updates to `AGENTS.md` and `CLAUDE.md`. |

## Layout

```text
skills/
├── consolidate/               SKILL.md, task-profile.json
├── dependency-upgrade/        SKILL.md, README.md, scripts/, references/, tests/, admin/
├── execution-protocol/        SKILL.md, reference.md, opus-gate-brief.md, implementer-brief.md, plan-schema.json,
│                              review-schema.json, opencode/, scripts/ (gate.sh, implement.sh,
│                              implement_lib.py, premerge-and-merge.sh), tests/ (smoke.sh, implement-smoke.sh)
├── frontend-ui-ux-overhaul/   SKILL.md, task-profile.json
├── intrinsic-responsive-ui/   SKILL.md
├── review-loop/               SKILL.md
├── safe-switch/               SKILL.md
└── sync-agent-instructions/   SKILL.md, references/ (audit-rubric.md, agent-surfaces.md),
                               scripts/ (collect_sessions.py, check_instructions.py),
                               tests/ (collector, checker)
```

All skills except `execution-protocol` are model-agnostic and harness-agnostic: they use the
current session's harness, model and effort without switching or enforcing alternatives (when
`execution-protocol` is explicitly invoked alongside another skill, `execution-protocol`'s
routing and execution rules take precedence for the applicable tasks). `consolidate` and
`frontend-ui-ux-overhaul` share `dependency-upgrade/scripts/review_task.py` for fresh-context
task preparation, candidate binding and required-review gating, reading their prompt profiles
from `<skills-root>/<skill>/task-profile.json`. Keep those three folders (`dependency-upgrade`,
`consolidate`, `frontend-ui-ux-overhaul`) as siblings under one skills root.

## Install

Each harness discovers skills from a global root: `~/.agents/skills` for OpenCode and
`~/.claude/skills` for Claude Code. This repository mirrors that layout under `skills/`:

```sh
git clone https://github.com/beyourahi/agent-skills.git
cp -R agent-skills/skills/* ~/.agents/skills/
```

Claude Code reads only `~/.claude/skills`, so link each skill there once:

```sh
cd ~/.claude/skills
for s in consolidate dependency-upgrade execution-protocol frontend-ui-ux-overhaul intrinsic-responsive-ui review-loop safe-switch sync-agent-instructions; do
  [ -e "$s" ] || ln -s ../../.agents/skills/$s $s
done
```

`dependency-upgrade` also ships an idempotent installer for that link, with a doctor check:

```sh
python3 ~/.agents/skills/dependency-upgrade/admin/depup-admin.py install
python3 ~/.agents/skills/dependency-upgrade/admin/depup-admin.py doctor
```

Requirements: git and Python 3.9+. The `sync-agent-instructions` collector and checker are
stdlib-only; the checker stages, gates and applies memory-file edits and never commits or
pushes.
`execution-protocol` also needs the `claude` CLI (signed in), `gh` (signed in), the `opencode` CLI
(OpenCode Go, model `opencode-go/deepseek-v4.1-flash#high`) and `python3`;
`scripts/implement.sh` also needs `timeout` and `lsof`. It optionally uses `claude-swap`
(`cswap`), if installed, to rotate Opus gates between your signed-in Claude accounts when one runs
out of quota; without it the gates use the account `claude` is signed in with.

## Usage

| Skill                     | Invoke                                                                          |
| ------------------------- | ------------------------------------------------------------------------------- |
| `consolidate`             | `consolidate`                                                                   |
| `dependency-upgrade`      | `/dependency-upgrade [upgrade\|plan\|verify\|resume\|rollback\|status] [scope]` |
| `execution-protocol`      | Always on (part of every development task)                                      |
| `frontend-ui-ux-overhaul` | `Run frontend-ui-ux-overhaul.`                                                  |
| `intrinsic-responsive-ui` | `Use intrinsic-responsive-ui.`                                                  |
| `review-loop`             | `Review this change with review-loop.`                                          |
| `safe-switch`             | `Safe Switch`                                                                   |
| `sync-agent-instructions` | `sync AGENTS.md`                                                                |

`dependency-upgrade` runs only when named explicitly; a casual "update my dependencies" gets a
read-only plan instead. Details and harness notes are in its
[README](skills/dependency-upgrade/README.md).

## Tests

```sh
python3 -m unittest discover -s skills/dependency-upgrade/tests -t skills/dependency-upgrade
python3 -m unittest discover -s skills/sync-agent-instructions/tests -t skills/sync-agent-instructions
bash skills/execution-protocol/tests/smoke.sh
```

The `sync-agent-instructions` suite covers the collector (`scripts/collect_sessions.py`) and
the checker (`scripts/check_instructions.py`); the checker tests stage, gate and apply edits in
scratch repositories and never touch this checkout.

## License

MIT — see [LICENSE](./LICENSE).
