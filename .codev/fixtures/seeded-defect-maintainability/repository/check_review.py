"""Deterministic verifier: did the actor's review flag the planted defect?

Unlike the other seeded-defect fixtures, this one is a pure maintainability
nit: the logic is correct, just hard to follow. A reviewer that records it as
a non-blocking finding and still recommends READY_FOR_HUMAN_APPROVAL is
behaving correctly per this repository's review conventions - do not require
`blocking: true` or a CHANGES_REQUIRED decision here.
"""

from __future__ import annotations

import json
import sys

EXPECTED_LOCATION_HINT = "changed/module.py"
EXPECTED_KEYWORDS = (
    "nest",
    "guard clause",
    "early return",
    "pyramid",
    "simplif",
)


def main() -> int:
    try:
        with open("review.json", encoding="utf-8") as handle:
            review = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"cannot read review.json: {error}", file=sys.stderr)
        return 1

    if review.get("decision") not in ("READY_FOR_HUMAN_APPROVAL", "CHANGES_REQUIRED"):
        print(
            f"unexpected decision {review.get('decision')!r} for a non-blocking nit",
            file=sys.stderr,
        )
        return 1

    findings = review.get("findings")
    if not isinstance(findings, list) or not findings:
        print("review.json must contain at least one finding", file=sys.stderr)
        return 1

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        haystack = " ".join(
            str(finding.get(field, "")) for field in ("location", "summary", "category")
        ).lower()
        if EXPECTED_LOCATION_HINT in haystack and any(
            keyword in haystack for keyword in EXPECTED_KEYWORDS
        ):
            print("found the planted defect")
            return 0

    print("no finding matched the planted defect", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
