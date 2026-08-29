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
"""Deterministic verifier: did the actor design a well-formed, honest fixture?

Unlike a seeded-defect fixture, there is no single expected output value --
the actor's task is to produce a whole new fixture (its own fixture.json,
prompt.md, verifier.json, rubric.md, repository/) for the toy `greet-user`
skill seeded alongside this script. This checks the parts of "well-formed"
that are actually mechanical: it validates as a real fixture, it is tagged
for the right skill, and its prompt does not name the skill under test --
the one concrete, non-obvious rule this whole eval corpus depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from codev_workflow.eval import EvaluationError, validate_fixture
except ImportError as error:
    print(f"cannot import codev_workflow: {error}", file=sys.stderr)
    print(
        "this verifier must run under the same interpreter as CoDev itself",
        file=sys.stderr,
    )
    sys.exit(1)

TARGET_SKILL = "greet-user"
PLACEHOLDER_CATEGORY = "replace-with-category"


def main() -> int:
    candidates = sorted(Path(".codev/fixtures").glob("*/fixture.json"))
    if len(candidates) != 1:
        print(
            "expected exactly one new fixture under .codev/fixtures, found "
            f"{len(candidates)}",
            file=sys.stderr,
        )
        return 1
    fixture_dir = candidates[0].parent

    try:
        fixture = validate_fixture(fixture_dir)
    except EvaluationError as error:
        print(f"new fixture at {fixture_dir} is not valid: {error}", file=sys.stderr)
        return 1

    if fixture.skill != TARGET_SKILL:
        print(
            f"fixture.json skill must be {TARGET_SKILL!r}, got {fixture.skill!r}",
            file=sys.stderr,
        )
        return 1
    if not fixture.category or fixture.category == PLACEHOLDER_CATEGORY:
        print(
            "fixture.json category was left as the scaffold placeholder",
            file=sys.stderr,
        )
        return 1

    prompt_text = fixture.prompt.decode("utf-8", errors="replace").lower()
    if TARGET_SKILL in prompt_text or "greet_user" in prompt_text:
        print(
            f"prompt.md names the skill under test ({TARGET_SKILL!r}); the "
            "prompt must describe the task on its own terms so staging the "
            "skill is the only thing that differs between conditions",
            file=sys.stderr,
        )
        return 1

    print(
        "new fixture is valid, tagged for "
        f"{TARGET_SKILL!r}/{fixture.category!r}, and does not name the "
        "skill under test"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
