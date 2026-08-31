"""Tests for the Claude Code wave-shape guardrail hook script.

Exercises the bundled .claude/hooks/require_wave_shape.py directly, as an
independent subprocess given fixture stdin -- the same "pin the external
contract in tests against a fake, not the real tool" pattern
test_claude_hook.py already uses for require_plan.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/require_wave_shape.py"
)

_WELL_FORMED_WAVE_PLAN = """\
## Current work

| ID | Task and acceptance | Owner |
|---|---|---|
| W-01 | do the thing | alice |

## Later waves

<!-- coarse only -->

- **Outcome:** something coarse, refine later
"""

_MALFORMED_WAVE_PLAN = """\
## Current work

| ID | Task and acceptance | Owner |
|---|---|---|
| W-01 | do the thing | alice |

## Later waves

| ID | Task and acceptance | Owner |
|---|---|---|
| W-05 | this should not be detailed yet | bob |
"""


def _run_hook(repo: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=stdin,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_hook_json(
    repo: Path, payload: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    return _run_hook(repo, json.dumps(payload))


class RequireWaveShapeHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ignores_non_gated_tools(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "docs/codev/wave/x.md"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_ignores_write_to_a_non_wave_plan_path(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "docs/features/x/design.md",
                    "content": _MALFORMED_WAVE_PLAN,
                },
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_write_of_a_well_formed_wave_plan(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "docs/codev/wave/some-feature.md",
                    "content": _WELL_FORMED_WAVE_PLAN,
                },
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_on_write_with_a_populated_later_waves_table(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "docs/codev/wave/some-feature.md",
                    "content": _MALFORMED_WAVE_PLAN,
                },
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual("PreToolUse", payload["hookSpecificOutput"]["hookEventName"])
        self.assertTrue(payload["hookSpecificOutput"]["permissionDecisionReason"])

    def test_fails_open_on_malformed_stdin(self) -> None:
        result = _run_hook(self.repo, "not json")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_ignores_non_issue_create_bash_commands(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_issue_create_when_no_wave_plan_exists(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git issue-create --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_issue_create_when_every_wave_plan_is_well_formed(self) -> None:
        wave_dir = self.repo / "docs/codev/wave"
        wave_dir.mkdir(parents=True)
        (wave_dir / "some-feature.md").write_text(
            _WELL_FORMED_WAVE_PLAN, encoding="utf-8"
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git issue-create --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_on_issue_create_when_a_wave_plan_is_malformed(self) -> None:
        wave_dir = self.repo / "docs/codev/wave"
        wave_dir.mkdir(parents=True)
        (wave_dir / "some-feature.md").write_text(
            _MALFORMED_WAVE_PLAN, encoding="utf-8"
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git issue-create --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])
        self.assertIn(
            "some-feature.md",
            payload["hookSpecificOutput"]["permissionDecisionReason"],
        )


if __name__ == "__main__":
    unittest.main()
