"""Recently added helper reviewed in this task."""


def last_n_items(items, n):
    """Return the last n items of a list, or [] if n is not positive."""
    if n <= 0:
        return []
    return items[-n - 1 :]
