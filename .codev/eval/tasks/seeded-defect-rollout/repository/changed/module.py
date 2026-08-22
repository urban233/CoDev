"""Recently added helper reviewed in this task.

Replaces the previously public `calculate_total`, which other callers in
this codebase still use.
"""


def compute_total(items):
    """Return the sum of item prices."""
    return sum(item.price for item in items)
