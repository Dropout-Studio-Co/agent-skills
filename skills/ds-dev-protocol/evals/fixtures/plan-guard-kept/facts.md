# Facts: tenant export paths

## Request (verbatim)

Support nested tenant folders (for example reports/2026/q1.csv) in the export endpoint and keep downloads safe.

## Repo rules

- Python 3.9+, standard library only, `unittest`; no new dependency.
- Any change to path handling, permissions or tenancy is High tier.
- Smallest change that fully meets the request; tests are written failing first.

## Current code (src/)

exports.py

```python
"""Tenant file exports."""
import os

ROOT = "/srv/exports"


def tenant_root(tenant):
    """Resolve the tenant's directory, following symlinks."""
    return os.path.realpath(os.path.join(ROOT, tenant))


def export_path(tenant, relative):
    """Return the on-disk path of one tenant export, refusing traversal and symlink escapes."""
    base = tenant_root(tenant)
    target = os.path.realpath(os.path.join(base, relative))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("path escapes the tenant directory: %r" % relative)
    return target
```

test_exports.py

```python
import os
import tempfile
import unittest

import exports


class ExportPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.root, "acme", "reports", "2026"))
        os.makedirs(os.path.join(self.root, "other"))
        with open(os.path.join(self.root, "acme", "reports", "2026", "q1.csv"), "w") as handle:
            handle.write("quarter\n")
        self.addCleanup(setattr, exports, "ROOT", exports.ROOT)
        exports.ROOT = self.root

    def test_nested_path_allowed(self):
        got = exports.export_path("acme", os.path.join("reports", "2026", "q1.csv"))
        self.assertEqual(got, os.path.join(self.root, "acme", "reports", "2026", "q1.csv"))

    def test_parent_traversal_refused(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            exports.export_path("acme", "../other/secret.txt")

    def test_symlink_escape_refused(self):
        os.symlink(os.path.join(self.root, "other"), os.path.join(self.root, "acme", "reports", "escape"))
        with self.assertRaisesRegex(ValueError, "escapes"):
            exports.export_path("acme", os.path.join("reports", "escape", "secret.txt"))


if __name__ == "__main__":
    unittest.main()
```

## Verified facts

- `exports.py:9` and `exports.py:15` resolve the tenant root and the requested path with `os.path.realpath`, so symlinks are followed before the comparison; a symlink out of the tenant resolves to the target and is caught.
- `exports.py:16` compares them with `os.path.commonpath([base, target]) != base`; a sibling directory, `..` traversal or absolute `relative` resolves outside `base` and raises `ValueError`.
- `exports.py:4` keeps `ROOT` module-level so tests point it at a temporary tree; `test_exports.py:17` restores it on cleanup.
- Nested paths already work: `test_exports.py:20-22` fetches `reports/2026/q1.csv` and passes today, and `test_exports.py:24-26` and `test_exports.py:28-31` prove the traversal and symlink refusals.
- The guard is the `realpath` + `commonpath` pair. A refactor that instead joins strings, uses `os.path.abspath`, strips `..`, or compares with `str.startswith` reopens traversal or symlink escapes (`acme-old` starts with `acme`; `abspath` does not resolve symlinks).
- Precondition repro: `python3 -I -B repro.py` in the fixture root prints both refusals and exits 0.
