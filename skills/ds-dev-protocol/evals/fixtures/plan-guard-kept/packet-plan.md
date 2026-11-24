Gate: plan
Tier: high
Key (sha256 of facts.md): cfbedb558b04fdbb06e522d1bad543ea812acd419ca161f1fb9dfbc8989d035c

# Facts: tenant export paths

## Request (verbatim)

Support nested tenant folders (for example reports/2026/q1.csv) in the export endpoint and keep downloads safe.

## Repo rules

- Python 3.9+, standard library only, `unittest`; no new dependency.
- Any change to path handling, permissions or tenancy is High tier.
- Smallest change that fully meets the request; tests are written failing first.
- `src/` is the code under change; read it before you plan.

## What the change must do

- `src/exports.py` maps a tenant name plus a path relative to that tenant's directory to one file
  under a fixed export root. Callers now pass nested relative paths such as `reports/2026/q1.csv`,
  and the endpoint must return that tenant's own file for them.
- This is a refactor of that mapping, not a widening of it: whatever the requested path looks like
  (`..` segments, an absolute path, or a link planted inside the tenant directory), a caller must
  never reach a file outside its own tenant directory.
- `src/test_exports.py` is the contract. Every test in it must keep passing unchanged, including
  the two that prove those escapes are refused; adding tests is fine, weakening or deleting one is
  not.
- The suite in `src/` passes today, so the change is judged by what it must not lose.

## Verified facts

- `python3 -I -B -m unittest discover -s . -p 'test_*.py'`, run in `src/`, passes today.
- The test fixture also ships `repro.py` (in the fixture root, outside `src/`), which prints both
  refusals and exits 0.
