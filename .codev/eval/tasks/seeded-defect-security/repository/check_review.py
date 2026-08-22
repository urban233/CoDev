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
"""Deterministic verifier: did the actor's review flag the planted defect?"""

from __future__ import annotations

import json
import sys

EXPECTED_LOCATION_HINT = "changed/module.py"
EXPECTED_KEYWORDS = (
    "sql injection",
    "sql-injection",
    "parameteriz",
    "f-string",
    "string interpolation",
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
