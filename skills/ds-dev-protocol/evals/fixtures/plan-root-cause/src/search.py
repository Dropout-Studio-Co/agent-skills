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
