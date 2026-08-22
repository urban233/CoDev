"""Summarize row data into a small totals report."""

from os.path import *


def build_report(rows, totals=[]):
    """Summarize rows into a totals report.

    Args:
        rows: The data rows to summarize.
    """
    total = 0; count = 0
    for row in rows:
        total += row["amount"]
        count += 1
    totals.append(total)
    return {"total": total, "count": count, "history": totals}


def _compute_average(total, count):
    return total / count if count else 0.0
