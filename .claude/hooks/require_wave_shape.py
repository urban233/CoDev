#!/usr/bin/env python3
"""CoDev's wave-shape guardrail: a Claude Code PreToolUse hook.

Pauses for human confirmation before a wave-plan document is saved with a
populated task table in a "Later waves" section, or before `codev git
issue-create` runs while any wave-plan document is in that state -- see
docs/features/plan-wave/design.md's "Proposed design" and "Quality and
risk" sections. It only ever asks; it never denies, and it fails open
(allows) on any internal error, so a bug here degrades to "no extra
check", never to "no edits or issue creation possible".

This check is deliberately coarse, the same way require_plan.py's own
spec-exists check is: it asks whether *a* wave-plan document is
well-formed, not whether the specific edit or issue-create call in front
of it targets a later wave -- see design.md's Alternatives and trade-offs
for why a per-issue-precise check was rejected for this release.

Checks `Write`, `Edit`, and `MultiEdit` calls against a wave-plan path,
using the content the file would have *after* the call -- for `Write` that
is the proposed content directly; for `Edit`/`MultiEdit` it is the file's
current on-disk content with the edit(s) applied, mirroring the real Edit
tool's own refusal conditions (no-op when old_string == new_string or is
absent) rather than guessing past them. `MultiEdit`'s exact payload shape
is `[unverified]` -- confirmed as a real Claude Code tool name by
docs/features/claude-code/design.md's Phase 0 binary inspection, but never
confirmed field-by-field against a live payload; an unexpected shape falls
through to allow (fail open) rather than checking it incorrectly. See
docs/codev/wave/production-readiness.md's Risks and discovery for the open
item to confirm this against a real session. The `codev git issue-create`
trigger is the backstop that still catches a violation however it was
introduced.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HOOK_NAME = "require_wave_shape.py"
_DECISIONS_LOG_RELATIVE = ".codev/hooks/decisions.jsonl"

_GATED_CONTENT_TOOLS = {"Write", "Edit", "MultiEdit"}
_ISSUE_CREATE_PREFIX = "codev git issue-create"
_WAVE_PLAN_GLOB = "docs/codev/wave/*.md"
_LATER_WAVES_HEADING = "## Later waves"


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


def _later_waves_section_lines(text: str) -> list[str]:
    """Returns the lines of the "## Later waves" section, or an empty list
    if the document has no such heading. Stops at the next "## " heading."""
    section: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.strip() == _LATER_WAVES_HEADING:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            section.append(line)
    return section


def _has_populated_task_table(section_lines: list[str]) -> bool:
    """A markdown table row starts with "|". The wave-plan template's own
    explanatory HTML comment inside this section never does, so no
    special-casing is needed for it."""
    return any(line.strip().startswith("|") for line in section_lines)


def _relative(path: Path, repo_root: Path) -> Path:
    return path.relative_to(repo_root) if path.is_absolute() else path


def _wave_plan_violation(repo_root: Path) -> Path | None:
    """Returns the first wave-plan document (by sorted path) with a
    populated task table in its "Later waves" section, or None if every
    wave-plan document -- if any exist at all -- is well-formed."""
    for match in sorted(repo_root.glob(_WAVE_PLAN_GLOB)):
        try:
            text = match.read_text(encoding="utf-8")
        except OSError:
            continue
        if _has_populated_task_table(_later_waves_section_lines(text)):
            return match
    return None


def _apply_edit(
    content: str, old_string: str, new_string: str, replace_all: bool
) -> str | None:
    """Applies one Edit-style replacement to content. Returns None (not
    applicable) when old_string equals new_string or is absent from
    content, mirroring the real Edit tool's own refusal conditions rather
    than guessing past them."""
    if old_string == new_string or old_string not in content:
        return None
    if replace_all:
        return content.replace(old_string, new_string)
    return content.replace(old_string, new_string, 1)


def _target_content_after_edit(
    payload: dict[str, Any], repo_root: Path
) -> tuple[Path, str] | None:
    """For a Write/Edit/MultiEdit call targeting a wave-plan path, returns
    (path, the content that path would have after this call). Returns None
    for any other call, or when the resulting content can't be determined
    -- this only ever inspects a wave-plan document's own content, never an
    unrelated file's, and never guesses past an unexpected payload shape."""
    tool_name = payload.get("tool_name")
    if tool_name not in _GATED_CONTENT_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if not file_path:
        return None
    candidate = Path(file_path)
    relative = _relative(candidate, repo_root)
    if not relative.match(_WAVE_PLAN_GLOB):
        return None

    if tool_name == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            return None
        return candidate, content

    try:
        current = candidate.read_text(encoding="utf-8")
    except OSError:
        return None

    if tool_name == "Edit":
        old_string = tool_input.get("old_string")
        new_string = tool_input.get("new_string")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return None
        result = _apply_edit(
            current, old_string, new_string, bool(tool_input.get("replace_all"))
        )
        return (candidate, result) if result is not None else None

    # MultiEdit -- [unverified] payload shape, see module docstring. An
    # unexpected shape returns None here, which falls through to allow.
    edits = tool_input.get("edits")
    if not isinstance(edits, list) or not edits:
        return None
    for edit in edits:
        if not isinstance(edit, dict):
            return None
        old_string = edit.get("old_string")
        new_string = edit.get("new_string")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return None
        result = _apply_edit(
            current, old_string, new_string, bool(edit.get("replace_all"))
        )
        if result is None:
            return None
        current = result
    return candidate, current


def _is_issue_create(payload: dict[str, Any]) -> bool:
    if payload.get("tool_name") != "Bash":
        return False
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "").strip()
    return command.startswith(_ISSUE_CREATE_PREFIX)


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
        edit_target = _target_content_after_edit(payload, repo_root)
        if edit_target is not None:
            tool_name = str(payload.get("tool_name") or "")
            _, content = edit_target
            if _has_populated_task_table(_later_waves_section_lines(content)):
                reason = (
                    "This save leaves a populated task table in a 'Later "
                    "waves' section -- plan-wave's rolling-wave discipline "
                    "keeps only the current wave detailed. If this is "
                    "intentional, approve and continue."
                )
                _log_decision(repo_root, "ask", tool_name=tool_name, reason=reason)
                _ask(reason)
                return
            _log_decision(repo_root, "allow", tool_name=tool_name, reason="well-formed")
            _allow()
            return

        if _is_issue_create(payload):
            violation = _wave_plan_violation(repo_root)
            if violation is None:
                _log_decision(
                    repo_root, "allow", tool_name="Bash", reason="no-violation"
                )
                _allow()
                return
            reason = (
                f"{_relative(violation, repo_root)} has a populated task "
                "table in its 'Later waves' section -- detail only the "
                "current wave before creating issues. If this issue "
                "genuinely is for the current wave and the other section "
                "just needs cleanup, approve and continue."
            )
            _log_decision(repo_root, "ask", tool_name="Bash", reason=reason)
            _ask(reason)
            return

        _allow()
    except Exception as error:  # noqa: BLE001 - guardrail must fail open
        print(
            f"require_wave_shape.py: internal error, allowing: {error}",
            file=sys.stderr,
        )
        _allow()


if __name__ == "__main__":
    main()
