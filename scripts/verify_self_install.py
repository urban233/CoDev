#!/usr/bin/env python3
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
"""Fail if this repository's own root dogfood install has drifted from its
bundle source -- see docs/features/production-readiness/brief.md.

This repository installs CoDev on itself (`.claude/`, `.opencode/`,
`.agents/skills/`, `.codev/for-ai/`, ...), the same as any adopter. That
root install went unnoticed out of sync with `src/codev_workflow/bundle/`
for over a week before a routine feature landed and had to resync it by
hand -- the exact failure mode this script exists to catch immediately
instead.

Runs `codev diff --target .` against this repository itself and fails
loudly on anything but "No changes." Unlike
scripts/verify_claude_code_compat.py, this needs no network access -- both
sides of the comparison are already checked out -- so it runs on every push
and pull request (see .github/workflows/ci.yml), not only on a schedule.

Calls `codev_workflow.cli.main()` in-process rather than shelling out to a
bare `codev` on `PATH`: a developer machine can have an unrelated, globally
installed CoDev release (for example via `uv tool install`) that silently
shadows this repository's own editable dev install and reports drift
against the wrong version entirely -- confirmed the hard way while writing
this script. Importing the package this script's own interpreter already
has guarantees there is no ambiguity about which CoDev is being checked.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from codev_workflow.cli import main as codev_main

_NO_CHANGES = "No changes."


def verify(repo_root: Path) -> int:
    output = io.StringIO()
    with redirect_stdout(output):
        codev_main(["diff", "--target", str(repo_root)])
    stdout = output.getvalue()
    print(stdout, end="")

    if _NO_CHANGES in stdout:
        return 0

    print(
        "\nThis repository's own root install has drifted from bundle source "
        "(see above). Review the diff, then run:\n"
        "  codev update --target . --on-conflict override\n"
        "or resolve conflicts individually with --resolve.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    return verify(Path(__file__).resolve().parent.parent)


if __name__ == "__main__":
    raise SystemExit(main())
