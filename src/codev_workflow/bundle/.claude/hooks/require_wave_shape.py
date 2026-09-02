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
"""Pause when a save or an issue would break plan-wave's rolling-wave
discipline.

A shim. The decision lives in `codev gate check --gate wave-shape` so every
adapter enforces the same rule (see `src/codev_workflow/gate.py`); this file
only translates that answer into Claude Code's PreToolUse protocol and keeps
the local decision log.

Fails open on everything: a missing `codev` on PATH, a nonzero exit, a
timeout, or unparseable output all allow the tool call. A guardrail that
errors must never block work.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HOOK_NAME = "require_wave_shape.py"
_GATE = "wave-shape"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"


def _log_decision(
    repo_root: Path, decision: str, *, tool_name: str = "", reason: str = ""
) -> None:
    """Appends one local, gitignored record to `.codev/hooks/decisions.jsonl`.
    Never raises: a broken log must never change this guardrail's own
    allow/ask behavior."""
    try:
        record = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": _HOOK_NAME,
            "decision": decision,
            "tool_name": tool_name,
            "reason": reason,
        }
        path = repo_root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - logging must never affect the gate
        pass


def _allow() -> None:
    sys.exit(0)


def _ask(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def _decide(raw: str, repo_root: Path) -> dict[str, Any] | None:
    try:
        completed = subprocess.run(
            ["codev", "gate", "check", "--gate", _GATE, "--json"],
            cwd=repo_root,
            input=raw,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
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
        _allow()
        return
    if not isinstance(payload, dict):
        _allow()
        return

    repo_root = Path(payload.get("cwd") or Path.cwd())
    tool_name = str(payload.get("tool_name") or "")
    decision = _decide(raw, repo_root)
    if decision is None:
        # The gate could not be consulted at all -- most often `codev` is not
        # on PATH. Allowing is right; staying silent about it is not, because
        # a repository where every hook fails open looks exactly like one
        # with no guardrails configured.
        _log_decision(
            repo_root,
            "degraded",
            tool_name=tool_name,
            reason="`codev gate check` could not be run, so this tool call "
            "was allowed without being checked",
        )
        _allow()
        return
    reason = str(decision.get("reason") or "")
    verdict = decision.get("decision")
    if verdict == "ask":
        _log_decision(repo_root, "ask", tool_name=tool_name, reason=reason)
        _ask(reason)
        return
    if verdict == "degraded":
        _log_decision(repo_root, "degraded", tool_name=tool_name, reason=reason)
        _allow()
        return
    # `recorded` is false when the gate never applied -- an unwatched tool or
    # an unreadable payload. Logging those would count every unrelated tool
    # call as a guardrail allow.
    if decision.get("recorded", True):
        _log_decision(repo_root, "allow", tool_name=tool_name, reason=reason)
    _allow()


if __name__ == "__main__":
    main()
