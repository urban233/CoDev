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
for why a per-issue-precise check was rejected for this release. It also
only inspects `Write` calls directly, using the proposed new content
rather than re-reading a stale on-disk copy -- an `Edit`/`MultiEdit` to an
already-saved wave-plan document is not separately checked at edit time in
this release; the `codev git issue-create` trigger is the backstop that
still catches a violation however it was introduced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_GATED_EDIT_TOOLS = {"Write"}
_ISSUE_CREATE_PREFIX = "codev git issue-create"
_WAVE_PLAN_GLOB = "docs/codev/wave/*.md"
_LATER_WAVES_HEADING = "## Later waves"


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


def _write_target_content(
    payload: dict[str, Any], repo_root: Path
) -> tuple[Path, str] | None:
    """For a `Write` call targeting a wave-plan path, returns (path,
    proposed content). Returns None for any other call -- this only ever
    inspects a wave-plan document's own proposed content, never an
    unrelated file's."""
    if payload.get("tool_name") not in _GATED_EDIT_TOOLS:
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
    content = tool_input.get("content")
    if not isinstance(content, str):
        return None
    return candidate, content


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
        write_target = _write_target_content(payload, repo_root)
        if write_target is not None:
            _, content = write_target
            if _has_populated_task_table(_later_waves_section_lines(content)):
                _ask(
                    "This save leaves a populated task table in a 'Later "
                    "waves' section -- plan-wave's rolling-wave discipline "
                    "keeps only the current wave detailed. If this is "
                    "intentional, approve and continue."
                )
                return
            _allow()
            return

        if _is_issue_create(payload):
            violation = _wave_plan_violation(repo_root)
            if violation is None:
                _allow()
                return
            _ask(
                f"{_relative(violation, repo_root)} has a populated task "
                "table in its 'Later waves' section -- detail only the "
                "current wave before creating issues. If this issue "
                "genuinely is for the current wave and the other section "
                "just needs cleanup, approve and continue."
            )
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
