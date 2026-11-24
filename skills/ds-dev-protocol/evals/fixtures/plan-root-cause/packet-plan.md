Gate: plan
Tier: medium
Key (sha256 of facts.md): 065567e277c679cccb8df90fbf553ff35d3338b8dfc6ae5948a201cb83e51c3c

# Facts: search filter defaults

## Request (verbatim)

Stop search results from inheriting tags between requests.

## Repo rules

- Python 3.9+, standard library only, `unittest`; no new dependency.
- Smallest change that fully meets the request; tests are written failing first.

## Current code (src/)

filters.py

```python
"""Filter defaults for search."""

DEFAULT_FILTERS = {"tags": [], "sort": "new"}


def filters_for(request):
    """Return the filter dict for one search request."""
    filters = dict(DEFAULT_FILTERS)
    filters.update(request or {})
    return filters


def add_tag(filters, tag):
    """Add one tag to a filter dict in place."""
    filters["tags"].append(tag)
    return filters
```

search.py

```python
"""Search entry point."""
from filters import add_tag, filters_for

RESULTS = {}


def search(request):
    """Run one search and cache its results per tag set."""
    filters = add_tag(filters_for(request), "visible")
    key = tuple(filters["tags"])
    if key not in RESULTS:
        RESULTS[key] = ["result-for-%s" % (request or {}).get("tag", "all")]
    return RESULTS[key]


def clear_cache():
    """Drop cached results (tests call this between cases)."""
    RESULTS.clear()
```

test_filters.py

```python
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
```

## Verified facts

- `filters.py:3` defines one module-level `DEFAULT_FILTERS` dict whose `"tags"` value is a list.
- `filters.py:8` returns `dict(DEFAULT_FILTERS)`, a shallow copy: every returned dict shares that one list object.
- `filters.py:15` mutates the list in place through `filters["tags"].append(tag)`.
- `search.py:9` adds the tag `"visible"` on every request and `search.py:10` caches results per tag tuple, so the shared list also changes the cache key on later requests.
- `test_filters.py:9` clears only `RESULTS`; nothing resets `DEFAULT_FILTERS`, and `test_empty_request_has_no_tags` runs first (alphabetical order), so the suite passes today.
- Repro, from `src/`: `python3 -I -B -c "import search; search.search({'tag': 'shoes'}); from filters import filters_for; print(filters_for({})['tags'])"` prints `['visible']`; a second search makes it `['visible', 'visible']`. A request that names no tags must see `[]`.
- The leak lives in `filters.py`; `search.py` is only the caller that observes it. Clearing `RESULTS` more often, or dropping the `"visible"` tag, masks the symptom and leaves the shared list in place.
- Precondition repro: `python3 -I -B repro.py` in the fixture root prints the two leaking tag lists and exits 0.
