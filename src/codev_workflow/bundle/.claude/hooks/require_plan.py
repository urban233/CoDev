#!/usr/bin/env python3
"""CoDev's plan-first guardrail: a Claude Code PreToolUse hook.

Pauses for human confirmation before the first source edit, or the first
repository-mutating git command, of a session when no spec/plan document can
be found for the active branch -- see
docs/features/claude-code/design.md's "Guardrail Design" section. It only
ever asks; it never denies, and it fails open (allows) on any internal
error, so a bug here degrades to "no guardrail", never to "no edits
possible".

Two independent checks decide whether a spec exists, either is sufficient:

1. Precise: if the branch follows CoDev's own `codev/<task-id>` convention
   (`git_ops.branch_name_for`), look for that exact task's own plan at
   `docs/codev/task/<task-id>/implementation-plan.md`
   (`.agents/skills/build-change/SKILL.md`'s convention).
2. Coarse fallback: a repo-wide, branch-name-substring match against
   `docs/features/*/design.md`, `docs/codev/features/*/design.md`, or
   `docs/codev/wave/*.md`, for planning work that predates a `codev task
   start` (e.g. still drafting a brief/design/wave plan) or a branch that
   never went through `codev git branch`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HOOK_NAME = "require_plan.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"

_GATED_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Mirrors ADR-0002's raw-mutation list -- the same commands OpenCode's
# `builder` subagent already denies outright in favor of the guarded `codev
# git` surface (bundle/.opencode/agents/builder.md). Prefix matching, not a
# full shell parse: a chained command ("git status && git commit ...")
# after the first `&&`/`;`/`|` is a known, accepted gap for this heuristic,
# not a security boundary -- see design.md's Quality and Risk.
_DESTRUCTIVE_BASH_PREFIXES = (
    "git commit",
    "git push",
    "git merge",
    "git reset",
    "git checkout",
    "git clean",
    "git rebase",
    "rm -rf",
    "rm -r ",
)

_TASK_BRANCH_PREFIX = "codev/"  # must match git_ops.branch_name_for()
_TASK_PLAN_TEMPLATE = "docs/codev/task/{task_id}/implementation-plan.md"
_SPEC_GLOBS = (
    "docs/features/*/design.md",
    "docs/codev/features/*/design.md",
    "docs/codev/wave/*.md",
)
_UNGATED_BRANCHES = {"main", "master", "HEAD"}


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


def _gate_reason(payload: dict[str, Any]) -> str | None:
    """Returns why this call is gated, or None if it should be allowed
    without any further check."""
    tool_name = payload.get("tool_name")
    if tool_name in _GATED_EDIT_TOOLS:
        return "edit"
    if tool_name == "Bash":
        tool_input = payload.get("tool_input")
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or "").strip()
        if any(command.startswith(prefix) for prefix in _DESTRUCTIVE_BASH_PREFIXES):
            return "bash"
    return None


def _current_branch(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _has_precise_task_plan(repo_root: Path, branch: str) -> bool:
    if not branch.startswith(_TASK_BRANCH_PREFIX):
        return False
    task_id = branch[len(_TASK_BRANCH_PREFIX) :]
    if not task_id:
        return False
    plan = repo_root / _TASK_PLAN_TEMPLATE.format(task_id=task_id)
    return plan.is_file()


def _branch_slug(branch: str) -> str:
    tail = branch.rsplit("/", 1)[-1]
    return tail.strip().lower()


def _has_matching_spec(repo_root: Path, slug: str) -> bool:
    for pattern in _SPEC_GLOBS:
        for match in repo_root.glob(pattern):
            # docs/features/*/design.md and docs/codev/features/*/design.md
            # carry the slug in the parent directory; docs/codev/wave/*.md
            # carries it in the filename itself -- check both rather than
            # assuming one convention for every glob.
            candidates = {match.parent.name.lower(), match.stem.lower()}
            if slug and any(
                slug in candidate or candidate in slug for candidate in candidates
            ):
                return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _allow()
        return

    if not isinstance(payload, dict):
        _allow()
        return

    gate_reason = _gate_reason(payload)
    if gate_reason is None:
        _allow()
        return

    tool_input = payload.get("tool_input")
    tool_name = str(payload.get("tool_name") or "")
    file_path = ""
    if gate_reason == "edit" and isinstance(tool_input, dict):
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    repo_root = Path(payload.get("cwd") or Path.cwd())

    try:
        if file_path:
            candidate = Path(file_path)
            relative = (
                candidate.relative_to(repo_root)
                if candidate.is_absolute()
                else candidate
            )
            if relative.parts and relative.parts[0] == "docs":
                _log_decision(repo_root, "allow", tool_name=tool_name, reason="docs")
                _allow()
                return

        branch = _current_branch(repo_root)
        if not branch or branch in _UNGATED_BRANCHES:
            _log_decision(
                repo_root, "allow", tool_name=tool_name, reason="ungated-branch"
            )
            _allow()
            return

        if _has_precise_task_plan(repo_root, branch):
            _log_decision(
                repo_root, "allow", tool_name=tool_name, reason="precise-task-plan"
            )
            _allow()
            return

        slug = _branch_slug(branch)
        if _has_matching_spec(repo_root, slug):
            _log_decision(
                repo_root, "allow", tool_name=tool_name, reason="coarse-spec-match"
            )
            _allow()
            return

        if gate_reason == "bash":
            reason = (
                "This looks like a repository-mutating git command, and no "
                "design/plan doc or recorded task plan was found for this "
                "branch. If this is an intentional, already-discussed step, "
                "approve and continue -- otherwise consider design-solution "
                "or build-change first."
            )
        else:
            reason = (
                "No design/plan doc or recorded task plan was found for "
                "this branch. If this is intentionally a small, spec-free "
                "change, approve and continue -- otherwise consider "
                "design-solution or build-change first."
            )
        _log_decision(repo_root, "ask", tool_name=tool_name, reason=reason)
        _ask(reason)
    except Exception as error:  # noqa: BLE001 - guardrail must fail open
        print(f"require_plan.py: internal error, allowing: {error}", file=sys.stderr)
        _allow()


if __name__ == "__main__":
    main()
