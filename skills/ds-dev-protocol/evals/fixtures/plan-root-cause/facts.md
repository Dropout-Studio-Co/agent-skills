# Facts: search filter defaults

## Request (verbatim)

Stop search results from inheriting tags between requests.

## Repo rules

- Python 3.9+, standard library only, `unittest`; no new dependency.
- Smallest change that fully meets the request; tests are written failing first.
- `src/` is the code under change; read it before you plan.

## Symptom

- A search request that names no tags does not start from a clean filter set. It carries one more
  tag for every search already run in the same process, so the state grows on every request and a
  tag-free request is handled as a tagged one.
- Repro, from `src/`:
  `python3 -I -B -c "import sys; sys.path.insert(0, '.'); import search; search.search({}); search.search({}); print(sorted(search.RESULTS))"`
  prints `[('visible',), ('visible', 'visible')]`. Two identical tag-free requests must land on one
  shared cache entry; a third call must not add a third tag.
- The test fixture also ships `repro.py` (in the fixture root, outside `src/`), which prints the
  same accumulation as two tag lists and exits 0 while it leaks.
- Already tried: clearing the cached results (`RESULTS`) between requests. The tags still
  accumulate across calls, so dropping the cache does not stop it.
- The existing tests under `src/` pass today; they never run the sequence above.

## Verified facts

- The repro above is reproducible in `src/` and prints the two growing tag lists.
- `python3 -I -B -m unittest discover -s . -p 'test_*.py'`, run in `src/`, passes today.
