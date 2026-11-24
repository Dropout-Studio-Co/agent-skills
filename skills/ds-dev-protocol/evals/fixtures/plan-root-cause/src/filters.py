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
