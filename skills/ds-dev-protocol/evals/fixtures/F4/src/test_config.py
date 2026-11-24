import unittest

from config import parse_port


class PortTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_port("8080"), 8080)
        self.assertEqual(parse_port(" 1 "), 1)
        self.assertEqual(parse_port("65535"), 65535)

    def test_invalid(self):
        for bad in [None, "", "  ", "abc", "-1", "0", "65536", "80.5", "²", "٣"]:
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "PORT"):
                    parse_port(bad)


if __name__ == "__main__":
    unittest.main()
