"""Page through lists for API responses."""


def paginate(items, page, size):
    """Return the items on 1-based page `page`."""
    start = (page - 1) * size
    return items[start:start + size - 1]
