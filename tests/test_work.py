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
    escalations_text,
    log_text,
    read_escalations,
    record_builder,
    record_escalation,
    record_reviewer,
    record_triage,
    start,
    triage_note,
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
                    "current_phase": "inner",
                    "max_rounds": {"inner": 2, "outer": 2},
                    "latest_decision": None,
                    "link_ref": None,
                    "summary": None,
                    "owner": None,
                },
                summary,
            )

    def test_start_accepts_link_summary_and_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                link_ref="docs/codev/work/item-1/implementation-plan.md",
                summary="Fix the thing",
                owner="octocat",
            )
            summary = describe("item-1", target=target)
            self.assertEqual(
                "docs/codev/work/item-1/implementation-plan.md", summary["link_ref"]
            )
            self.assertEqual("Fix the thing", summary["summary"])
            self.assertEqual("octocat", summary["owner"])

    def test_start_rejects_empty_link(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), link_ref="   ")

    def test_start_rejects_empty_summary(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), summary="")

    def test_start_rejects_empty_owner(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), owner="")

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

    def test_log_includes_summary_link_and_owner_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                link_ref="https://github.com/o/r/issues/1",
                summary="Fix the thing",
                owner="octocat",
            )
            text = log_text("item-1", target=target)
        self.assertIn("summary: Fix the thing", text)
        self.assertIn("link: https://github.com/o/r/issues/1", text)
        self.assertIn("owner: octocat", text)

    def test_log_omits_summary_link_and_owner_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            text = log_text("item-1", target=target)
        self.assertNotIn("summary:", text)
        self.assertNotIn("link:", text)
        self.assertNotIn("owner:", text)


def _blocking_finding(
    location: str, category: str, rank: int = 1, expansion_reason: str | None = None
) -> dict[str, object]:
    finding: dict[str, object] = {
        "id": f"f-{location}-{category}",
        "location": location,
        "category": category,
        "blocking": True,
        "rank": rank,
        "summary": "needs a fix",
    }
    if expansion_reason is not None:
        finding["expansion_reason"] = expansion_reason
    return finding


class CoverageDimensionsTests(unittest.TestCase):
    def test_concurrency_is_its_own_dimension(self) -> None:
        self.assertIn("concurrency", REQUIRED_COVERAGE_DIMENSIONS)
        self.assertIn(
            "security_privacy_data_compatibility", REQUIRED_COVERAGE_DIMENSIONS
        )
        self.assertNotIn(
            "security_privacy_data_concurrency_compatibility",
            REQUIRED_COVERAGE_DIMENSIONS,
        )


class MaxRoundsNormalizationTests(unittest.TestCase):
    def test_int_applies_to_both_phases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=3)
            summary = describe("item-1", target=target)
        self.assertEqual({"inner": 3, "outer": 3}, summary["max_rounds"])

    def test_none_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            summary = describe("item-1", target=target)
        self.assertEqual({"inner": 2, "outer": 2}, summary["max_rounds"])

    def test_dict_sets_each_phase_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                max_rounds={"inner": 4, "outer": 1},
            )
            summary = describe("item-1", target=target)
        self.assertEqual({"inner": 4, "outer": 1}, summary["max_rounds"])

    def test_dict_missing_a_phase_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), max_rounds={"inner": 2})

    def test_dict_with_unknown_phase_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start(
                "item-1",
                "base-sha",
                target=Path(directory),
                max_rounds={"inner": 2, "outer": 2, "sideways": 1},
            )

    def test_bool_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(WorkError),
        ):
            start("item-1", "base-sha", target=Path(directory), max_rounds=True)


class ReadyForOuterLoopTests(unittest.TestCase):
    def test_ready_for_outer_loop_skips_the_coverage_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                {"correctness": {"passed": True, "evidence": "checked"}},
                "READY_FOR_OUTER_LOOP",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual(CheckResult(True, "ok_ready_for_pr", result.message), result)

    def test_opens_the_outer_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_builder(
                "item-1", 2, "head-2", {"delivered": "opened pr"}, target=target
            )
            text = log_text("item-1", target=target)
        self.assertIn("round 1:\n  phase: inner", text)
        self.assertIn("round 2:\n  phase: outer", text)

    def test_ready_for_outer_loop_from_outer_phase_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_builder("item-1", 2, "head-2", {}, target=target)
            record_reviewer(
                "item-1",
                2,
                "head-2",
                [],
                {},
                "READY_FOR_OUTER_LOOP",
                target=target,
            )
            with self.assertRaises(WorkError):
                record_builder("item-1", 3, "head-3", {}, target=target)


class ScopeExpansionTests(unittest.TestCase):
    def _to_second_inner_round(
        self, target: Path, round_one_finding: dict[str, object]
    ) -> None:
        start("item-1", "base-sha", target=target, max_rounds=5)
        record_reviewer(
            "item-1",
            1,
            "base-sha",
            [round_one_finding],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        record_builder("item-1", 2, "base-sha", {"delivered": "fix"}, target=target)

    def test_new_untagged_finding_stops_as_scope_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_second_inner_round(
                target, _blocking_finding("a.py:1", "correctness")
            )
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [_blocking_finding("b.py:9", "architecture_scope")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_scope_expansion", result.reason)

    def test_regression_tagged_finding_does_not_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_second_inner_round(
                target, _blocking_finding("a.py:1", "correctness")
            )
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [
                    _blocking_finding(
                        "b.py:9", "architecture_scope", expansion_reason="regression"
                    )
                ],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual("ok_continue", result.reason)

    def test_newly_discovered_critical_does_not_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_second_inner_round(
                target, _blocking_finding("a.py:1", "correctness")
            )
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [
                    _blocking_finding(
                        "b.py:9",
                        "security_privacy_data_compatibility",
                        expansion_reason="newly_discovered_critical",
                    )
                ],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual("ok_continue", result.reason)

    def test_a_repeat_of_round_ones_own_finding_is_not_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            finding = _blocking_finding("a.py:1", "correctness")
            self._to_second_inner_round(target, finding)
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [finding],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "base-sha", target=target)
        # a genuine repeat is stop_repeated_finding, not stop_scope_expansion
        self.assertEqual("stop_repeated_finding", result.reason)


class TriageTests(unittest.TestCase):
    def _to_outer_round_one_with_findings(
        self,
        target: Path,
        findings: list[dict[str, object]],
        *,
        owner: str | None = None,
    ) -> None:
        start("item-1", "base-sha", target=target, owner=owner)
        record_reviewer(
            "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        record_builder("item-1", 2, "head-2", {}, target=target)
        record_reviewer(
            "item-1", 2, "head-2", findings, {}, "CHANGES_REQUIRED", target=target
        )

    def test_check_waits_on_triage_before_round_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            result = check("item-1", "head-2", target=target)
        self.assertEqual(
            CheckResult(True, "ok_waiting_on_triage", result.message), result
        )

    def test_triage_requires_a_disposition_for_every_blocking_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            with self.assertRaises(WorkError):
                record_triage("item-1", 2, {"dispositions": {}}, target=target)

    def test_deferring_a_blocking_finding_requires_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            with self.assertRaises(WorkError):
                record_triage(
                    "item-1",
                    2,
                    {"dispositions": {finding_id: {"disposition": "defer"}}},
                    target=target,
                )

    def test_deferring_with_a_reason_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {
                    "dispositions": {
                        finding_id: {
                            "disposition": "defer",
                            "override_reason": "accepted risk for this release",
                        }
                    }
                },
                target=target,
            )
            text = log_text("item-1", target=target)
        self.assertIn("defer (accepted risk for this release)", text)

    def test_nit_needs_no_reason_to_defer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            nit = {
                "id": "n1",
                "location": "a.py:1",
                "category": "style",
                "blocking": False,
                "rank": 3,
                "summary": "consider renaming",
            }
            self._to_outer_round_one_with_findings(target, [nit])
            record_triage(
                "item-1",
                2,
                {"dispositions": {"n1": {"disposition": "defer"}}},
                target=target,
            )

    def test_unknown_finding_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            with self.assertRaises(WorkError):
                record_triage(
                    "item-1",
                    2,
                    {"dispositions": {"not-a-real-id": {"disposition": "address"}}},
                    target=target,
                )

    def test_cannot_triage_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            payload = {"dispositions": {finding_id: {"disposition": "address"}}}
            record_triage("item-1", 2, payload, target=target)
            with self.assertRaises(WorkError):
                record_triage("item-1", 2, payload, target=target)

    def test_cannot_triage_the_inner_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [_blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            with self.assertRaises(WorkError):
                record_triage(
                    "item-1",
                    1,
                    {
                        "dispositions": {
                            "f-a.py:1-correctness": {"disposition": "address"}
                        }
                    },
                    target=target,
                )

    def test_round_may_open_once_triage_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
            )
            result = check("item-1", "head-2", target=target)
            self.assertEqual("ok_continue", result.reason)
            record_builder("item-1", 3, "head-3", {"delivered": "fix"}, target=target)
            summary = describe("item-1", target=target)
        self.assertEqual("outer", summary["current_phase"])

    def test_round_cannot_open_without_triage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            with self.assertRaises(WorkError):
                record_builder("item-1", 3, "head-3", {}, target=target)

    def test_record_triage_stores_by(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
                by="octocat",
            )
            text = log_text("item-1", target=target)
        self.assertIn("triage (by octocat):", text)

    def test_record_triage_rejects_empty_by(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            with self.assertRaises(WorkError):
                record_triage(
                    "item-1",
                    2,
                    {"dispositions": {finding_id: {"disposition": "address"}}},
                    target=target,
                    by="   ",
                )

    def test_triage_note_when_by_matches_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")], owner="octocat"
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
                by="octocat",
            )
            note = triage_note("item-1", target=target)
            text = log_text("item-1", target=target)
        self.assertEqual(
            "note: octocat both owns this work item and triaged this round", note
        )
        self.assertIn(note, text)

    def test_triage_note_none_when_by_differs_from_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")], owner="octocat"
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
                by="someone-else",
            )
            note = triage_note("item-1", target=target)
        self.assertIsNone(note)

    def test_triage_note_none_when_no_owner_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
                by="octocat",
            )
            note = triage_note("item-1", target=target)
        self.assertIsNone(note)

    def test_triage_note_none_before_any_triage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")], owner="octocat"
            )
            note = triage_note("item-1", target=target)
        self.assertIsNone(note)

    def test_outer_round_cap_is_two_not_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            finding = _blocking_finding("a.py:1", "concurrency")
            self._to_outer_round_one_with_findings(target, [finding])
            finding_id = "f-a.py:1-concurrency"
            record_triage(
                "item-1",
                2,
                {"dispositions": {finding_id: {"disposition": "address"}}},
                target=target,
            )
            record_builder("item-1", 3, "head-3", {"delivered": "fix"}, target=target)
            record_reviewer(
                "item-1",
                3,
                "head-3",
                [finding],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_repeated_finding", result.reason)


class EscalationLogTests(unittest.TestCase):
    def test_no_file_yet_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual([], read_escalations(target=target))
            self.assertEqual(
                "No escalations recorded.\n", escalations_text(target=target)
            )

    def test_record_and_read_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation(
                "item-1",
                "stop_round_cap",
                "round 2 of 2 for phase 'inner'",
                target=target,
                phase="inner",
                round_number=2,
            )
            records = read_escalations(target=target)
        self.assertEqual(1, len(records))
        self.assertEqual("item-1", records[0]["work_item_id"])
        self.assertEqual("stop_round_cap", records[0]["trigger"])
        self.assertEqual("inner", records[0]["phase"])
        self.assertEqual(2, records[0]["round"])
        self.assertIn("T", records[0]["timestamp"])

    def test_pre_build_critical_interrupt_has_no_phase_or_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation(
                "item-1",
                "critical_interrupt",
                "touches auth/ per the risk-overrides-size rule",
                target=target,
            )
            records = read_escalations(target=target)
        self.assertIsNone(records[0]["phase"])
        self.assertIsNone(records[0]["round"])

    def test_multiple_records_append_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation(
                "item-1", "stop_drift", "head changed unexpectedly", target=target
            )
            record_escalation(
                "item-2",
                "human_override_blocking_finding",
                "accepted risk for this release",
                target=target,
            )
            records = read_escalations(target=target)
        self.assertEqual(["item-1", "item-2"], [r["work_item_id"] for r in records])

    def test_unknown_trigger_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(WorkError):
                record_escalation("item-1", "not_a_real_trigger", "why", target=target)

    def test_empty_cause_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(WorkError):
                record_escalation("item-1", "stop_drift", "   ", target=target)

    def test_invalid_phase_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(WorkError):
                record_escalation(
                    "item-1", "stop_drift", "why", target=target, phase="sideways"
                )

    def test_read_filters_by_work_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation("item-1", "stop_drift", "a", target=target)
            record_escalation("item-2", "stop_drift", "b", target=target)
            records = read_escalations(target=target, work_item_id="item-2")
        self.assertEqual(1, len(records))
        self.assertEqual("item-2", records[0]["work_item_id"])

    def test_read_filters_by_since(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation("item-1", "stop_drift", "a", target=target)
            far_future = "2999-01-01T00:00:00Z"
            records = read_escalations(target=target, since=far_future)
        self.assertEqual([], records)

    def test_escalations_text_reads_as_one_line_per_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation(
                "item-1",
                "stop_scope_expansion",
                "finding at b.py:9 not in round 1",
                target=target,
                phase="outer",
                round_number=2,
            )
            text = escalations_text(target=target)
        self.assertIn("item-1", text)
        self.assertIn("[outer/round 2]", text)
        self.assertIn("stop_scope_expansion", text)
        self.assertIn("finding at b.py:9 not in round 1", text)


if __name__ == "__main__":
    unittest.main()
