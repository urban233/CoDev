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
"""Shared plumbing for every hook in this bundle, gate and advisory alike.

`require_plan.py`, `require_small_change.py`, and `require_wave_shape.py`
each translate one `codev gate check --gate <name>` verdict into Claude
Code's `PreToolUse` protocol, sharing `run_gate_hook` below. `restore_position.py`,
`checkpoint_state.py`, and `statusline.py` are not gates -- they carry no
allow/ask/degraded verdict -- but need the same `codev` CLI resolution, so
they share `codev_argv` and `codev_next` instead.

This module was `_gate_common.py` until this file was added: naming it for
"gate hooks" specifically stopped being accurate the moment a second kind
of hook needed the same CLI resolution, so it was renamed rather than left
to describe only half its callers.

Before either half existed, the CLI-resolution/decision-log translation was
copied identically into the three gate hooks; three independent copies
becoming five was the point that extraction was no longer optional.

Fails open on everything: an unreachable `codev`, a nonzero exit, a
timeout, or unparseable output all allow the tool call (or, for the
advisory half, simply produce no output). A guardrail that errors must
never block work. The two gate-side cases are recorded distinctly --
`infrastructure` for a CLI that genuinely is not reachable, `hook_error`
for one that answered unusably -- because only the second is a defect.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"

# Why a degraded gate happened, recorded so the two cases can be told apart.
# `infrastructure` is the legitimate fail-open: the CLI genuinely is not
# reachable from here. `hook_error` is a CLI that answered but could not be
# understood, which is a defect rather than an absence and should not be
# filed alongside it.
INFRASTRUCTURE = "infrastructure"
HOOK_ERROR = "hook_error"


def log_decision(
    repo_root: Path,
    hook_name: str,
    decision: str,
    *,
    tool_name: str = "",
    reason: str = "",
    failure_class: str = "",
) -> None:
    """Appends one local, gitignored record to `.codev/hooks/decisions.jsonl`.
    Never raises: a broken log must never change this guardrail's own
    allow/ask behavior."""
    try:
        record: dict[str, str] = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": hook_name,
            "decision": decision,
            "tool_name": tool_name,
            "reason": reason,
        }
        if failure_class:
            record["failure_class"] = failure_class
        path = repo_root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - logging must never affect the gate
        pass


def allow() -> None:
    sys.exit(0)


def ask(reason: str) -> None:
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


def codev_argv(repo_root: Path) -> list[str] | None:
    """The `codev` CLI, resolved without trusting `PATH` alone.

    A hook runs under whatever interpreter and environment the host hands
    it, which is often not the shell `codev` was installed into. When a bare
    name misses, every gate allows everything and the session is never told:
    this repository's own decision log recorded 508 of 1,112 calls deciding
    nothing for exactly that reason. Candidates are ordered most-specific
    first and none of them has to spawn a process to be discovered.

    Returns None only when no candidate exists at all, which is the one
    genuinely infrastructural reason to fail open.
    """
    override = os.environ.get("CODEV_CLI", "").strip()
    if override:
        # posix=False on Windows: the POSIX lexer treats a backslash as an
        # escape, which silently mangles every native path it is given. It
        # also keeps the quotes it split on, and an argv[0] carrying literal
        # quote characters cannot be executed -- so strip a matched pair.
        tokens = shlex.split(override, posix=os.name != "nt")
        if os.name == "nt":
            tokens = [
                token[1:-1]
                if len(token) > 1 and token[0] == token[-1] == '"'
                else token
                for token in tokens
            ]
        return tokens
    try:
        if importlib.util.find_spec("codev_workflow") is not None:
            # -P keeps the script's own directory and cwd off sys.path. The
            # hook runs with cwd set to the repository being gated, so
            # without it a `codev_workflow.py` committed at a repo root
            # would both execute and decide this gate's own verdict.
            return [sys.executable, "-P", "-m", "codev_workflow"]
    except (ImportError, ValueError):
        pass
    for relative in (".venv/bin/codev", ".venv/Scripts/codev.exe"):
        candidate = repo_root / relative
        if candidate.exists():
            return [str(candidate)]
    found = shutil.which("codev")
    if found:
        return [found]
    return None


def decide_gate(
    raw: str, repo_root: Path, gate: str
) -> tuple[dict[str, Any] | None, str]:
    """The gate's answer, or None plus the reason it could not be obtained."""
    argv = codev_argv(repo_root)
    if argv is None:
        return None, INFRASTRUCTURE
    try:
        completed = subprocess.run(
            [*argv, "gate", "check", "--gate", gate, "--json"],
            cwd=repo_root,
            input=raw,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, INFRASTRUCTURE
    if completed.returncode != 0:
        return None, HOOK_ERROR
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, HOOK_ERROR
    if not isinstance(parsed, dict):
        return None, HOOK_ERROR
    return parsed, ""


def run_gate_hook(hook_name: str, gate: str) -> None:
    """The shared `PreToolUse` body every gate hook's `main()` delegates to."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        allow()
        return
    if not isinstance(payload, dict):
        allow()
        return

    repo_root = Path(payload.get("cwd") or Path.cwd())
    tool_name = str(payload.get("tool_name") or "")
    decision, failure_class = decide_gate(raw, repo_root, gate)
    if decision is None:
        # The gate could not be consulted at all -- most often `codev` is not
        # on PATH. Allowing is right; staying silent about it is not, because
        # a repository where every hook fails open looks exactly like one
        # with no guardrails configured.
        log_decision(
            repo_root,
            hook_name,
            "degraded",
            tool_name=tool_name,
            reason="`codev gate check` could not be run, so this tool call "
            "was allowed without being checked",
            failure_class=failure_class,
        )
        allow()
        return
    reason = str(decision.get("reason") or "")
    verdict = decision.get("decision")
    if verdict == "ask":
        log_decision(repo_root, hook_name, "ask", tool_name=tool_name, reason=reason)
        ask(reason)
        return
    if verdict == "degraded":
        # The gate answered, and its answer was that it could not decide.
        # Carry its own classification through rather than dropping it: an
        # internal error filed as though the tooling were merely absent is
        # how this class of hole stays invisible.
        log_decision(
            repo_root,
            hook_name,
            "degraded",
            tool_name=tool_name,
            reason=reason,
            failure_class=str(decision.get("failure_class") or ""),
        )
        allow()
        return
    # `recorded` is false when the gate never applied -- an unwatched tool or
    # an unreadable payload. Logging those would count every unrelated tool
    # call as a guardrail allow.
    if decision.get("recorded", True):
        log_decision(repo_root, hook_name, "allow", tool_name=tool_name, reason=reason)
    allow()


def codev_next(repo_root: Path, *, timeout: float = 30) -> dict[str, object] | None:
    """`codev next --json --no-github`'s own report, or None if it could not
    be run.

    Shared by `restore_position.py`, `checkpoint_state.py`, and
    `statusline.py` -- the three advisory (non-gate) hooks in this bundle,
    each of which needs this exact call and previously each defined its own
    copy. `--no-github`: every caller here fires at a session boundary or on
    a `statusLine` refresh cadence and must be fast and offline-safe;
    `codev next --json` alone would check GitHub for most positions, which
    is exactly the network dependency none of these three should carry.
    """
    argv = codev_argv(repo_root)
    if argv is None:
        return None
    try:
        completed = subprocess.run(
            [*argv, "next", "--json", "--no-github"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
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
