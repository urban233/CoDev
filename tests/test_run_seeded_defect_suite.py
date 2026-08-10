from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_seeded_defect_suite


class SeededDefectFixtureNameTests(unittest.TestCase):
    def test_finds_only_seeded_defect_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "seeded-defect-b").mkdir()
            (root / "seeded-defect-a").mkdir()
            (root / "normalize-slug").mkdir()
            (root / "seeded-defect-c.txt").write_text("not a dir", encoding="utf-8")
            names = run_seeded_defect_suite.seeded_defect_fixture_names(root)
        self.assertEqual(["seeded-defect-a", "seeded-defect-b"], names)

    def test_missing_root_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "does-not-exist"
            self.assertEqual(
                [], run_seeded_defect_suite.seeded_defect_fixture_names(missing)
            )


class RunSuiteTests(unittest.TestCase):
    def test_splits_passed_and_failed_by_evaluate_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with patch.object(
                run_seeded_defect_suite,
                "evaluate",
                side_effect=[True, False, True],
            ):
                passed, failed = run_seeded_defect_suite.run_suite(
                    ["a", "b", "c"], repo=Path(directory), output=output
                )
        self.assertEqual(["a", "c"], passed)
        self.assertEqual(["b"], failed)

    def test_evaluation_error_counts_as_failed(self) -> None:
        from codev_workflow.eval import EvaluationError

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with patch.object(
                run_seeded_defect_suite,
                "evaluate",
                side_effect=EvaluationError("actor launch failed"),
            ):
                passed, failed = run_seeded_defect_suite.run_suite(
                    ["a"], repo=Path(directory), output=output
                )
        self.assertEqual([], passed)
        self.assertEqual(["a"], failed)


class MainTests(unittest.TestCase):
    def test_exits_nonzero_when_any_fixture_is_missed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                run_seeded_defect_suite,
                "seeded_defect_fixture_names",
                return_value=["a", "b"],
            ),
            patch.object(
                run_seeded_defect_suite, "evaluate", side_effect=[True, False]
            ),
        ):
            code = run_seeded_defect_suite.main(["--output", directory])
        self.assertEqual(1, code)

    def test_exits_zero_when_every_fixture_is_caught(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                run_seeded_defect_suite,
                "seeded_defect_fixture_names",
                return_value=["a", "b"],
            ),
            patch.object(run_seeded_defect_suite, "evaluate", side_effect=[True, True]),
        ):
            code = run_seeded_defect_suite.main(["--output", directory])
        self.assertEqual(0, code)

    def test_exits_nonzero_when_no_fixtures_found(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                run_seeded_defect_suite, "seeded_defect_fixture_names", return_value=[]
            ),
        ):
            code = run_seeded_defect_suite.main(["--output", directory])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
