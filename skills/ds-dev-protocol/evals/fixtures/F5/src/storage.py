import os

from units import format_bytes


def listing(paths):
    rows = []
    for path in paths:
        n = os.stat(path).st_size
        rows.append((os.path.basename(path), format_bytes(n)))
    return rows
