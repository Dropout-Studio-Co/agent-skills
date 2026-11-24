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
