"""Prove the export guard is present: parent traversal and symlink escapes are refused."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import exports

root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, "acme", "reports", "2026"))
os.makedirs(os.path.join(root, "other"))
os.symlink(os.path.join(root, "other"), os.path.join(root, "acme", "reports", "escape"))
exports.ROOT = root
try:
    for relative in ("../other/secret.txt", os.path.join("reports", "escape", "secret.txt")):
        try:
            path = exports.export_path("acme", relative)
        except ValueError:
            print("refused %r" % (relative,))
        else:
            print("ALLOWED %r -> %s" % (relative, path))
            sys.exit(1)
    print("guard kept: parent traversal and symlink escapes are refused")
finally:
    shutil.rmtree(root, ignore_errors=True)
