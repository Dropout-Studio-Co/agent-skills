# Gate eval set

Eight behaviour fixtures that check the review and plan gates themselves: five review fixtures
kept from the 2026-11-14 sp-apply run (byte-identical diffs, keys `70f073f5`, `cdab3e6d`,
`b255e8cd`, `1eeda862`, `cb5abbe6`), one high-tier race review, and two plan fixtures. Nothing
here is read by `scripts/`, the briefs or the schemas; the eval set runs beside the gate, never
inside it.

| Fixture | Kind | Tier | Expect |
|---|---|---|---|
| `F1` | review | medium | Important: empty score list divides by zero |
| `F2` | review | medium | Important: the regression test cannot fail |
| `F3` | review | medium | Important despite a note asking for a nit |
| `F4` | review | medium | clean: non-ASCII digits already rejected |
| `F5` | review | medium (round 2) | clean: the earlier finding has a sound reason |
| `review-race` | review | high | Important: check-then-act double redemption |
| `plan-root-cause` | plan | medium | plan fixes the shared default list in `filters.py` |
| `plan-guard-kept` | plan | high | plan keeps the `realpath`/`commonpath` guard |

## Layout

```text
evals/fixtures/<id>/fixture.json  request, tier, criteria, expected outcome
evals/fixtures/<id>/pre/ src/     before and after trees (review fixtures)
evals/fixtures/<id>/fixture.diff  generated from pre/ and src/
evals/fixtures/<id>/packet-review.md | facts.md + packet-plan.md
evals/fixtures/<id>/meta.json     generated key, kind, tier, expectation
evals/fixtures/<id>/repro.py      present for the three new fixtures: proves the defect
build_fixtures.py  regenerate or --check every derived file and inputs.sha256
fixture-check.sh   prove all eight defects/preconditions and run all eight suites
run.sh             check | prepare | record | score
score.py           validate and score records; append one metrics row
rubric.json        machine rubric; answer-key.md explains every expected outcome
```

## Commands

```sh
python3 -I -B skills/ds-dev-protocol/evals/build_fixtures.py --check
(cd skills/ds-dev-protocol/evals && shasum -a 256 -c inputs.sha256)
bash skills/ds-dev-protocol/evals/fixture-check.sh
bash skills/ds-dev-protocol/evals/run.sh check
python3 -I -B -m unittest discover -s skills/ds-dev-protocol/tests -p 'test_evals.py'
```

`python3 -m unittest <path>` needs the working directory on `sys.path`, which isolated mode
(`-I`) removes, so the suite is run through `discover`, which inserts its start directory itself;
`smoke.sh` runs it that way under both interpreters.

`prepare` stages each fixture outside the repository: `<out>/<variant>-<id>/work/` holds a copy of
`src/` (never `answer-key.md`, `rubric.json` or `meta.json`), `<out>/<variant>-<id>/evid/` holds the
packet and either `fixture.diff` or `facts.md`, and `<out>/manifest.json` lists them. `work/` is a
plain directory, not a git worktree, so `gate.sh plan` has nothing to clean-tree check and a child
cannot read the answer key or mutate the repository. Default `--out-dir` is
`${XDG_STATE_HOME:-$HOME/.local/state}/dev-evidence/evals/<utc>`; an out-dir inside a git repository
or the skill directory exits 2, as does any drift between `inputs.sha256` and the fixtures.

`record` runs `scripts/gate.sh --record` from that fixture's `work/` and keeps its exit code
(0 pass, 1 fail verdict, 2 usage/precondition, 3 blocked, 4 round cap). It writes `<evid>/exit`, and
skips a fixture already at 0 or 1 unless `--force` is given. `--evid`, `--record` and `--diff` are
resolved to absolute paths before the call, a review fixture with no `--diff` uses its staged
`<evid>/fixture.diff`, and the call runs with `XDG_STATE_HOME=<evid>/state` so synthetic eval
findings never reach the production `review-metrics/findings.jsonl`. `--variant` and `--fixture`
names must match `[A-Za-z0-9._-]+`. The gate call itself is unchanged: a real run still needs the T3
child and parent thread ids, and `gate.sh` still verifies the model, effort, thread and payload.

`score` validates a record against `../review-schema.json` or `../plan-schema.json` (unwrapping
`structured_output`), checks the fixture key in `head_sha`, and scores it against `rubric.json`.
A miss exits 1; an invalid or missing record, a wrong key, a record over 5 MB or a partial batch
exits 2, with or without `--append-jsonl`. `--append-jsonl` writes exactly one row per run to
`${XDG_STATE_HOME:-$HOME/.local/state}/review-metrics/evals.jsonl` under `flock`, and refuses any
path inside a git repository. The row carries `date`, `eval`, `fixtures`, `total`, `passed`,
`false_important`, `variant`, `score` and `misses`, where `false_important` counts Important
findings raised on a clean fixture.

## Validity and rerun

- `fixture-check.sh` prints every command with its output and exits nonzero if a proof or a suite
  fails; it also proves zero `__pycache__` remains (all Python runs use `-I -B`).
- Any edit to a fixture source needs `build_fixtures.py` (no flag) to regenerate the diff, packet,
  `meta.json`, `keys.txt` and `inputs.sha256`; `--check` then proves the tree is consistent.
- Rescore after any change to `opus-gate-brief.md`, `plan-gate-brief.md`, `plan-schema.json` or
  `review-schema.json`, and record one row per variant.
- The rubric matches identifiers and failure wording with regexes, so a correct finding phrased far
  from the expected language can still score as a miss; `score.py` prints which part did not match.
