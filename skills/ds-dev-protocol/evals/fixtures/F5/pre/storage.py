import os


def listing(paths):
    rows = []
    for path in paths:
        n = os.stat(path).st_size
        rows.append((os.path.basename(path), n))
    return rows
