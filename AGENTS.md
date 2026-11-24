# agent-skills — notes for agents

Repository of Dropout Studio (`ds-*`) AI-agent skills. Each directory under `skills/` is an
installable Agent Skill; this repository is the source of truth, and `~/.agents/skills/<name>` is
kept in sync with `main` automatically (see [Automatic sync](#automatic-sync)).

## Commands

```sh
python3 -m unittest discover -s skills/ds-deps-upgrade/tests -t skills/ds-deps-upgrade  # ds-deps-upgrade + review_task tests
python3 -m unittest discover -s skills/ds-agent-docs/tests -t skills/ds-agent-docs  # collector + checker tests
bash skills/ds-dev-protocol/tests/smoke.sh  # ds-dev-protocol smoke tests (fake CLIs)
diff -rq -x __pycache__ -x graft skills/<name> ~/.agents/skills/<name>  # drift check: must print nothing
rsync -a --exclude '__pycache__/' --exclude 'graft/.cache/' skills/<name>/ ~/.agents/skills/<name>/  # sync one skill
~/.agents/bin/agent-skills-sync --dry-run  # sync: show what the next run would do, change nothing
```

`skills/ds-agent-docs/scripts/check_instructions.py` runs a read-only cross-agent instruction and
documentation audit (`audit --repo R [--scope P]`); it never modifies a repository.
`scripts/collect_sessions.py` collects and redacts session evidence. Both helpers are stdlib-only Python
3.9+, and their tests live under `skills/ds-agent-docs/tests/`.

Run the drift check from an up-to-date `main` before starting a change to a skill: it must print
nothing (any difference is local drift; bring it into the repository first). After the change is
merged, sync from the merged `main` with the rsync, then run the drift check again: it must print
nothing. A file deleted in the repository is removed from the installed copy by hand before that
final check. Files the sync never copies (for example `.agent-skills-sync` or `.DS_Store`) can show
up as `Only in ~/.agents/skills/<name>` and are expected; any other difference is drift.

## Automatic sync

- A LaunchAgent labelled `com.beyourahi.agent-skills-sync` starts the watcher
  `~/.agents/bin/agent-skills-watch` at login. The watcher runs `~/.agents/bin/agent-skills-sync` at
  start, on every change under `~/.agents/skills`, and when the network comes back; it can also be
  run by hand. There is no schedule. The sync keeps `~/.agents/skills` and `main` in step in both
  directions.
- Managed skills are every `skills/<name>` on `main`, plus a new real folder in `~/.agents/skills`
  that holds a `SKILL.md` whose frontmatter `name` equals the folder name, an empty
  `.agent-skills-sync` marker, and no entry in `~/.agents/.skill-lock.json`. Symlinked entries are
  ignored.
- Local edits, additions and deletions are committed and pushed straight to `main`, with the
  subjects `chore(sync): update <name> from local copy`, `feat(sync): add <name>` and
  `chore(sync): remove <name>`. A local change is pushed at once, with no wait. A whole-skill
  deletion is committed after an immediate confirmation pass that still finds the folder missing.
- Changes merged on `main` are installed in the local copy when that copy is unchanged since the
  last sync. They arrive at login, on the next local change, when the network comes back, or at once
  with `~/.agents/bin/agent-skills-sync`. A skill changed on both sides is held, with no write either
  way and one macOS notification, until both sides match. A skill removed from `main` is retired locally: the folder
  is kept and the skill is no longer synced.
- Never synced: `__pycache__/`, `*.pyc`, `.pytest_cache/`, any `graft/` folder, `.DS_Store`,
  `.agent-skills-sync`, `.git/`, `.local-state/`, `*.log`, `.env` and `.env.*` except
  `.env.example`, `.dev.vars`, and editor temp files (`*~`, `*.swp`, `*.swo`, `*.swx`, `*.tmp`,
  `.#*`, `4913`, `*___jb_tmp___*`, `*___jb_old___*`).
- A change that holds a home path, a token-like string, or a file over 5 MB is held and not pushed.
- State and logs live in `~/.local/state/agent-skills-sync/`: `runs.jsonl`, `state.json`,
  `launchd.log` and the sync's own clone in `repo/`.
- For agents: change a skill in this repository through a PR and never edit
  `~/.agents/skills/<name>` directly, because the sync pushes such an edit to `main` without
  review. After the merge, run `~/.agents/bin/agent-skills-sync` (or the rsync above) to install
  the change at once; otherwise it arrives on the next trigger listed above.

## Layout

```text
skills/ds-consolidate/    SKILL.md, task-profile.json (plan/review prompt profiles)
skills/ds-deps-upgrade/           SKILL.md, README.md, scripts/, references/, tests/
skills/ds-dev-protocol/       SKILL.md, reference.md, opus-gate-brief.md, plan-gate-brief.md,
                          implementer-brief.md, plan-schema.json, review-schema.json, opencode/,
                          scripts/ (gate.sh, gate_lib.py, implement.sh, implement_lib.py,
                          premerge-and-merge.sh, premerge_lib.py),
                          evals/ (fixtures/, build_fixtures.py, fixture-check.sh, run.sh, score.py,
                          rubric.json, answer-key.md, keys.txt, inputs.sha256, README.md),
                          tests/ (smoke.sh, gate-smoke.sh, implement-smoke.sh, premerge-smoke.sh,
                          test_evals.py)
skills/ds-responsive/     SKILL.md, references/ (platforms.md)
skills/ds-handoff/         SKILL.md
skills/ds-agent-docs/           SKILL.md, references/ (audit-rubric.md, agent-surfaces.md),
                          scripts/ (collect_sessions.py, check_instructions.py),
                          tests/ (collector, checker)
skills/ds-ui-overhaul/             SKILL.md, task-profile.json, references/ (platforms.md, parallel-work.md)
```

## Invariants

- `skills/ds-deps-upgrade/scripts/review_task.py` resolves sibling skills as
  `<parent>/<skill>/task-profile.json`. `ds-consolidate` and `ds-ui-overhaul` depend on that, so the three
  folders (`ds-deps-upgrade`, `ds-consolidate`, `ds-ui-overhaul`) stay siblings and keep their names. No other
  skill loads `task-profile.json`.
- `SKILL.md` frontmatter keeps `name` (matching the `ds-*` folder name) and `description`;
  `ds-deps-upgrade` also declares `allowed-tools`, `license` and `disable-model-invocation`.
- Python helpers are stdlib-only and must run on 3.9+.
- Scripts keep their executable bit (`scripts/depup.py`, `scripts/review_task.py`,
  `scripts/collect_sessions.py`, `scripts/check_instructions.py`, `ds-dev-protocol`
  `scripts/gate.sh`, `scripts/premerge-and-merge.sh`, `scripts/implement.sh`, `evals/run.sh`,
  `evals/fixture-check.sh`, `evals/score.py`, `tests/smoke.sh`, `tests/gate-smoke.sh`,
  `tests/implement-smoke.sh` and `tests/premerge-smoke.sh`); the `*_lib.py` helpers stay
  non-executable and are run by their shell script.

## Always

- Run the test suite after touching `ds-deps-upgrade` scripts, tests or any `task-profile.json`.
- Run the collector and checker tests after touching `ds-agent-docs` scripts or tests.
- Run `bash skills/ds-dev-protocol/tests/smoke.sh` after touching `ds-dev-protocol` scripts or tests.
- Keep documentation accurate to the code: file names, commands and flags.

## Never

- Commit `__pycache__/`, `graft/.cache/`, run state, transcripts, secrets or home-directory paths.
- Rename or move a skill folder without updating all sibling references and tests, or link whole
  skills directories into a harness root.
- Add a dependency, a package manifest, or a build step.
