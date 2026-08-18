# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
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
