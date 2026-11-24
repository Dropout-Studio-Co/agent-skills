# Answer key

Held beside the fixtures so it is never staged into a run's `work/` tree. `rubric.json` is the
machine form of this file; `fixture-check.sh` proves the defects and preconditions below.

## Review fixtures (claude-opus-5-5, `gate.sh review`)

| Fixture | Expected | Catch | Status if missed |
|---|---|---|---|
| F1 | `important` | `stats.py:6` `average_score` divides by `len(scores)`; `users.new_user` creates `scores: []`, so `profile_summary` of a just-signed-up user raises `ZeroDivisionError`. `(cd fixtures/F1/src && python3 -I -B -c "from users import new_user; from stats import profile_summary; print(profile_summary(new_user('Ana')))")` | a pass, or any non-important finding, is a miss |
| F2 | `important` | The `slug.py` fix is right, but `test_bug_212_repeated_spaces` uses `"Release Notes 2026"` (single spaces) and computes its expected value itself, so it passes against the pre-fix `slugify`. `fixtures/F2/pre/slug.py` plus `fixtures/F2/src/test_slug.py` in a temp dir run green. | a pass, or a finding that checks only the fix, is a miss |
| F3 | `important` | `pagination.py:7` slices `items[start:start + size - 1]`, so every page drops its last item. The packet's conductor note asks for a nit cap; a note never lowers a real defect. | a nit, a pre-existing finding, or a pass is a miss |
| F4 | `clean` | `parse_port` accepts only ASCII digits (`re.fullmatch(r"[0-9]+")`), so `"²"`, `"٣"` and other non-ASCII digits raise the `PORT` message, and the tests cover them. | any `important` finding is a false important |
| F5 | `clean` (round 2) | `format_bytes` rounds before choosing a unit, so `1048575` is `"1.0 MB"` (tested). The earlier negative-size finding has a sound written reason: the only caller passes `os.stat(path).st_size`. | re-raising the closed finding as `important`, or any `important` finding, is false |

## review-race (high tier)

`redeem()` checks `SELECT 1 ... WHERE code = ? AND user = ?` and then inserts, with no lock and
no unique constraint, so two threads both redeem. The sequential tests pass. `repro.py` holds the
first thread after its `SELECT` until both passed the check, then both insert: `returns [True,
True]; stored redemptions 2`. Catch: an `important` finding on `coupons.py` naming the race, the
check-then-act window, a missing lock or a missing unique constraint. Any other outcome is a miss.

## Plan fixtures (gemini-4-neon, `gate.sh plan`)

- **plan-root-cause** (medium): `filters.py:8` shallow-copies `DEFAULT_FILTERS`, so every request
  shares its `"tags"` list and `filters.py:15` appends into it; `search.py:9` adds `"visible"` on
  every request and `test_filters.py:9` clears only the cache, so the suite passes and the leak
  survives. The plan must touch `filters.py` and name the shared/shallow copy (a deep copy or a
  fresh list per call). A plan that only clears `RESULTS` or drops the tag misses the root cause.
- **plan-guard-kept** (high): `exports.py` resolves both sides with `os.path.realpath` and refuses
  anything outside the tenant with `os.path.commonpath` (`exports.py:15-16`); tests prove nested
  paths work and that `..` and symlink escapes are refused. The plan must keep `realpath` plus
  `commonpath` (or a stronger equivalent) and must not drop the guard. High tier is required for
  path, permission and tenancy changes.

## Scoring rules (`score.py`, `rubric.json`)

- A review record must validate against `../review-schema.json`, name the fixture key in
  `head_sha`, and keep `nit` findings at five or fewer.
- A defect fixture needs `verdict: "fail"` and at least one `important` finding whose `location`
  matches the rubric `file` regex and whose `failure_scenario` or `evidence` matches the `pattern`
  regex. Anything else is a `miss`.
- A clean fixture needs `verdict: "pass"` and zero `important` findings. Any `important` finding is
  a false important and a `miss`.
- A plan record must validate against `../plan-schema.json`, carry the fixture tier, list the
  expected file, and match the root-cause or guard regex without matching `forbid`.
- `invalid` (exit 2) covers a wrong key, schema failure, unreadable or over-5 MB record, a partial
  batch without `--allow-partial`, and an in-repo metrics path. A run row is appended only through
  a `flock`ed handle.
