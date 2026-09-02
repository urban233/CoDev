"""Tests for the Claude Code small-change guardrail hook script.

Exercises the bundled .claude/hooks/require_small_change.py directly, as an
independent subprocess given fixture stdin -- the same pattern
test_claude_hook.py and test_wave_shape_hook.py already use for their own
hooks. Unlike those two, this hook shells out to a further external
command (`codev task size --id <id> --json`), so these tests build a real
task in a real temporary git repository with git_ops directly, then run
the hook against it end to end rather than faking that subprocess call --
the real command is the contract worth pinning here, not a stand-in for
it.

Resolving that real `codev` differs by how these tests themselves run.
Under a normal `pip install -e .` (every raw `python -m unittest discover`
CI leg, including Windows), a real `codev`/`codev.exe` console script sits
right next to whatever Python is running these tests, so prepending that
directory to PATH is enough. Bazel's `py_test` has no such console script
at all -- its hermetic interpreter never went through `pip install` -- so
when that lookup comes up empty, a tiny POSIX shell wrapper is synthesized
that simply re-execs `sys.executable -m codev_workflow`, which resolves
correctly under Bazel's own runfiles-based imports. This fallback is
POSIX-only, matching this project's own stated scope for Bazel testing
(verified on Linux and macOS, not Windows) -- Windows never needs it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from codev_workflow import config, git_ops

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/require_small_change.py"
)


def _init_repo(target: Path) -> str:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=target, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
    (target / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=target, check=True)
    return git_ops.current_head(target)


def _hook_env(bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    candidate_path = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    if shutil.which("codev", path=candidate_path) is not None:
        env["PATH"] = candidate_path
        return env

    shim = bin_dir / "codev"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -m codev_workflow "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env["PATH"] = str(bin_dir) + os.pathsep + candidate_path
    return env


class RequireSmallChangeHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.bin_dir = Path(self.temporary.name) / "bin"
        self.bin_dir.mkdir()
        self.base = _init_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_hook(self, stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_HOOK)],
            input=stdin,
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
            env=_hook_env(self.bin_dir),
        )

    def _run_hook_json(
        self, payload: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        return self._run_hook(json.dumps(payload))

    def test_ignores_non_bash_tools(self) -> None:
        result = self._run_hook_json(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/foo.py"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_ignores_bash_commands_that_are_not_open_pr(self) -> None:
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git push --id item-1"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_when_no_task_id_can_be_found(self) -> None:
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git open-pr --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_when_the_task_has_no_branch_recorded(self) -> None:
        # task_size returns zero counts (never over budget) for an unknown
        # id, matching git_ops.task_size's own documented posture.
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "codev git open-pr --id unknown-task --title x"
                },
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_allows_a_within_budget_task(self) -> None:
        git_ops.create_branch("item-1", self.base, target=self.repo)
        (self.repo / "small.txt").write_text("one line\n", encoding="utf-8")
        git_ops.commit("item-1", "small change", target=self.repo)
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git open-pr --id item-1 --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asks_on_an_over_budget_task(self) -> None:
        git_ops.create_branch("item-1", self.base, target=self.repo)
        config.set_value("review.max_lines", "1", target=self.repo)
        (self.repo / "big.txt").write_text("a\nb\nc\n", encoding="utf-8")
        git_ops.commit("item-1", "big change", target=self.repo)
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git open-pr --id item-1 --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])
        reason = payload["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("item-1", reason)
        self.assertIn("over budget", reason)

    def test_asks_on_an_over_file_budget_task(self) -> None:
        git_ops.create_branch("item-1", self.base, target=self.repo)
        config.set_value("review.max_files", "1", target=self.repo)
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        (self.repo / "b.txt").write_text("b\n", encoding="utf-8")
        git_ops.commit("item-1", "two files", target=self.repo)
        result = self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git open-pr --id item-1 --title x"},
                "cwd": str(self.repo),
            },
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("ask", payload["hookSpecificOutput"]["permissionDecision"])

    def test_allows_when_codev_is_not_resolvable_on_path(self) -> None:
        git_ops.create_branch("item-1", self.base, target=self.repo)
        config.set_value("review.max_lines", "1", target=self.repo)
        (self.repo / "big.txt").write_text("a\nb\nc\n", encoding="utf-8")
        git_ops.commit("item-1", "big change", target=self.repo)
        env = os.environ.copy()
        env["PATH"] = ""
        result = subprocess.run(
            [sys.executable, str(_HOOK)],
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "codev git open-pr --id item-1 --title x"
                    },
                    "cwd": str(self.repo),
                }
            ),
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_fails_open_on_malformed_stdin(self) -> None:
        result = self._run_hook("not json")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_asking_writes_a_decision_log_entry(self) -> None:
        git_ops.create_branch("item-1", self.base, target=self.repo)
        config.set_value("review.max_lines", "1", target=self.repo)
        (self.repo / "big.txt").write_text("a\nb\nc\n", encoding="utf-8")
        git_ops.commit("item-1", "big change", target=self.repo)
        self._run_hook_json(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "codev git open-pr --id item-1 --title x"},
                "cwd": str(self.repo),
            },
        )
        log_path = self.repo / ".codev/hooks/decisions.jsonl"
        self.assertTrue(log_path.exists())
        record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("require_small_change.py", record["hook"])
        self.assertEqual("ask", record["decision"])


if __name__ == "__main__":
    unittest.main()
