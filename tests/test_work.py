from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codev_workflow.work import (
    REQUIRED_COVERAGE_DIMENSIONS,
    CheckResult,
    WorkError,
    check,
    close,
    describe,
    describe_all,
    log_text,
    record_builder,
    record_reviewer,
    start,
)

FULL_COVERAGE = {
    dimension: {"passed": True, "evidence": f"checked {dimension}"}
    for dimension in REQUIRED_COVERAGE_DIMENSIONS
}


class StartTests(unittest.TestCase):
    def test_start_creates_round_one_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            path = start("item-1", "base-sha", target=target)
            self.assertTrue(path.exists())
            summary = describe("item-1", target=target)
            self.assertEqual(
                {
                    "work_item_id": "item-1",
                    "status": "in_progress",
                    "current_round": 1,
                    "max_rounds": 2,
                    "latest_decision": None,
                },
                summary,
            )

    def test_start_refuses_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(WorkError):
                start("item-1", "base-sha", target=target)

    def test_start_rejects_invalid_id(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("../escape", "base-sha", target=Path(directory))

    def test_start_rejects_non_positive_max_rounds(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), max_rounds=0)


class RoundOpeningTests(unittest.TestCase):
    def test_cannot_skip_a_round_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(WorkError):
                record_builder("item-1", 3, "head-sha", {}, target=target)

    def test_cannot_open_round_two_without_changes_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            with self.assertRaises(WorkError):
                record_builder("item-1", 2, "head-2", {}, target=target)

    def test_cannot_exceed_max_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=1)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            with self.assertRaises(WorkError):
                record_builder("item-1", 2, "head-2", {}, target=target)

    def test_cannot_double_record_same_role_in_a_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "base-sha", {"delivered": "x"}, target=target)
            with self.assertRaises(WorkError):
                record_builder(
                    "item-1", 1, "base-sha", {"delivered": "y"}, target=target
                )


class RecordValidationTests(unittest.TestCase):
    def test_finding_requires_blocking_bool_and_int_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            bad = [
                {
                    "id": "f1",
                    "location": "a.py:1",
                    "category": "correctness",
                    "blocking": "yes",
                    "rank": 1,
                    "summary": "bug",
                }
            ]
            with self.assertRaises(WorkError):
                record_reviewer(
                    "item-1", 1, "base-sha", bad, {}, "CHANGES_REQUIRED", target=target
                )

    def test_duplicate_finding_ids_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            findings = [
                {
                    "id": "f1",
                    "location": "a.py:1",
                    "category": "correctness",
                    "blocking": True,
                    "rank": 1,
                    "summary": "bug",
                },
                {
                    "id": "f1",
                    "location": "b.py:2",
                    "category": "scope",
                    "blocking": False,
                    "rank": 2,
                    "summary": "nit",
                },
            ]
            with self.assertRaises(WorkError):
                record_reviewer(
                    "item-1",
                    1,
                    "base-sha",
                    findings,
                    {},
                    "CHANGES_REQUIRED",
                    target=target,
                )

    def test_unknown_coverage_dimension_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(WorkError):
                record_reviewer(
                    "item-1",
                    1,
                    "base-sha",
                    [],
                    {"not_a_real_dimension": {"passed": True, "evidence": "x"}},
                    "READY_FOR_HUMAN_APPROVAL",
                    target=target,
                )

    def test_invalid_decision_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(WorkError):
                record_reviewer(
                    "item-1", 1, "base-sha", [], {}, "LOOKS_FINE", target=target
                )


class CheckTests(unittest.TestCase):
    def _blocking_finding(
        self, location: str, category: str, rank: int = 1
    ) -> dict[str, object]:
        return {
            "id": f"f-{location}-{category}",
            "location": location,
            "category": category,
            "blocking": True,
            "rank": rank,
            "summary": "needs a fix",
        }

    def test_waiting_on_reviewer_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            result = check("item-1", "base-sha", target=target)
        self.assertEqual(
            CheckResult(True, "ok_waiting_on_reviewer", result.message), result
        )

    def test_drift_detected_against_expected_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            result = check("item-1", "someone-elses-commit", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_drift", result.reason)

    def test_changes_required_under_cap_is_ok_continue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=2)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [self._blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual("ok_continue", result.reason)
        self.assertTrue(result.ok)

    def test_round_cap_reached_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=1)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [self._blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_round_cap", result.reason)

    def test_repeated_blocking_finding_stops_before_round_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=5)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [self._blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            record_builder("item-1", 2, "base-sha", {"delivered": "fix"}, target=target)
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [self._blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_repeated_finding", result.reason)

    def test_non_blocking_repeat_does_not_stop_the_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=5)
            nit = {
                "id": "n1",
                "location": "a.py:1",
                "category": "style",
                "blocking": False,
                "rank": 3,
                "summary": "consider renaming",
            }
            record_reviewer(
                "item-1", 1, "base-sha", [nit], {}, "CHANGES_REQUIRED", target=target
            )
            record_builder("item-1", 2, "base-sha", {"delivered": "fix"}, target=target)
            record_reviewer(
                "item-1", 2, "base-sha", [nit], {}, "CHANGES_REQUIRED", target=target
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual("ok_continue", result.reason)

    def test_ready_for_approval_with_full_coverage_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual(CheckResult(True, "ok_approve", result.message), result)

    def test_ready_for_approval_with_missing_dimension_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            incomplete = {
                key: value for key, value in FULL_COVERAGE.items() if key != "rollout"
            }
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                incomplete,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_incomplete_coverage", result.reason)
        self.assertIn("rollout", result.message)

    def test_ready_for_approval_with_a_failing_dimension_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            failing = dict(FULL_COVERAGE)
            failing["rollout"] = {"passed": False, "evidence": "rollback undocumented"}
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                failing,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_incomplete_coverage", result.reason)

    def test_blocked_by_missing_evidence_is_ok_but_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                {},
                "BLOCKED_BY_MISSING_EVIDENCE",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertTrue(result.ok)
        self.assertEqual("ok_blocked_missing_evidence", result.reason)


class CloseTests(unittest.TestCase):
    def test_close_sets_status_and_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            summary = describe("item-1", target=target)
            self.assertEqual("closed", summary["status"])

    def test_cannot_record_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            with self.assertRaises(WorkError):
                record_builder("item-1", 1, "base-sha", {}, target=target)

    def test_cannot_close_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            with self.assertRaises(WorkError):
                close("item-1", "approved", target=target)

    def test_invalid_outcome_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(WorkError):
                close("item-1", "maybe", target=target)


class DescribeAllTests(unittest.TestCase):
    def test_lists_every_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            start("item-2", "base-sha", target=target)
            ids = sorted(item["work_item_id"] for item in describe_all(target=target))
        self.assertEqual(["item-1", "item-2"], ids)

    def test_empty_when_nothing_started(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual([], describe_all(target=Path(directory)))


class LogTextTests(unittest.TestCase):
    def test_log_includes_round_and_finding_detail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            finding = {
                "id": "f1",
                "location": "a.py:1",
                "category": "correctness",
                "blocking": True,
                "rank": 1,
                "summary": "off-by-one",
            }
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [finding],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            text = log_text("item-1", target=target)
        self.assertIn("round 1:", text)
        self.assertIn("CHANGES_REQUIRED", text)
        self.assertIn("BLOCKING", text)
        self.assertIn("a.py:1", text)


if __name__ == "__main__":
    unittest.main()
