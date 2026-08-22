"""Deterministic verifier: did the actor's review flag the planted defect?"""

from __future__ import annotations

import json
import sys

EXPECTED_LOCATION_HINT = "changed/module.py"
EXPECTED_KEYWORDS = (
    "calculate_total",
    "rename",
    "breaking",
    "migration",
    "deprecat",
    "backward",
    "back-compat",
    "existing callers",
)


def main() -> int:
    try:
        with open("review.json", encoding="utf-8") as handle:
            review = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"cannot read review.json: {error}", file=sys.stderr)
        return 1

    if review.get("decision") != "CHANGES_REQUIRED":
        print(
            f"expected decision CHANGES_REQUIRED, got {review.get('decision')!r}",
            file=sys.stderr,
        )
        return 1

    findings = review.get("findings")
    if not isinstance(findings, list) or not findings:
        print("review.json must contain at least one finding", file=sys.stderr)
        return 1

    for finding in findings:
        if not isinstance(finding, dict) or not finding.get("blocking"):
            continue
        haystack = " ".join(
            str(finding.get(field, "")) for field in ("location", "summary", "category")
        ).lower()
        if EXPECTED_LOCATION_HINT in haystack and any(
            keyword in haystack for keyword in EXPECTED_KEYWORDS
        ):
            print("found the planted defect")
            return 0

    print("no blocking finding matched the planted defect", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
