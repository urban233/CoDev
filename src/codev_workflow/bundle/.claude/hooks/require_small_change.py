#!/usr/bin/env python3
"""CoDev's small-change guardrail: a Claude Code PreToolUse hook.

Pauses for human confirmation before `codev git open-pr` runs for a task
whose non-generated diff exceeds its `review.max_lines`/`review.max_files`
budget -- see docs/features/small-prs/design.md's "Proposed design" and
"Quality and risk" sections. It only ever asks; it never denies, and it
fails open (allows) on any internal error -- an unresolvable task id, a
`codev` invocation that fails, or unparseable output -- so a bug here
degrades to "no extra check", never to "no pull request possible".

Reuses `codev task size --id <id> --json` (`git_ops.task_size`) rather than
reimplementing the measurement: this hook is a thin trigger over the same
number `codev git commit`/`codev git open-pr` already print, one CoDev
already computes correctly against `.gitattributes` and its own task-state
exclusions. `codev` must be resolvable on PATH in the hook's own execution
environment; when it is not, this fails open exactly like any other
internal error.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HOOK_NAME = "require_small_change.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"

_OPEN_PR_PREFIX = "codev git open-pr"
_TASK_ID_PATTERN = re.compile(r"--id[= ]+(\S+)")


def _log_decision(
    repo_root: Path, decision: str, *, tool_name: str = "", reason: str = ""
) -> None:
    """Appends one local, gitignored record to `.codev/hooks/decisions.jsonl`
    -- see docs/features/production-readiness/brief.md. Never raises: a
    broken log must never change this guardrail's own allow/ask behavior."""
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


def _open_pr_task_id(payload: dict[str, Any]) -> str | None:
    """The task id of a `codev git open-pr` Bash call, or None when this
    call isn't one, or the id can't be found -- prefix matching, not a
    full shell parse, the same heuristic require_plan.py's gated-command
    check already accepts (see its own module docstring)."""
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "").strip()
    if not command.startswith(_OPEN_PR_PREFIX):
        return None
    match = _TASK_ID_PATTERN.search(command)
    return match.group(1) if match else None


def _task_size(task_id: str, *, repo_root: Path) -> dict[str, Any] | None:
    """Runs `codev task size --id <id> --json` in repo_root and returns its
    parsed payload, or None on any failure -- a missing `codev` on PATH, a
    nonzero exit, a timeout, or unparseable output all fail open here."""
    try:
        completed = subprocess.run(
            ["codev", "task", "size", "--id", task_id, "--json"],
            cwd=repo_root,
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
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _allow()
        return

    if not isinstance(payload, dict):
        _allow()
        return

    repo_root = Path(payload.get("cwd") or Path.cwd())

    try:
        task_id = _open_pr_task_id(payload)
        if task_id is None:
            _allow()
            return

        size = _task_size(task_id, repo_root=repo_root)
        if size is None:
            _log_decision(
                repo_root,
                "allow",
                tool_name="Bash",
                reason="size measurement unavailable",
            )
            _allow()
            return

        if not size.get("over_budget"):
            _log_decision(repo_root, "allow", tool_name="Bash", reason="within-budget")
            _allow()
            return

        reason = (
            f"{task_id!r}'s diff is {size.get('lines_changed')} non-generated "
            f"line(s) (budget {size.get('max_lines')}) and "
            f"{size.get('files_changed')} file(s) (budget {size.get('max_files')}) "
            "-- over budget. If this is intentional, approve and continue; "
            "otherwise consider splitting further first (see the plan's "
            "Slices field)."
        )
        _log_decision(repo_root, "ask", tool_name="Bash", reason=reason)
        _ask(reason)
    except Exception as error:  # noqa: BLE001 - guardrail must fail open
        print(
            f"require_small_change.py: internal error, allowing: {error}",
            file=sys.stderr,
        )
        _allow()


if __name__ == "__main__":
    main()
