from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import verify_release


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src/codev_workflow").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text(
            '[project]\nversion = "0.1.3"\n',
            encoding="utf-8",
        )
        self.runtime_path = self.root / "src/codev_workflow/__init__.py"
        self.runtime_path.write_text('__version__ = "0.1.3"\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_matching_versions_and_tag_pass(self) -> None:
        self.assertEqual(
            ("0.1.3", "0.1.3"),
            verify_release.verify(self.root, "v0.1.3"),
        )

    def test_mismatched_runtime_version_fails(self) -> None:
        self.runtime_path.write_text('__version__ = "0.1.2"\n', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "runtime version 0.1.2"):
            verify_release.verify(self.root, "v0.1.3")

    def test_mismatched_tag_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "tag v0.1.4"):
            verify_release.verify(self.root, "v0.1.4")

    def test_metadata_only_mode_skips_release_checks(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["verify_release.py", "--root", str(self.root), "--metadata-only"],
            ),
            patch.object(verify_release, "run_release_checks") as checks,
        ):
            self.assertEqual(0, verify_release.main())
        checks.assert_not_called()

    def test_release_checks_run_all_quality_gates(self) -> None:
        (self.root / "dist").mkdir()
        (self.root / "dist" / "package.whl").write_bytes(b"artifact")

        def successful_run(*args: object, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(subprocess, "run", side_effect=successful_run) as run:
            verify_release.run_release_checks(self.root)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("unittest" in command for command in commands))
        self.assertTrue(any("compileall" in command for command in commands))
        self.assertTrue(any("ruff" in command for command in commands))
        self.assertTrue(any("mypy" in command for command in commands))
        self.assertTrue(any("build" in command for command in commands))
        self.assertTrue(any("twine" in command for command in commands))

    def test_release_checks_report_failed_command_and_output(self) -> None:
        failure = SimpleNamespace(
            returncode=1,
            stdout="test output",
            stderr="failure detail",
        )

        with (
            patch.object(subprocess, "run", return_value=failure),
            self.assertRaises(ValueError) as context,
        ):
            verify_release.run_release_checks(self.root)
        self.assertIn("unit tests failed with exit code 1", str(context.exception))
        self.assertIn("failure detail", str(context.exception))


class BundlePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "src" / "codev_workflow" / "bundle"
        self.bundle.mkdir(parents=True)
        (self.bundle / "AGENTS.md").write_text("x", encoding="utf-8")
        nested = self.bundle / ".codev" / "for-ai"
        nested.mkdir(parents=True)
        (nested / "ai-agent-guidelines.md").write_text("y", encoding="utf-8")
        (self.root / "dist").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_wheel(self, included: list[str]) -> None:
        wheel_path = self.root / "dist" / "package-0.0.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel_path, "w") as archive:
            for relative in included:
                archive.writestr(f"codev_workflow/bundle/{relative}", "content")

    def test_passes_when_every_bundle_file_is_packaged(self) -> None:
        self._write_wheel(["AGENTS.md", ".codev/for-ai/ai-agent-guidelines.md"])
        verify_release.verify_bundle_packaging(self.root)

    def test_fails_when_a_bundle_file_is_missing_from_the_wheel(self) -> None:
        self._write_wheel(["AGENTS.md"])
        with self.assertRaisesRegex(
            ValueError, r"\.codev/for-ai/ai-agent-guidelines\.md"
        ):
            verify_release.verify_bundle_packaging(self.root)

    def test_no_wheel_is_a_hard_failure_when_bundle_files_exist(self) -> None:
        with self.assertRaisesRegex(ValueError, "no wheel"):
            verify_release.verify_bundle_packaging(self.root)

    def test_missing_bundle_directory_is_a_silent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as empty_root:
            root = Path(empty_root)
            (root / "src" / "codev_workflow").mkdir(parents=True)
            verify_release.verify_bundle_packaging(root)

    def test_pycache_and_pyc_files_are_never_required(self) -> None:
        cache_dir = self.bundle / "scripts" / "__pycache__"
        cache_dir.mkdir(parents=True)
        (cache_dir / "check_google_rules.cpython-313.pyc").write_bytes(b"x")
        self._write_wheel(["AGENTS.md", ".codev/for-ai/ai-agent-guidelines.md"])
        verify_release.verify_bundle_packaging(self.root)
