Gate: review
Tier: medium
Triggers: none
Key (sha256 of the diff file): 1eeda8623c148d3475ec9902f5c2e6458362aae5a02f6af948acc654f4d477f5

## Request (verbatim)
Validate the PORT setting at startup and fail with a clear message when it is invalid.

## Acceptance criteria (PLAN.md)
- parse_port(value) returns an int between 1 and 65535.
- Empty, non-numeric or out-of-range values raise ValueError with a message naming PORT.
- Unit tests cover valid, empty, non-numeric and out-of-range values.

## Full diff
--- /dev/null
+++ b/config.py
@@ -0,0 +1,13 @@
+"""Startup configuration."""
+import re
+
+
+def parse_port(value):
+    """Parse the PORT setting; raise ValueError naming PORT when it is invalid."""
+    text = (value or "").strip()
+    if not re.fullmatch(r"[0-9]+", text):
+        raise ValueError("PORT must be a whole number, got %r" % value)
+    port = int(text)
+    if not 1 <= port <= 65535:
+        raise ValueError("PORT must be between 1 and 65535, got %d" % port)
+    return port
--- /dev/null
+++ b/test_config.py
@@ -0,0 +1,20 @@
+import unittest
+
+from config import parse_port
+
+
+class PortTest(unittest.TestCase):
+    def test_valid(self):
+        self.assertEqual(parse_port("8080"), 8080)
+        self.assertEqual(parse_port(" 1 "), 1)
+        self.assertEqual(parse_port("65535"), 65535)
+
+    def test_invalid(self):
+        for bad in [None, "", "  ", "abc", "-1", "0", "65536", "80.5", "²", "٣"]:
+            with self.subTest(bad=bad):
+                with self.assertRaisesRegex(ValueError, "PORT"):
+                    parse_port(bad)
+
+
+if __name__ == "__main__":
+    unittest.main()
