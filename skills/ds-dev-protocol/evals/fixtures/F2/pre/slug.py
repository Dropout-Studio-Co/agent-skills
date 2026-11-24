"""URL slugs for article titles."""


def slugify(title):
    return title.strip().lower().replace(" ", "-")
