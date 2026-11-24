import unittest

from pagination import paginate


class PaginateTest(unittest.TestCase):
    def test_past_end_is_empty(self):
        self.assertEqual(paginate(list(range(10)), 5, 3), [])

    def test_returns_list(self):
        self.assertIsInstance(paginate(list(range(10)), 1, 3), list)


if __name__ == "__main__":
    unittest.main()
