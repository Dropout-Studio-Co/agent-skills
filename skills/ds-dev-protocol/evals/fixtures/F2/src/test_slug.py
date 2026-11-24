import unittest

from slug import slugify


class SlugTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_bug_212_repeated_spaces(self):
        title = "Release Notes 2026"
        expected = "-".join(title.lower().split())
        self.assertEqual(slugify(title), expected)


if __name__ == "__main__":
    unittest.main()
