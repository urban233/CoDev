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
"""Write `codev next`'s position to this session's scratchpad before a
compaction, so `restore_position.py` has a second, independent way to
recover it if `codev` itself is briefly unreachable right afterward.

Targets the E12 incident class (docs/plans/claude-code-adapter-verification-first.md)
where state a session was tracking quietly disappears across a compaction
boundary. This is deliberately a narrower guarantee than that incident
class implies: it captures machine-readable task/plan position, not a
general capture of every rule or constraint established mid-conversation,
which would need to parse the transcript rather than shell out to `codev`.

Writes to `scratchpad_dir`, not `.codev/`: both `PreCompact` and the
`SessionStart` that follows compaction receive the same `scratchpad_dir` in
their payload, and it already lives outside the repository, so this needs
no gitignore entry of its own.

Fails open (writes nothing, never blocks) on unreachable `codev`, a nonzero
exit, a timeout, unparseable output, or an unwritable scratchpad -- this is
best-effort context for a later hook, never a gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gate_common  # noqa: E402

_CHECKPOINT_FILENAME = "checkpoint.json"


def _next_position(repo_root: Path) -> dict[str, object] | None:
    argv = _gate_common.codev_argv(repo_root)
    if argv is None:
        return None
    try:
        completed = subprocess.run(
            # --no-github: a PreCompact hook must be fast and offline-safe;
            # see the same note in restore_position.py.
            [*argv, "next", "--json", "--no-github"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
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


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return

    scratchpad_dir = str(payload.get("scratchpad_dir") or "")
    if not scratchpad_dir:
        return
    repo_root = Path(payload.get("cwd") or Path.cwd())
    position = _next_position(repo_root)
    if position is None:
        return
    try:
        path = Path(scratchpad_dir) / _CHECKPOINT_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(position, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    main()
