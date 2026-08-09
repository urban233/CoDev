from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from codev_workflow.cli import main


class CliTests(unittest.TestCase):
    def test_init_check_diff_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "codex",
                        ]
                    ),
                )
                self.assertEqual(0, main(["check", "--target", str(target)]))
                self.assertEqual(0, main(["diff", "--target", str(target)]))

    def test_missing_install_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = StringIO()
            with redirect_stderr(errors):
                code = main(["check", "--target", directory])
            self.assertEqual(2, code)
            self.assertIn("not installed", errors.getvalue())

    def test_remove_dry_run_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "codex",
                        ]
                    ),
                )
                self.assertEqual(
                    0, main(["remove", "--target", str(target), "--dry-run"])
                )
                self.assertTrue((target / ".codev" / "lock.json").exists())
                self.assertEqual(0, main(["remove", "--target", str(target)]))
                self.assertFalse((target / ".codev" / "lock.json").exists())

    def test_update_can_add_a_platform_to_an_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "codex",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "update",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "antigravity",
                        ]
                    ),
                )
            self.assertTrue((target / ".agents/agents/reviewer.md").is_file())
            self.assertTrue(
                (target / ".agents/skills/review-change/SKILL.md").is_file()
            )
            self.assertEqual(0, main(["check", "--target", str(target)]))

    def test_programming_language_flag_selects_audit_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "codex",
                            "--programming-language",
                            "typescript",
                        ]
                    ),
                )

            self.assertFalse(
                (target / ".agents/skills/audit-google-python-style").exists()
            )
            self.assertTrue(
                (
                    target
                    / ".agents/skills/audit-google-typescript-style/SKILL.md"
                ).is_file()
            )

    def test_update_can_add_codex_to_an_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "init",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "opencode",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "update",
                            "--target",
                            str(target),
                            "--agent-platform",
                            "codex",
                        ]
                    ),
                )
                self.assertEqual(0, main(["check", "--target", str(target)]))
            self.assertTrue((target / ".codex/agents/reviewer.toml").is_file())


if __name__ == "__main__":
    unittest.main()
