# Contributing

These are personal workflow skills, published so they are versioned, reviewable and portable.
Bug reports and fixes are welcome; there is no roadmap or feature-request process.

## Before you change anything

Read the skill you are touching. `SKILL.md` is the workflow, and for `dependency-upgrade` the
`references/` files carry the detail. Keep the change inside the skill it belongs to.

## Invariants

- **Folder names are the skill names.** `consolidate` and `frontend-ui-ux-overhaul` resolve
  `../dependency-upgrade/scripts/review_task.py` and their own `task-profile.json` from their location.
  Renaming or splitting `skills/dependency-upgrade` breaks both.
- **Skills stay self-contained.** A folder must work when copied alone into a global skills root,
  except for the shared fresh-context task scripts above.
- **Frontmatter stays valid.** Every `SKILL.md` keeps `name` and `description`; the description
  states what the skill does and when to use it.
- **No machine-specific paths.** Document the canonical install root (`~/.agents/skills/<skill>`,
  `~/.claude/skills/<skill>`); never commit a home directory, transcript, or run state.
- **No new dependencies** without a clear need. The helpers are stdlib-only Python.

## Checks

```sh
python3 -m unittest discover -s skills/dependency-upgrade/tests -t skills/dependency-upgrade
python3 -m unittest discover -s skills/sync-agent-instructions/tests -t skills/sync-agent-instructions
```

Run the dependency-upgrade suite after any change to `dependency-upgrade` scripts, tests or any
`task-profile.json` (this also validates the `consolidate` and `frontend-ui-ux-overhaul` profiles). Run
the collector and checker suite after changes to `sync-agent-instructions` scripts or tests.

`sync-agent-instructions` ships two stdlib-only helpers. `scripts/collect_sessions.py` collects
and redacts session evidence; `scripts/check_instructions.py` surveys a repository (`check`),
runs a read-only cross-agent prompt-audit (`audit`), stages a memory-file edit (`stage`), gates
it against that evidence and typed claims (`gate`), and applies only a gated stage (`apply`).
The checker never commits, pushes, opens a pull request or merges, and only `apply` writes to a
repository. Both scripts keep their executable bit, require Python 3.9+, and their tests use
scratch repositories with no network, credentials or outside paths. Also re-read the file you
edited: commands, paths and script names must match the repository.

## Installing a change locally

```sh
diff -rq -x __pycache__ -x graft skills/<name> ~/.agents/skills/<name>
rsync -a --exclude '__pycache__/' --exclude 'graft/.cache/' skills/<name>/ ~/.agents/skills/<name>/
```

Run the drift check from an up-to-date `main` before starting a change to a skill: it must print
nothing (any difference is local drift; bring it into the repository first). After the change is
merged, sync from the merged `main` with the rsync above, then run the drift check again: it must
print nothing. A file deleted in the repository is removed from the installed copy by hand before
that final check.

On the maintainer's machine a LaunchAgent sync keeps `~/.agents/skills/<name>` and `main` in step
both ways: it runs on every local change, at login and when the network comes back. An edit to the
installed copy is pushed straight to `main` without review, so contributions and agent changes go through a PR here; merged changes are installed
automatically. `~/.agents/bin/agent-skills-sync --dry-run` previews a run. See "Automatic sync" in
[AGENTS.md](./AGENTS.md) for the full rules: managed skills, ignored files and held changes.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `fix:`, `feat:`, `docs:`, `test:`,
`chore:`. Imperative subject, one logical change per commit, no AI attribution trailers.

## Secrets and private data

Never commit API keys, tokens, `.env` files, session transcripts, personal paths or run state. New
tests use fixtures and temporary directories only, and never call a real model, registry or remote.

## License

The repository and the skills it contains are released under the [MIT License](./LICENSE).
