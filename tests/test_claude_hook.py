"""Tests for the Claude Code plan-first guardrail hook script.

Exercises the bundled .claude/hooks/require_plan.py directly, as an
independent subprocess given fixture stdin -- there is no real Claude Code
session to drive in CI, so this pins the hook's own stdin/stdout contract
against itself, the same "pin the external contract in tests against a
fake, not the real tool" pattern already used for the OpenCode driver (see
docs/features/skill-eval/design.md).
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
    / "src/codev_workflow/bundle/.claude/hooks/require_plan.py"
)


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


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


class RequirePlanHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ignores_non_gated_tools(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_edits_under_docs(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature/x"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "docs/features/x/design.md"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_on_main_branch(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_when_no_matching_spec_exists_on_feature_branch(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual("PreToolUse", payload["hookSpecificOutput"]["hookEventName"])
        self.assertTrue(payload["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_when_matching_spec_exists_on_feature_branch(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        spec_dir = self.repo / "docs/features/some-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "design.md").write_text("# design\n", encoding="utf-8")
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_when_matching_wave_plan_exists_on_feature_branch(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        wave_dir = self.repo / "docs/codev/wave"
        wave_dir.mkdir(parents=True)
        (wave_dir / "some-feature.md").write_text("# wave plan\n", encoding="utf-8")
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_fails_open_on_malformed_stdin(self) -> None:
        result = _run_hook(self.repo, "not json")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_when_tool_input_has_no_file_path(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(self.repo, {"tool_name": "Edit", "cwd": str(self.repo)})
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])

    def test_allows_edit_with_a_precise_task_plan_and_no_feature_design_doc(
        self,
    ) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "codev/some-task-id"],
            cwd=self.repo,
            check=True,
        )
        plan_dir = self.repo / "docs/codev/task/some-task-id"
        plan_dir.mkdir(parents=True)
        (plan_dir / "implementation-plan.md").write_text("# plan\n", encoding="utf-8")
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_on_a_task_branch_with_no_recorded_plan(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "codev/some-task-id"],
            cwd=self.repo,
            check=True,
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])

    def test_ignores_non_destructive_bash_commands(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
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

    def test_asks_on_destructive_bash_command_without_spec(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'x'"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])
        self.assertIn(
            "git command", payload["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_allows_destructive_bash_command_with_precise_task_plan(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "codev/some-task-id"],
            cwd=self.repo,
            check=True,
        )
        plan_dir = self.repo / "docs/codev/task/some-task-id"
        plan_dir.mkdir(parents=True)
        (plan_dir / "implementation-plan.md").write_text("# plan\n", encoding="utf-8")
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin codev/some-task-id"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_bash_on_main_branch(self) -> None:
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git reset --hard"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
