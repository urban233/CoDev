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
"""What is quietly not working.

CoDev fails open nearly everywhere, and each instance is right on its own: a
guardrail that errors must not block a developer, and a measurement that
cannot be taken must not block a commit. Collectively they mean CoDev can be
substantially broken and still look fine -- a missing `codev` on PATH makes
every hook fail open, so all three guardrails stop existing and nothing says
so.

This module draws the line the rest of the codebase already knows how to
draw in one place: the navigator distinguishes "approved" from "not approved"
from "GitHub could not be asked", and only the middle one is a reason to
wait. Everything degraded should be as legible as that.

Nothing here blocks anything. It reports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codev_workflow import hook_log


@dataclass(frozen=True)
class Finding:
    """One capability that is silently not working, and what it costs."""

    name: str
    ok: bool
    detail: str
    impact: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "impact": self.impact,
        }


_DISABLES_EVERY_GUARDRAIL = (
    "every guardrail hook fails open, so plan-first, wave-shape and "
    "change-size stop being enforced without reporting anything"
)


def _codev_usable(target: Path) -> Finding:
    """Every hook shells out to `codev gate check` and fails open on any
    failure.

    Checking that a `codev` binary exists is not enough, and assuming it is
    hides the more likely fault. A globally installed older release shadows a
    development checkout perfectly happily, answers `gate check` with an
    unknown-command error, and every guardrail fails open exactly as if
    nothing were installed at all. Ask the binary whether it can do the thing
    the hooks need, not whether it is there.
    """
    resolved = shutil.which("codev")
    if resolved is None:
        return Finding(
            "codev-usable", False, "`codev` is not on PATH", _DISABLES_EVERY_GUARDRAIL
        )
    # Probe without PYTHONPATH. The `codev` console script imports whatever
    # `codev_workflow` its interpreter can see, so inheriting a developer's
    # PYTHONPATH makes an installed release appear to have commands that only
    # exist in their checkout -- a falsely healthy answer, and precisely
    # backwards, since the hooks run from the agent's environment rather than
    # from a shell with a development path set.
    environment = {
        key: value for key, value in os.environ.items() if key != "PYTHONPATH"
    }
    try:
        completed = subprocess.run(
            ["codev", "gate", "check", "--gate", "plan"],
            cwd=target,
            input="{}",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Finding("codev-usable", False, str(error), _DISABLES_EVERY_GUARDRAIL)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return Finding(
            "codev-usable",
            False,
            f"{resolved} cannot run `gate check`: "
            f"{detail[-1] if detail else 'unknown error'}",
            _DISABLES_EVERY_GUARDRAIL
            + " -- most often the `codev` on PATH is an older release than "
            "the bundle installed here",
        )
    return Finding("codev-usable", True, f"{resolved} answers `gate check`", "")


def _gh_available(target: Path) -> Finding:
    if shutil.which("gh") is None:
        return Finding(
            "gh-available",
            False,
            "`gh` is not on PATH",
            "pull-request state and human approvals cannot be read, so "
            "`codev next` reports what it cannot determine rather than where "
            "the work stands",
        )
    try:
        completed = subprocess.run(
            ["gh", "auth", "status"],
            cwd=target,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Finding("gh-available", False, str(error), "as above")
    if completed.returncode != 0:
        return Finding(
            "gh-available",
            False,
            "`gh` is present but not authenticated",
            "pull-request state and human approvals cannot be read",
        )
    return Finding("gh-available", True, "authenticated", "")


def _hooks_wired(target: Path) -> Finding:
    """A settings file naming a hook script that is not there fails open on
    every tool call, which looks exactly like a repository with no hooks."""
    settings = target / ".claude" / "settings.json"
    if not settings.exists():
        return Finding(
            "hooks-wired", True, "no Claude Code hook settings installed", ""
        )
    try:
        parsed = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return Finding(
            "hooks-wired",
            False,
            f"{settings} cannot be read: {error}",
            "the guardrails configured there may not run at all",
        )
    missing = []
    for entry in parsed.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            command = str(hook.get("command", ""))
            for token in command.replace('"', " ").split():
                if token.endswith(".py"):
                    script = token.replace("${CLAUDE_PROJECT_DIR}", str(target))
                    if not Path(script).exists():
                        missing.append(token)
    if missing:
        return Finding(
            "hooks-wired",
            False,
            "configured hook script(s) not found: " + ", ".join(sorted(set(missing))),
            "those guardrails never run, and nothing reports their absence",
        )
    return Finding("hooks-wired", True, "every configured hook script exists", "")


def _gates_failing_open(target: Path) -> Finding:
    """A gate that answered `degraded` decided nothing -- it could not
    check. Counting those separately is the difference between a guardrail
    that passed and one that never ran."""
    decisions = hook_log.read_decisions(target=target)
    degraded = [record for record in decisions if record.get("decision") == "degraded"]
    if not degraded:
        return Finding("gates-deciding", True, "no gate has failed open", "")
    hooks = sorted({str(record.get("hook", "?")) for record in degraded})
    return Finding(
        "gates-deciding",
        False,
        f"{len(degraded)} gate call(s) failed open, from: {', '.join(hooks)}",
        "those tool calls were allowed without being checked",
    )


def inspect(*, target: Path) -> list[Finding]:
    """Every health check, in the order a developer should read them."""
    return [
        _codev_usable(target),
        _gh_available(target),
        _hooks_wired(target),
        _gates_failing_open(target),
    ]


def degraded(*, target: Path) -> list[Finding]:
    return [finding for finding in inspect(target=target) if not finding.ok]
