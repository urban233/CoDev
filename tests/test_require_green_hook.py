"""Tests for the Claude Code `Stop` verification hook.

Exercises the bundled .claude/hooks/require_green.py directly, as an
independent subprocess given fixture stdin -- the same "pin the external
contract against a fake, not the real tool" pattern as
tests/test_claude_hook.py, since there is no real Claude Code session to
drive in CI.

The block path matters more than the fail-open path here. A hook that fails
open when it should block silently removes the guarantee it exists to add,
so every test that asserts a refusal is load-bearing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

_HOOK = (
    Path(__file__).resolve().parent.parent
    / "src/codev_workflow/bundle/.claude/hooks/require_green.py"
)


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
        timeout=120,
        env=env,
    )


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _write_justfile(
    repo: Path, *, lint: int = 0, typecheck: int = 0, test: int = 0
) -> None:
    """A Justfile declaring the recipe names discovery has to find.

    The hook reads this file to learn which checks exist and then invokes
    them through `just`; `_plant_just` supplies that `just` and decides the
    exit codes. Writing a real Justfile rather than monkeypatching keeps the
    discovery half genuinely under test.
    """
    repo.joinpath("Justfile").write_text(
        f"lint:\n    @echo lint output\n    @exit {lint}\n"
        f"typecheck:\n    @echo typecheck output\n    @exit {typecheck}\n"
        f"test:\n    @echo test output\n    @exit {test}\n",
        encoding="utf-8",
    )


def _reason(result: Any) -> str:
    """The hook's block reason, or "" when it allowed."""
    if not result.stdout.strip():
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    return str(payload.get("reason", ""))


def _plant_just(repo: Path, exits: dict[str, int]) -> None:
    """A `.tools/just` stand-in whose recipes exit as the test dictates.

    The hook looks for a repository-local `.tools/just` before `PATH`, so
    planting one here exercises the real discovery path without depending on
    `just` being installed wherever the suite runs. The block path is the
    most important behaviour this hook has; leaving it to a test that skips
    on most machines would mean it was effectively untested.
    """
    tools = repo / ".tools"
    tools.mkdir(exist_ok=True)
    if os.name == "nt":
        # Windows cannot execute an extensionless shell script; the hook
        # looks for the .bat spelling there for exactly this reason.
        branches = "\r\n".join(
            f'if "%1"=="{recipe}" (echo {recipe} output & exit /b {code})'
            for recipe, code in exits.items()
        )
        (tools / "just.bat").write_text(
            "@echo off\r\n" + branches + "\r\nexit /b 0\r\n", encoding="utf-8"
        )
        return
    launcher = tools / "just"
    branches = "\n".join(
        f'  {recipe}) echo "{recipe} output"; exit {code} ;;'
        for recipe, code in exits.items()
    )
    launcher.write_text(
        '#!/bin/sh\ncase "$1" in\n' + branches + "\n  *) exit 0 ;;\nesac\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)


class StopFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_allows_a_clean_tree_without_running_anything(self) -> None:
        """The latency control: a turn that changed no source costs nothing."""
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_allows_when_only_non_source_files_changed(self) -> None:
        self.repo.joinpath("notes.md").write_text("hello\n", encoding="utf-8")
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_re_entry_still_runs_the_checks(self) -> None:
        """Re-entry must not be a blanket allow.

        Treating `stop_hook_active` as "already stopped once, let it go"
        made the whole guarantee one-shot: an agent whose checks still
        failed simply ended the turn on its second attempt, which is the
        opposite of what this hook exists to do.
        """
        self.repo.joinpath("broken.py").write_text("x = 1\n", encoding="utf-8")
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 1})
        result = _run(self.repo, {"cwd": str(self.repo), "stop_hook_active": True})
        self.assertIn("lint", _reason(result))

    def test_stands_down_after_three_consecutive_refusals(self) -> None:
        """Bounded, on the record, and before the host's own override.

        The host force-overrides a Stop hook after eight consecutive
        blocks. Standing down earlier and saying so is better than being
        overridden silently -- the record is what stops an unverified turn
        from reading like a verified one.
        """
        self.repo.joinpath("broken.py").write_text("x = 1\n", encoding="utf-8")
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 1})
        payload = {"cwd": str(self.repo), "stop_hook_active": True}
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                self.assertIn("lint", _reason(_run(self.repo, payload)))
        # Fourth: the budget is spent, so it allows -- loudly.
        result = _run(self.repo, payload)
        self.assertEqual("", result.stdout.strip())
        records = [
            json.loads(line)
            for line in (self.repo / ".codev/hooks/decisions.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual("unverified", records[-1]["decision"])
        self.assertIn("stood down", records[-1]["reason"])

    def test_a_passing_run_clears_the_refusal_count(self) -> None:
        """Otherwise one bad patch permanently spends the turn's budget."""
        self.repo.joinpath("broken.py").write_text("x = 1\n", encoding="utf-8")
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 1})
        payload = {"cwd": str(self.repo), "stop_hook_active": True}
        _run(self.repo, payload)
        _run(self.repo, payload)
        _plant_just(self.repo, {"lint": 0, "typecheck": 0, "test": 0})
        self.assertEqual("", _run(self.repo, payload).stdout.strip())
        _plant_just(self.repo, {"lint": 1})
        self.assertIn("lint", _reason(_run(self.repo, payload)))

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
        self.assertEqual("", result.stdout.strip())

    def test_fails_open_when_git_cannot_be_consulted(self) -> None:
        """An empty PATH removes git. Allowing is right; the record of having
        allowed blind is what makes it visible afterwards."""
        result = _run(self.repo, {"cwd": str(self.repo)}, path="")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())
        log = self.repo / ".codev/hooks/decisions.jsonl"
        self.assertTrue(log.exists())
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual("degraded", records[-1]["decision"])

    def test_fails_open_when_no_checks_are_reachable(self) -> None:
        """A repository with no Justfile and no tooling must not be blocked
        from ending a turn."""
        self.repo.joinpath("thing.py").write_text("x = 1\n", encoding="utf-8")
        result = _run(
            self.repo, {"cwd": str(self.repo)}, path=os.environ.get("PATH", "")
        )
        self.assertEqual(0, result.returncode)
        # Either it found no checks (degraded) or it found and passed some;
        # what must never happen is a block.
        self.assertNotIn('"decision": "block"', result.stdout)


class StopCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)
        self.repo.joinpath("thing.py").write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_blocks_when_a_check_fails(self) -> None:
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 1})
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("block", payload["decision"])
        self.assertIn("lint", payload["reason"])

    def test_block_reason_carries_the_check_output(self) -> None:
        """A refusal the agent cannot act on is a worse outcome than none."""
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 0, "typecheck": 0, "test": 1})
        result = _run(self.repo, {"cwd": str(self.repo)})
        payload = json.loads(result.stdout)
        self.assertIn("test output", payload["reason"])

    def test_allows_when_every_check_passes(self) -> None:
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 0, "typecheck": 0, "test": 0})
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())

    def test_stops_at_the_first_failing_check(self) -> None:
        _write_justfile(self.repo)
        _plant_just(self.repo, {"lint": 1, "typecheck": 0, "test": 1})
        result = _run(self.repo, {"cwd": str(self.repo)})
        payload = json.loads(result.stdout)
        self.assertIn("lint", payload["reason"])
        self.assertNotIn("test output", payload["reason"])


class DiscoveredFallbackTests(unittest.TestCase):
    """The path taken in a repository with no `just` recipes.

    This is the shape the bundle actually installs into most often -- a
    flat-layout scientific Python project with no Justfile at all -- and it
    had no test, which is how `-P` on the test runner reached CI green
    while being permanently broken there.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_unittest_fallback_can_import_a_flat_layout_package(self) -> None:
        """A package beside its tests must still be importable.

        `-P` strips the cwd entry from sys.path, which is exactly the entry
        a flat layout relies on. With it, the runner cannot import the code
        under test, the hook blocks on a failure no agent can fix, and it
        stands down unverified every time. Hence no -P on the runners --
        the asymmetry with the analyzers is deliberate.
        """
        (self.repo / "mypkg").mkdir()
        (self.repo / "mypkg" / "__init__.py").write_text(
            "VALUE = 41\n", encoding="utf-8"
        )
        tests_dir = self.repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_value.py").write_text(
            "import unittest\n\nimport mypkg\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(41, mypkg.VALUE)\n",
            encoding="utf-8",
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        reason = _reason(result)
        self.assertNotIn("ModuleNotFoundError", reason)
        self.assertNotIn("No module named", reason)

    def test_analyzers_keep_the_safe_path_flag(self) -> None:
        """`-P` is load-bearing where a planted module changes the verdict.

        Asserted on source because the alternative is planting a malicious
        module in a fixture, and the flag's presence is the whole control.
        """
        for rel in (
            "src/codev_workflow/bundle/.claude/hooks/require_green.py",
            "src/codev_workflow/bundle/.claude/hooks/require_plan.py",
            "src/codev_workflow/bundle/.claude/hooks/require_wave_shape.py",
            "src/codev_workflow/bundle/.claude/hooks/require_small_change.py",
            "src/codev_workflow/bundle/.claude/hooks/format_touched.py",
        ):
            source = (Path(__file__).resolve().parent.parent / rel).read_text(
                encoding="utf-8"
            )
            with self.subTest(hook=rel):
                for analyzer in ("codev_workflow", "ruff", "mypy"):
                    if f'"{analyzer}"' in source and "sys.executable" in source:
                        self.assertIn(
                            '"-P"',
                            source,
                            f"{rel} runs a module without -P",
                        )
                        break


class ToothlessTestDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        _init_repo(self.repo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_blocks_a_new_test_that_asserts_nothing(self) -> None:
        self.repo.joinpath("test_thing.py").write_text(
            "def test_works():\n    value = 1 + 1\n", encoding="utf-8"
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        payload = json.loads(result.stdout)
        self.assertEqual("block", payload["decision"])
        self.assertIn("test_works", payload["reason"])
        self.assertIn("asserts nothing", payload["reason"])

    def test_blocks_a_test_whose_assertions_are_unchanged_from_head(self) -> None:
        source = "def test_works():\n    assert 1 == 1\n"
        path = self.repo / "test_thing.py"
        path.write_text(source, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=self.repo, check=True)
        # Touch the function without changing what it actually checks.
        path.write_text(
            "def test_works():\n    context = 'setup'\n    assert 1 == 1\n",
            encoding="utf-8",
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        payload = json.loads(result.stdout)
        self.assertEqual("block", payload["decision"])
        self.assertIn("same assertions as HEAD", payload["reason"])

    def test_allows_a_test_with_new_assertions(self) -> None:
        self.repo.joinpath("test_thing.py").write_text(
            "def test_works():\n    assert 2 + 2 == 4\n", encoding="utf-8"
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertNotIn('"decision": "block"', result.stdout)

    def test_recognises_unittest_style_assertions(self) -> None:
        """`assert` is not the only way to assert, and treating it as the only
        one would flag every unittest.TestCase in the repository."""
        self.repo.joinpath("test_thing.py").write_text(
            "import unittest\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_works(self):\n"
            "        self.assertEqual(4, 2 + 2)\n",
            encoding="utf-8",
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertNotIn("asserts nothing", result.stdout)

    def test_ignores_a_non_test_source_file(self) -> None:
        self.repo.joinpath("thing.py").write_text(
            "def compute():\n    return 1\n", encoding="utf-8"
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertNotIn("asserts nothing", result.stdout)

    def test_does_not_flag_an_unparseable_test_file(self) -> None:
        """A syntax error is the lint check's finding, not this one's -- and
        reporting it here would give the agent two different explanations of
        the same problem."""
        self.repo.joinpath("test_thing.py").write_text(
            "def test_works(:\n", encoding="utf-8"
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        self.assertNotIn("asserts nothing", result.stdout)

    def test_ignores_untouched_tests_in_a_file_that_gained_a_new_one(self) -> None:
        """Regression: adding a test to an existing file must not put every
        pre-existing test in that file on trial.

        Found by running this hook against its own change. Every untouched
        test genuinely does have the same assertions as HEAD -- because
        nobody changed them -- so comparing assertions alone reported the
        whole file and made the hook unusable on any real edit.
        """
        path = self.repo / "test_thing.py"
        path.write_text(
            "def test_one():\n    assert 1 == 1\n\n\n"
            "def test_two():\n    assert 2 == 2\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=self.repo, check=True)
        path.write_text(
            "def test_one():\n    assert 1 == 1\n\n\n"
            "def test_two():\n    assert 2 == 2\n\n\n"
            "def test_three():\n    assert 3 == 3\n",
            encoding="utf-8",
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        # Assert on the pre-change finding specifically. A temporary repo
        # inherits whatever ruff config sits above it, so the lint check may
        # legitimately have something to say about the fixture; that is a
        # different finding and not what this test is about.
        self.assertNotIn("pre-change code", _reason(result))

    def test_still_flags_a_touched_test_in_a_file_with_untouched_ones(self) -> None:
        """The narrowing above must not weaken the check it narrows."""
        path = self.repo / "test_thing.py"
        path.write_text(
            "def test_one():\n    assert 1 == 1\n\n\n"
            "def test_two():\n    assert 2 == 2\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=self.repo, check=True)
        path.write_text(
            "def test_one():\n    assert 1 == 1\n\n\n"
            "def test_two():\n    setup = 1\n    assert 2 == 2\n",
            encoding="utf-8",
        )
        result = _run(self.repo, {"cwd": str(self.repo)})
        reason = _reason(result)
        self.assertIn("pre-change code", reason)
        self.assertIn("test_two", reason)
        self.assertNotIn("test_one", reason)

    def test_never_modifies_the_working_tree(self) -> None:
        """The pre-change comparison reads git object storage. A mechanism
        that checked out, stashed, or created a worktree could lose
        uncommitted work, which is why this is pinned."""
        path = self.repo / "test_thing.py"
        path.write_text("def test_works():\n    assert 1 == 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=self.repo, check=True)
        path.write_text(
            "def test_works():\n    assert 1 == 1\n# uncommitted\n", encoding="utf-8"
        )
        before = path.read_text(encoding="utf-8")
        _run(self.repo, {"cwd": str(self.repo)})
        self.assertEqual(before, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
