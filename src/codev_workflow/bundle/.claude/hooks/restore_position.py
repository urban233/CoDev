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
"""Surface `codev next`'s current position at every session start, so a
developer -- or the agent itself -- never has to ask "what was I doing".

E11 (docs/plans/claude-code-adapter-verification-first.md) is the strongest
quantitative finding in the parent plan's research pass: novices recover
from a derailed session 4% of the time versus 15-16% for experts, and the
gap is specifically about recovery, not generation. This fires on every
`SessionStart` -- a fresh launch, a `/clear`, a `--resume`, or the
`SessionStart` that follows a compaction -- because a developer returning to
their own code after a funding or publication gap needs the same
reorientation a fresh launch does.

On the `compact` source specifically, also folds in whatever
`checkpoint_state.py` wrote to this session's `scratchpad_dir` just before
compaction, since `codev next` alone cannot recover anything compaction
itself may have quietly dropped from the conversation. This is a smaller
guarantee than that sounds: the checkpoint is machine-readable task/plan
state, not a general capture of every mid-session decision.

Fails open (no output, never a block) on unreachable `codev`, a nonzero
exit, a timeout, or unparseable output -- this is advisory context for
Claude, never a gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hook_common  # noqa: E402

_HOOK_NAME = "restore_position.py"
_CHECKPOINT_FILENAME = "checkpoint.json"


def _checkpoint(scratchpad_dir: str) -> dict[str, object] | None:
    """The last position `checkpoint_state.py` wrote before a compaction, or
    None when there is none -- most sessions never compact."""
    if not scratchpad_dir:
        return None
    path = Path(scratchpad_dir) / _CHECKPOINT_FILENAME
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _message(position: dict[str, object]) -> str:
    lines = [f"CoDev position: {position.get('position')}"]
    recommendation = position.get("recommendation")
    if recommendation:
        lines.append(f"Recommended next step: {recommendation}")
    reason = position.get("reason")
    if reason:
        lines.append(f"Why: {reason}")
    return "\n".join(lines)


def _system_message(message: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "systemMessage": message,
            }
        },
        sys.stdout,
    )


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(payload, dict):
        return

    repo_root = Path(payload.get("cwd") or Path.cwd())
    position = _hook_common.codev_next(repo_root)
    if position is None and payload.get("source") == "compact":
        # `codev` itself may be briefly unreachable right after a
        # compaction; the checkpoint is a second, independent path to the
        # same information for exactly that case.
        position = _checkpoint(str(payload.get("scratchpad_dir") or ""))
    if position is None:
        return
    _system_message(_message(position))


if __name__ == "__main__":
    main()
