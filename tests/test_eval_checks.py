from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from codev_workflow.eval_checks import (
    ChecksError,
    changed_paths_since_seed,
    finding_matches,
    load_structured_output,
    require,
    run_declarative_checks,
)


class LoadStructuredOutputTests(unittest.TestCase):
    def test_loads_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"decision": "OK"}), encoding="utf-8")
            self.assertEqual({"decision": "OK"}, load_structured_output(path))

    def test_missing_file_raises_oserror(self) -> None:
        with self.assertRaises(OSError):
            load_structured_output("/no/such/file.json")

    def test_malformed_json_raises_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_structured_output(path)


class FindingMatchesTests(unittest.TestCase):
    def test_matches_location_and_keyword(self) -> None:
        findings = [
            {"location": "pkg/reporter.py:_helper", "summary": "no docstring"},
        ]
        self.assertTrue(
            finding_matches(
                findings,
                location_contains="_helper",
                keywords=["docstring", "documentation"],
            )
        )

    def test_requires_both_location_and_keyword(self) -> None:
        findings = [{"location": "pkg/reporter.py:_helper", "summary": "unrelated"}]
        self.assertFalse(
            finding_matches(
                findings, location_contains="_helper", keywords=["docstring"]
            )
        )
        findings = [{"location": "other.py", "summary": "no docstring"}]
        self.assertFalse(
            finding_matches(
                findings, location_contains="_helper", keywords=["docstring"]
            )
        )

    def test_ignores_non_dict_entries(self) -> None:
        self.assertFalse(
            finding_matches(["not a dict"], location_contains="x", keywords=["y"])
        )

    def test_case_insensitive(self) -> None:
        findings = [{"location": "PKG/REPORTER.PY", "summary": "Missing DOCSTRING"}]
        self.assertTrue(
            finding_matches(
                findings, location_contains="reporter.py", keywords=["docstring"]
            )
        )


class ChangedPathsSinceSeedTests(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "t@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test"], check=True
        )
        (root / "a.txt").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True
        )

    def test_no_changes_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            import os

            cwd = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual([], changed_paths_since_seed())
            finally:
                os.chdir(cwd)

    def test_modified_and_untracked_files_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            (root / "a.txt").write_text("changed", encoding="utf-8")
            (root / "new.txt").write_text("new", encoding="utf-8")
            (root / "allowed.txt").write_text("new", encoding="utf-8")
            import os

            cwd = Path.cwd()
            try:
                os.chdir(root)
                changed = changed_paths_since_seed(ignore=["allowed.txt"])
            finally:
                os.chdir(cwd)
            self.assertEqual(["a.txt", "new.txt"], changed)


class RequireTests(unittest.TestCase):
    def test_true_condition_does_not_exit(self) -> None:
        require(True, "unused")

    def test_false_condition_exits_one(self) -> None:
        with self.assertRaises(SystemExit) as context:
            require(False, "boom")
        self.assertEqual(1, context.exception.code)


class RunDeclarativeChecksTests(unittest.TestCase):
    def _write_plan(self, directory: Path, **fields: object) -> None:
        (directory / "plan.json").write_text(json.dumps(fields), encoding="utf-8")

    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "t@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test"], check=True
        )
        (root / "seed.txt").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True
        )

    def test_json_field_equals_passes_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_plan(root, decision="APPROVED")
            import os

            cwd = Path.cwd()
            try:
                os.chdir(root)
                ok, _ = run_declarative_checks(
                    [
                        {
                            "type": "json_field_equals",
                            "file": "plan.json",
                            "field": "decision",
                            "equals": "APPROVED",
                        }
                    ]
                )
                self.assertTrue(ok)
                ok, message = run_declarative_checks(
                    [
                        {
                            "type": "json_field_equals",
                            "file": "plan.json",
                            "field": "decision",
                            "equals": "REJECTED",
                        }
                    ]
                )
                self.assertFalse(ok)
                self.assertIn("REJECTED", message)
            finally:
                os.chdir(cwd)

    def test_finding_matches_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_plan(
                root,
                findings=[{"location": "x.py:_helper", "summary": "no docstring"}],
            )
            import os

            cwd = Path.cwd()
            try:
                os.chdir(root)
                ok, _ = run_declarative_checks(
                    [
                        {
                            "type": "finding_matches",
                            "file": "plan.json",
                            "field": "findings",
                            "location_contains": "_helper",
                            "any_keyword": ["docstring"],
                        }
                    ]
                )
                self.assertTrue(ok)
            finally:
                os.chdir(cwd)

    def test_files_unchanged_except_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            import os

            cwd = Path.cwd()
            try:
                os.chdir(root)
                self._write_plan(root, decision="OK")
                ok, _ = run_declarative_checks(
                    [{"type": "files_unchanged_except", "except": ["plan.json"]}]
                )
                self.assertTrue(ok)
                (root / "seed.txt").write_text("tampered", encoding="utf-8")
                ok, message = run_declarative_checks(
                    [{"type": "files_unchanged_except", "except": ["plan.json"]}]
                )
                self.assertFalse(ok)
                self.assertIn("seed.txt", message)
            finally:
                os.chdir(cwd)

    def test_command_succeeds_check(self) -> None:
        import sys

        ok, _ = run_declarative_checks(
            [{"type": "command_succeeds", "argv": [sys.executable, "-c", "pass"]}]
        )
        self.assertTrue(ok)
        ok, message = run_declarative_checks(
            [{"type": "command_succeeds", "argv": [sys.executable, "-c", "exit(1)"]}]
        )
        self.assertFalse(ok)
        self.assertIn("exited 1", message)

    def test_unknown_check_type_fails(self) -> None:
        ok, message = run_declarative_checks([{"type": "not-a-real-type"}])
        self.assertFalse(ok)
        self.assertIn("unknown check type", message)

    def test_stops_at_first_failure(self) -> None:
        import sys

        ok, message = run_declarative_checks(
            [
                {"type": "command_succeeds", "argv": [sys.executable, "-c", "exit(1)"]},
                {"type": "command_succeeds", "argv": [sys.executable, "-c", "exit(1)"]},
            ]
        )
        self.assertFalse(ok)
        self.assertIn("checks[0]", message)


class ChecksErrorTests(unittest.TestCase):
    def test_is_a_runtime_error(self) -> None:
        self.assertIsInstance(ChecksError("x"), RuntimeError)


if __name__ == "__main__":
    unittest.main()
