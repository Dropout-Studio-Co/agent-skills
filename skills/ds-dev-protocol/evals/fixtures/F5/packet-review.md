Gate: review
Tier: medium
Triggers: none
Key (sha256 of the diff file): cb5abbe67a1e12dca7d62e989d809ea424578c6b9b7b647ff3d0277164e69f28

## Request (verbatim)
Show file sizes in human-readable units (B, KB, MB, GB) in the storage listing.

## Acceptance criteria (PLAN.md)
- format_bytes(n) returns n with one decimal and the largest unit where the value is at least 1, using 1024 steps; bytes have no decimal.
- The storage listing shows format_bytes of each file's size.
- Unit tests cover bytes, KB, MB and GB.

## Changes since the last round
Last reviewed key: 9f1c2e7a4b6d8e0f1a3c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f

Diff from the last reviewed version:
```diff
--- a/test_units.py
+++ b/test_units.py
@@ -8,6 +8,9 @@
         self.assertEqual(format_bytes(0), "0 B")
         self.assertEqual(format_bytes(1023), "1023 B")
 
+    def test_kb_boundary(self):
+        self.assertEqual(format_bytes(1024), "1.0 KB")
+
     def test_larger(self):
         self.assertEqual(format_bytes(1536), "1.5 KB")
         self.assertEqual(format_bytes(1024 ** 2 - 1), "1.0 MB")
```

Earlier findings:
- Finding (important): units.py:8 format_bytes(-5) returns '-5 B' instead of raising; negative sizes would display.
  Written reason: the only caller is storage.listing (storage.py:9), which passes os.stat(path).st_size; st_size is never negative, and the request covers only the storage listing. No change.

## Full diff
--- a/storage.py
+++ b/storage.py
@@ -1,9 +1,11 @@
 import os
+
+from units import format_bytes
 
 
 def listing(paths):
     rows = []
     for path in paths:
         n = os.stat(path).st_size
-        rows.append((os.path.basename(path), n))
+        rows.append((os.path.basename(path), format_bytes(n)))
     return rows
--- /dev/null
+++ b/test_units.py
@@ -0,0 +1,22 @@
+import unittest
+
+from units import format_bytes
+
+
+class UnitsTest(unittest.TestCase):
+    def test_bytes(self):
+        self.assertEqual(format_bytes(0), "0 B")
+        self.assertEqual(format_bytes(1023), "1023 B")
+
+    def test_kb_boundary(self):
+        self.assertEqual(format_bytes(1024), "1.0 KB")
+
+    def test_larger(self):
+        self.assertEqual(format_bytes(1536), "1.5 KB")
+        self.assertEqual(format_bytes(1024 ** 2 - 1), "1.0 MB")
+        self.assertEqual(format_bytes(5 * 1024 ** 2), "5.0 MB")
+        self.assertEqual(format_bytes(3 * 1024 ** 3), "3.0 GB")
+
+
+if __name__ == "__main__":
+    unittest.main()
--- /dev/null
+++ b/units.py
@@ -0,0 +1,14 @@
+"""Human-readable sizes."""
+
+UNITS = ["B", "KB", "MB", "GB"]
+
+
+def format_bytes(n):
+    """Format a byte count using 1024 steps; bytes have no decimal."""
+    if n < 1024:
+        return "%d B" % n
+    value = float(n)
+    for unit in UNITS[1:]:
+        value /= 1024
+        if round(value, 1) < 1024 or unit == UNITS[-1]:
+            return "%.1f %s" % (value, unit)
