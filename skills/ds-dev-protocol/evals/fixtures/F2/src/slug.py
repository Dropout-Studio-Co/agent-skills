"""URL slugs for article titles."""
import re


def slugify(title):
    return re.sub(r"\s+", "-", title.strip().lower())
