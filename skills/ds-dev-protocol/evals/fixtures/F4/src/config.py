"""Startup configuration."""
import re


def parse_port(value):
    """Parse the PORT setting; raise ValueError naming PORT when it is invalid."""
    text = (value or "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError("PORT must be a whole number, got %r" % value)
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535, got %d" % port)
    return port
