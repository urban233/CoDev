"""Tests for the Claude Code `PostToolUse` formatter hook.

Exercises the bundled .claude/hooks/format_touched.py directly, as an
independent subprocess given fixture stdin -- the same pattern as
tests/test_claude_hook.py.

This hook is deliberately the least powerful of the five: it runs a
formatter and nothing else, so the cases worth pinning are the ones where
it must stay out of the way.
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

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/format_touched.py"
)

_UNFORMATTED = "def f( a,b ):\n  return   a+b\n"


def _run(repo: Path, payload: dict[str, Any], *, path: str | None = None) -> Any:
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _edit(repo: Path, target: Path, tool: str = "Edit") -> dict[str, Any]:
    return {
        "cwd": str(repo),
        "tool_name": tool,
        "tool_input": {"file_path": str(target)},
    }


def _ruff_available() -> bool:
    try:
        import importlib.util

        if importlib.util.find_spec("ruff") is not None:
            return True
    except (ImportError, ValueError):
        pass
    return shutil.which("ruff") is not None


def _plant_ruff(repo: Path, *, reformats: bool) -> None:
    """A `ruff` stand-in on PATH, so the behaviour is testable everywhere.

    Five of these tests skipped under Bazel because ruff is not importable
    in the sandbox on any leg -- which left the hook's entire purpose
    unexercised in CI, the same gap a planted `just` closed for the Stop
    hook. Returns the directory to prepend to PATH.
    """
    tools = repo / ".fake-bin"
    tools.mkdir(exist_ok=True)
    message = "1 file reformatted" if reformats else "1 file left unchanged"
    if os.name == "nt":
        (tools / "ruff.bat").write_text(
            f"@echo off\r\necho {message}\r\nexit /b 0\r\n", encoding="utf-8"
        )
    else:
        launcher = tools / "ruff"
        launcher.write_text(f'#!/bin/sh\necho "{message}"\nexit 0\n', encoding="utf-8")
        launcher.chmod(0o755)


class FormatTouchedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fails_open_on_malformed_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_HOOK)],
            input="not json",
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode)

    def test_is_a_no_op_for_a_non_python_file(self) -> None:
        target = self.repo / "notes.md"
        original = "#   Heading\n\n\n\nbody\n"
        target.write_text(original, encoding="utf-8")
        result = _run(self.repo, _edit(self.repo, target))
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_is_a_no_op_when_the_payload_names_no_file(self) -> None:
        result = _run(
            self.repo, {"cwd": str(self.repo), "tool_name": "Edit", "tool_input": {}}
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_tolerates_a_path_that_no_longer_exists(self) -> None:
        """An edit can be followed by a delete inside the same turn."""
        result = _run(self.repo, _edit(self.repo, self.repo / "gone.py"))
        self.assertEqual(0, result.returncode)

    def test_fails_open_when_no_formatter_is_reachable(self) -> None:
        target = self.repo / "thing.py"
        target.write_text(_UNFORMATTED, encoding="utf-8")
        # An empty PATH plus an interpreter that cannot import ruff.
        result = subprocess.run(
            [sys.executable, "-S", str(_HOOK)],
            input=json.dumps(_edit(self.repo, target)),
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "", "PYTHONPATH": ""},
        )
        self.assertEqual(0, result.returncode)

    @unittest.skipUnless(_ruff_available(), "ruff is not installed")
    def test_reformats_a_touched_python_file(self) -> None:
        target = self.repo / "thing.py"
        target.write_text(_UNFORMATTED, encoding="utf-8")
        result = _run(self.repo, _edit(self.repo, target))
        self.assertEqual(0, result.returncode)
        self.assertEqual("def f(a, b):\n    return a + b\n", target.read_text())

    @unittest.skipUnless(_ruff_available(), "ruff is not installed")
    def test_tells_the_agent_its_file_changed_underneath_it(self) -> None:
        """Without this the agent's idea of the file is stale and it
        re-applies its own spacing on the next edit."""
        target = self.repo / "thing.py"
        target.write_text(_UNFORMATTED, encoding="utf-8")
        result = _run(self.repo, _edit(self.repo, target))
        payload = json.loads(result.stdout)
        self.assertEqual("PostToolUse", payload["hookSpecificOutput"]["hookEventName"])
        self.assertIn("thing.py", payload["hookSpecificOutput"]["additionalContext"])

    @unittest.skipUnless(_ruff_available(), "ruff is not installed")
    def test_says_nothing_when_the_file_was_already_formatted(self) -> None:
        """Reporting every call would spend a turn's attention on the case
        where nothing happened."""
        target = self.repo / "thing.py"
        target.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
        result = _run(self.repo, _edit(self.repo, target))
        self.assertEqual("", result.stdout.strip())

    @unittest.skipUnless(_ruff_available(), "ruff is not installed")
    def test_handles_a_multiedit_payload(self) -> None:
        target = self.repo / "thing.py"
        target.write_text(_UNFORMATTED, encoding="utf-8")
        payload = {
            "cwd": str(self.repo),
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": str(target),
                "edits": [{"old_string": "a", "new_string": "a"}],
            },
        }
        result = _run(self.repo, payload)
        self.assertEqual(0, result.returncode)
        self.assertEqual("def f(a, b):\n    return a + b\n", target.read_text())

    @unittest.skipUnless(_ruff_available(), "ruff is not installed")
    def test_does_not_type_check(self) -> None:
        """The type checker belongs at Stop, not here: this hook fires
        between the edits of a multi-file sequence, where an intermediate
        state is legitimately broken."""
        target = self.repo / "thing.py"
        target.write_text("def f(a: int) -> str:\n    return a\n", encoding="utf-8")
        result = _run(self.repo, _edit(self.repo, target))
        self.assertEqual(0, result.returncode)
        self.assertNotIn("int", result.stdout)


class FormatTouchedWithoutRuffInstalledTests(unittest.TestCase):
    """The hook's purpose, exercised without depending on a real ruff.

    These run on every leg. The `@skipUnless(_ruff_available())` tests above
    stay because they pin the behaviour against the genuine formatter where
    one exists; these pin it where one does not.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_with_fake_ruff(self, target: Path) -> Any:
        env = dict(os.environ)
        env["PATH"] = str(self.repo / ".fake-bin") + os.pathsep + env.get("PATH", "")
        # -S so the hook's own interpreter cannot import a real ruff and
        # resolve that in preference to the planted one.
        return subprocess.run(
            [sys.executable, "-S", str(_HOOK)],
            input=json.dumps(_edit(self.repo, target)),
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def test_reports_back_when_the_formatter_rewrote_the_file(self) -> None:
        _plant_ruff(self.repo, reformats=True)
        target = self.repo / "thing.py"
        target.write_text(_UNFORMATTED, encoding="utf-8")
        result = self._run_with_fake_ruff(target)
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertIn("thing.py", payload["hookSpecificOutput"]["additionalContext"])

    def test_stays_silent_when_the_formatter_changed_nothing(self) -> None:
        _plant_ruff(self.repo, reformats=False)
        target = self.repo / "thing.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = self._run_with_fake_ruff(target)
        self.assertEqual("", result.stdout.strip())

    def test_passes_force_exclude_so_the_project_exclusions_apply(self) -> None:
        """Without it the hook rewrites vendored mirrors and eval fixtures
        that `just fmt-check` deliberately never touches."""
        source = (
            Path(__file__).resolve().parent.parent
            / "src/codev_workflow/bundle/.claude/hooks/format_touched.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"--force-exclude"', source)


if __name__ == "__main__":
    unittest.main()
