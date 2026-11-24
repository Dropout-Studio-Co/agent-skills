import unittest

import search
from filters import filters_for


class FiltersTest(unittest.TestCase):
    def setUp(self):
        search.clear_cache()

    def test_empty_request_has_no_tags(self):
        self.assertEqual(filters_for({})["tags"], [])

    def test_search_returns_result(self):
        self.assertEqual(search.search({"tag": "shoes"}), ["result-for-shoes"])

    def test_search_returns_result_for_another_tag(self):
        search.search({"tag": "shoes"})
        self.assertEqual(search.search({"tag": "hats"}), ["result-for-hats"])


if __name__ == "__main__":
    unittest.main()
