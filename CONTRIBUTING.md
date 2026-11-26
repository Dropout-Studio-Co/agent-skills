# Contributing

These are Dropout Studio (`ds-*`) workflow skills, published so they are versioned, reviewable and
portable across web, mobile, native, desktop, TV, CLI, and backend projects. Bug reports and fixes
are welcome; there is no roadmap or feature-request process.

## Before you change anything

Read the skill you are touching. `SKILL.md` is the workflow, and `references/` files carry
platform- or domain-specific detail. Keep the change inside the skill it belongs to.

## Invariants

- **Folder names are the skill names.** All skills use lowercase `ds-*` names. `ds-consolidate`
  and `ds-ui-overhaul` resolve `../ds-deps-upgrade/scripts/review_task.py` and their own `task-profile.json` from
  their location. Renaming or splitting `skills/ds-deps-upgrade` breaks both.
- **Skills stay self-contained.** A folder must work when copied alone into a global skills root,
  except for the shared fresh-context task scripts above.
- **Frontmatter stays valid.** Every `SKILL.md` keeps `name` and `description`; the description
  states what the skill does and when to use it.
- **No machine-specific paths.** Document the canonical install root (`~/.agents/skills/<skill>`,
  `~/.claude/skills/<skill>`); never commit a home directory, transcript, or run state.
- **No new dependencies** without a clear need. Helpers under `skills/` are stdlib-only Python
  (3.9+, no third-party packages). `crates/ds-agent-docs/` is the explicit exception: it is a Rust
  crate with its own `Cargo.toml`, `Cargo.lock` and dependencies, kept outside `skills/` so the
  text-only skill sync never carries build output.

## Checks

```sh
python3 -m unittest discover -s skills/ds-deps-upgrade/tests -t skills/ds-deps-upgrade
python3 -m unittest discover -s skills/ds-agent-docs/tests -t skills/ds-agent-docs
cargo test --manifest-path crates/ds-agent-docs/Cargo.toml
cargo clippy --manifest-path crates/ds-agent-docs/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path crates/ds-agent-docs/Cargo.toml --check
bash skills/ds-dev-protocol/tests/smoke.sh
```

Run the `ds-deps-upgrade` suite after any change to `ds-deps-upgrade` scripts, tests or any `task-profile.json`
(this also validates the `ds-consolidate` and `ds-ui-overhaul` profiles). Run the collector and checker
suite after changes to `ds-agent-docs` scripts or tests, run the Cargo commands above after changes to
`crates/ds-agent-docs/`, and run `bash skills/ds-dev-protocol/tests/smoke.sh` after changes to
`ds-dev-protocol` scripts or tests.

`ds-agent-docs` ships two stdlib-only helpers under `skills/ds-agent-docs/scripts/`.
`collect_sessions.py` collects and redacts session evidence; `check_instructions.py` runs a read-only
cross-agent instruction and documentation audit (`audit --repo R [--scope P]`) and never modifies a
repository. Both keep their executable bit, require Python 3.9+, and their tests use scratch
repositories with no network, credentials or outside paths. The Rust CLI in `crates/ds-agent-docs/`
provides the same `audit` and `collect` commands and is what `SKILL.md` invokes; the Python helpers
stay as the fallback. Also re-read the file you edited: commands, paths and script names must match
the repository.

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
installed copy is pushed straight to `main` without review, so contributions and agent changes go
through a PR here; merged changes are installed automatically.
`~/.agents/bin/agent-skills-sync --dry-run` previews a run. See "Automatic sync" in
[AGENTS.md](./AGENTS.md) for the full rules: managed skills, ignored files and held changes.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `fix:`, `feat:`, `docs:`, `test:`,
`chore:`. Imperative subject, one logical change per commit, no AI attribution trailers.

## Secrets and private data

Never commit API keys, tokens, `.env` files, session transcripts, personal paths or run state. New
tests use fixtures and temporary directories only, and never call a real model, registry or remote.

## License

The repository and the skills it contains are released under the [MIT License](./LICENSE).
