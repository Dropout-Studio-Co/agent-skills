"""Prove the tag leak: one search writes its tag into the module-level default list."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import search
from filters import DEFAULT_FILTERS, filters_for

search.search({"tag": "shoes"})
first = list(filters_for({})["tags"])
search.search({"tag": "hats"})
second = list(filters_for({})["tags"])
print("a request with no tags sees %r, then %r (correct: [] and [])" % (first, second))
print("DEFAULT_FILTERS['tags'] is %r" % (DEFAULT_FILTERS["tags"],))
return_ok = first == ["visible"] and second == ["visible", "visible"]
sys.exit(0 if return_ok else 1)
