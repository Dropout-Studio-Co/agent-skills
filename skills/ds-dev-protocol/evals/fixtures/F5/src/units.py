"""Human-readable sizes."""

UNITS = ["B", "KB", "MB", "GB"]


def format_bytes(n):
    """Format a byte count using 1024 steps; bytes have no decimal."""
    if n < 1024:
        return "%d B" % n
    value = float(n)
    for unit in UNITS[1:]:
        value /= 1024
        if round(value, 1) < 1024 or unit == UNITS[-1]:
            return "%.1f %s" % (value, unit)
