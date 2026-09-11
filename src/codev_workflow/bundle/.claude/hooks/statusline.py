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
"""One line: branch, slice, round, and context used -- the meter several
first-hand reports (docs/plans/claude-code-adapter-verification-first.md,
E12) said they had to build for themselves.

`codev next --json --no-github` supplies branch, slice, and the round
(embedded in its `position` string, e.g. "inner phase, round 18" -- there
is no separate round field). The implementation plan proposed reading
`.codev/task/*/round-state.json` directly instead, as a cheaper shortcut;
measured at ~0.13s on this repository (2026-09-11), the subprocess call is
negligible even at a `statusLine` refresh cadence, and going through the
same stable, versioned JSON contract every other hook already uses is
worth more than the shortcut would have saved. `context_window.used_percentage`
comes directly from this hook's own stdin payload -- Claude Code
precalculates it, so no token counting of any kind happens here.

Fails open to a minimal line (never no line, never a traceback) on
unreachable `codev`, a nonzero exit, a timeout, or unparseable output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gate_common  # noqa: E402


def _position(repo_root: Path) -> dict[str, object] | None:
    argv = _gate_common.codev_argv(repo_root)
    if argv is None:
        return None
    try:
        completed = subprocess.run(
            [*argv, "next", "--json", "--no-github"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode not in (0, 1):  # 1: `next` itself reports blocked
        return None
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _context_used_percentage(payload: dict[str, object]) -> str | None:
    context_window = payload.get("context_window")
    if not isinstance(context_window, dict):
        return None
    used = context_window.get("used_percentage")
    if not isinstance(used, (int, float)):
        return None
    return f"{used:.0f}% context"


def _line(payload: dict[str, object], repo_root: Path) -> str:
    parts: list[str] = []
    action = _position(repo_root)
    if action is not None:
        # slice_id, not the full branch name: `slice_id` is the short,
        # at-a-glance identifier; the branch it is part of
        # (codev/<task>--<slice>) is usually longer than the rest of this
        # line combined. Falls back to branch for a position with no active
        # slice (e.g. still at the repo-wide planning stage).
        identifier = action.get("slice_id") or action.get("branch")
        # `position` (e.g. "inner phase, round 18") already carries the
        # round -- `NextAction` has no separate round field, and adding a
        # second `codev` call just to extract one would cost more than the
        # line is worth.
        position = action.get("position")
        if identifier:
            parts.append(str(identifier))
        if position:
            parts.append(str(position))
    context = _context_used_percentage(payload)
    if context is not None:
        parts.append(context)
    return " | ".join(parts) if parts else "CoDev"


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print("CoDev")
        return
    if not isinstance(payload, dict):
        print("CoDev")
        return
    repo_root = Path(str(payload.get("cwd") or Path.cwd()))
    print(_line(payload, repo_root))


if __name__ == "__main__":
    main()
