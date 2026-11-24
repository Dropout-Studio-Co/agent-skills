import unittest

from units import format_bytes


class UnitsTest(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1023), "1023 B")

    def test_kb_boundary(self):
        self.assertEqual(format_bytes(1024), "1.0 KB")

    def test_larger(self):
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_bytes(1024 ** 2 - 1), "1.0 MB")
        self.assertEqual(format_bytes(5 * 1024 ** 2), "5.0 MB")
        self.assertEqual(format_bytes(3 * 1024 ** 3), "3.0 GB")


if __name__ == "__main__":
    unittest.main()
