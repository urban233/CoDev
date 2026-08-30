#!/usr/bin/env python3
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
"""Verify the real, currently-published Claude Code CLI still exposes the
surface CoDev's Claude Code adapter depends on.

Resolves the CLI via `npx` (no persistent install -- see
docs/features/claude-code/design.md's Phase 0, which did this same
inspection by hand) and inspects literal string constants in its own
shipped executable for hook event names, permission-decision field names,
permission-mode values, hardcoded discovery paths, and native memory files.
This is the automated replacement for that one-time manual spike -- run it
on a schedule and before a release (see .github/workflows/ci.yml), not on
every PR: it needs network access to fetch the package, which the rest of
this project's deterministic checks deliberately avoid
(docs/architecture.md).

Exit 0 when every expected marker is still present. Exit 1 and name exactly
which marker(s) went missing when Claude Code's own surface has drifted --
a signal to re-run docs/features/claude-code/design.md's Phase 0 and update
the adapter/hook/settings.json, not to silently keep trusting it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

_DEFAULT_CLAUDE_COMMAND = ("npx", "--yes", "@anthropic-ai/claude-code")

_EXPECTED_HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "SessionEnd",
    "PreCompact",
    "Notification",
    "SubagentStop",
)
_EXPECTED_HOOK_FIELDS = (
    "hookEventName",
    "permissionDecision",
    "hookSpecificOutput",
    "systemMessage",
    "additionalContext",
)
_EXPECTED_PERMISSION_SURFACE = (
    "defaultMode",
    '"plan"',
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
)
_EXPECTED_DISCOVERY_PATHS = (
    ".claude/agents",
    ".claude/commands",
    ".claude/skills/*/SKILL.md",
    ".claude/settings.json",
    ".claude/settings.local.json",
)
_EXPECTED_MEMORY_FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md")
_EXPECTED_ENV_VARS = ("CLAUDE_PROJECT_DIR",)

_ALL_EXPECTED_MARKERS = (
    _EXPECTED_HOOK_EVENTS
    + _EXPECTED_HOOK_FIELDS
    + _EXPECTED_PERMISSION_SURFACE
    + _EXPECTED_DISCOVERY_PATHS
    + _EXPECTED_MEMORY_FILES
    + _EXPECTED_ENV_VARS
)

_PATH_LINE = re.compile(r"^Path:\s*(.+)$", re.MULTILINE)
_VERSION_LINE = re.compile(r"^Running:.*\(([\w.\-]+)\)\s*$", re.MULTILINE)


class CompatCheckError(Exception):
    """Raised when the installed CLI's own report can't be parsed at all."""


def _claude_command() -> tuple[str, ...]:
    override = os.environ.get("CLAUDE_CLI_COMMAND")
    if override:
        return tuple(override.split())
    return _DEFAULT_CLAUDE_COMMAND


def _resolve_binary(command: tuple[str, ...]) -> tuple[str, str]:
    """Runs `claude doctor` and returns (version, path-to-executable)."""
    result = subprocess.run(
        [*command, "doctor"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    path_match = _PATH_LINE.search(result.stdout)
    if not path_match:
        raise CompatCheckError(
            "could not find a 'Path:' line in `claude doctor` output:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    version_match = _VERSION_LINE.search(result.stdout)
    version = version_match.group(1) if version_match else "unknown"
    return version, path_match.group(1).strip()


def _read_binary(binary_path: str) -> bytes:
    with open(binary_path, "rb") as handle:
        return handle.read()


def _missing_markers(data: bytes, markers: tuple[str, ...]) -> list[str]:
    # Direct substring search on the raw bytes, deliberately not "extract
    # printable runs, then exact-match" -- a marker is frequently embedded
    # inside a longer literal (e.g. an error message quoting a path), where
    # exact-run matching would miss it even though it's genuinely present.
    return [marker for marker in markers if marker.encode("ascii") not in data]


def main() -> int:
    command = _claude_command()
    print(f"Resolving the Claude Code CLI via: {' '.join(command)} ...")
    try:
        version, binary_path = _resolve_binary(command)
    except (CompatCheckError, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL: could not resolve the Claude Code CLI: {error}", file=sys.stderr)
        return 1
    print(f"claude {version} at {binary_path}")

    print("Searching the shipped binary for expected literal markers...")
    try:
        data = _read_binary(binary_path)
    except OSError as error:
        print(f"FAIL: could not read the resolved binary: {error}", file=sys.stderr)
        return 1

    missing = _missing_markers(data, _ALL_EXPECTED_MARKERS)
    if missing:
        print(
            f"FAIL: claude {version} no longer contains the following marker(s) "
            "this adapter depends on:",
            file=sys.stderr,
        )
        for marker in missing:
            print(f"  - {marker!r}", file=sys.stderr)
        print(
            "\nRe-run the compatibility spike in "
            "docs/features/claude-code/design.md's Phase 0 and update the "
            "adapter, hook, and settings.json accordingly before trusting "
            "this adapter against this Claude Code version.",
            file=sys.stderr,
        )
        return 1

    count = len(_ALL_EXPECTED_MARKERS)
    print(f"OK: all {count} expected markers present in claude {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
