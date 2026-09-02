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
import os
import shlex
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


def _codev_on_path() -> str:
    """A directory holding a `codev` executable that runs this interpreter's
    own codev_workflow.

    The hooks are shims: the decision lives in `codev gate check`, so a test
    that does not put `codev` on PATH exercises only the fail-open branch and
    would pass no matter what the gate decided.
    """
    bindir = Path(tempfile.mkdtemp(prefix="codev-bin-"))
    launcher = bindir / "codev"
    launcher.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' -m codev_workflow "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return str(bindir)


def _run_hook(repo: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = _codev_on_path() + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=stdin,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
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

    def test_asks_on_codev_git_branch_without_spec(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git branch --id item-1 --base main"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])

    def test_asks_on_codev_git_restack_without_spec(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git restack --id item-2"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])

    def test_ignores_codev_git_read_only_commands(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        result = _run_hook_json(
            self.repo,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git issue-view --number 7"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

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

    def test_asking_writes_a_decision_log_entry(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        log_path = self.repo / ".codev/hooks/decisions.jsonl"
        self.assertTrue(log_path.exists())
        record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("require_plan.py", record["hook"])
        self.assertEqual("ask", record["decision"])

    def test_allowing_on_main_writes_a_decision_log_entry(self) -> None:
        # main is exempted from gating, but that is still a real decision
        # the hook made, not an irrelevant-tool early exit -- log it.
        _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        log_path = self.repo / ".codev/hooks/decisions.jsonl"
        record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("allow", record["decision"])
        self.assertEqual("ungated-branch", record["reason"])

    def test_ignoring_a_read_tool_writes_no_decision(self) -> None:
        # Read is not in _GATED_EDIT_TOOLS at all -- gate_reason is None,
        # the earliest exit, before any real decision is reached.
        _run_hook_json(
            self.repo,
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertFalse((self.repo / ".codev/hooks/decisions.jsonl").exists())

    def test_allowing_with_a_matching_spec_writes_a_decision_log_entry(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", "some-feature"], cwd=self.repo, check=True
        )
        spec_dir = self.repo / "docs/features/some-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "design.md").write_text("# design\n", encoding="utf-8")
        _run_hook_json(
            self.repo,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        log_path = self.repo / ".codev/hooks/decisions.jsonl"
        record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("allow", record["decision"])

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
