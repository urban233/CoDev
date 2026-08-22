"""Small slug helper used by the evaluation task."""


def slugify(value: str) -> str:
    """Return a lowercase slug."""
    return value.lower().replace(" ", "-")
