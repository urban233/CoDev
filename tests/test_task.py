# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from codev_workflow.task import (
    REQUIRED_COVERAGE_DIMENSIONS,
    ROUND_SCHEMA_VERSION,
    SUPPORTED_ROUND_SCHEMA_VERSIONS,
    CheckResult,
    TaskError,
    _load,
    _save,
    advance_slice,
    check,
    close,
    current_slice,
    deprecated_reason_for,
    describe,
    describe_all,
    escalations_text,
    is_final_slice,
    log_text,
    pr_description,
    read_escalations,
    record_builder,
    record_escalation,
    record_restack,
    record_reviewer,
    record_triage,
    relink,
    reopen,
    slice_ids,
    start,
    triage_note,
    waive,
)

FULL_COVERAGE = {
    dimension: {"passed": True, "evidence": f"checked {dimension}"}
    for dimension in REQUIRED_COVERAGE_DIMENSIONS
}


def _state_path(target: Path, task_id: str) -> Path:
    return target / ".codev" / "task" / task_id / "round-state.json"


def _read_state(target: Path, task_id: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        _state_path(target, task_id).read_text(encoding="utf-8")
    )
    return document


def _rewrite_as_v3(target: Path, task_id: str) -> None:
    """Downgrade a written v4 document to the v3 form a task recorded before
    this schema still has on disk. Slice D1 writes v4, so this is now the
    direction backward compatibility runs in."""
    path = _state_path(target, task_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["round_schema_version"] = 3
    document.pop("slices", None)
    for round_entry in document["rounds"]:
        round_entry.pop("slice_id", None)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _blocking(location: str, category: str) -> dict[str, Any]:
    return {
        "id": f"f-{location}-{category}",
        "location": location,
        "category": category,
        "blocking": True,
        "rank": 1,
        "summary": "needs a fix",
    }


class IndependentReviewerTests(unittest.TestCase):
    """ADR-0037: the task owns its independent reviewer, and the owner --
    the author of the change, however little of it they typed -- cannot be
    it."""

    def test_a_task_records_its_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target, owner="@alice", reviewer="@bob")
            self.assertEqual("@bob", describe("item-1", target=target)["reviewer"])

    def test_the_owner_cannot_be_their_own_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(TaskError) as caught:
                start("item-1", "base", target=target, owner="@a", reviewer="@a")
        self.assertIn("must not be the task owner", str(caught.exception))


class SliceListTests(unittest.TestCase):
    """ADR-0035, slice D2: the task owns the ordered slice list, and the
    list is what says whether anything in the task still has to land."""

    def test_a_single_slice_task_is_its_own_final_slice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            self.assertEqual("item-1", current_slice("item-1", target=target))
            self.assertTrue(is_final_slice("item-1", "item-1", target=target))

    def test_only_the_last_slice_of_a_multi_slice_task_is_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target, slices=["a", "b", "c"])
            self.assertFalse(is_final_slice("item-1", "a", target=target))
            self.assertFalse(is_final_slice("item-1", "b", target=target))
            self.assertTrue(is_final_slice("item-1", "c", target=target))

    def test_a_task_starts_on_its_first_slice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target, slices=["a", "b"])
            self.assertEqual("a", current_slice("item-1", target=target))
            self.assertFalse(
                is_final_slice(
                    "item-1", current_slice("item-1", target=target), target=target
                )
            )

    def test_advancing_moves_to_the_next_slice_and_opens_a_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target, slices=["a", "b"])
            self.assertEqual(
                "b", advance_slice("item-1", "slice-a-head", target=target)
            )
            document = _read_state(target, "item-1")
        self.assertEqual("b", document["current_slice"])
        self.assertEqual("b", document["rounds"][-1]["slice_id"])
        self.assertEqual("inner", document["rounds"][-1]["phase"])
        self.assertEqual("slice-a-head", document["base_snapshot"])

    def test_a_round_opened_after_a_later_slice_exists_stays_on_the_current_one(
        self,
    ) -> None:
        """The defect the review of slice D1 flagged: returning the *last*
        slice would silently attach this round to `b`."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target, slices=["a", "b"])
            record_reviewer(
                "item-1",
                1,
                "base",
                [_blocking("x.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            record_builder("item-1", 2, "base", {"validation": "ok"}, target=target)
            document = _read_state(target, "item-1")
        self.assertEqual("a", document["rounds"][1]["slice_id"])

    def test_advancing_past_the_final_slice_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base", target=target)
            with self.assertRaises(TaskError):
                advance_slice("item-1", "head", target=target)

    def test_a_declared_slice_list_rejects_duplicates_and_emptiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(TaskError):
                start("dup", "base", target=target, slices=["a", "a"])
            with self.assertRaises(TaskError):
                start("empty", "base", target=target, slices=[])


class DeprecatedReasonAliasTests(unittest.TestCase):
    """ADR-0037: a returned reason is part of the machine contract, so the
    rename reports the former name for one release rather than silently
    ceasing to match a pinned consumer."""

    def test_only_the_two_renamed_reasons_have_a_former_name(self) -> None:
        self.assertEqual(
            "ok_approve", deprecated_reason_for("ok_machine_review_complete")
        )
        self.assertEqual(
            "ok_approve_with_deferrals",
            deprecated_reason_for("ok_machine_review_complete_with_deferrals"),
        )
        for untouched in ("ok_continue", "stop_drift", "ok_ready_for_pr"):
            self.assertIsNone(deprecated_reason_for(untouched))

    def test_the_old_names_are_no_longer_returned_by_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="direct-review")
            record_reviewer(
                "item-1",
                1,
                "head-sha",
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "head-sha", target=target)
        self.assertEqual("ok_machine_review_complete", result.reason)


class SchemaVersionFourTests(unittest.TestCase):
    """ADR-0035, slice D-prep-1. The reader understands v4; the writers still
    emit v3, so a revert of this slice leaves nothing on disk to migrate."""

    def test_writes_are_version_four(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head-sha", {"validation": "ok"}, target=target)
            document = _read_state(target, "item-1")
        self.assertEqual(ROUND_SCHEMA_VERSION, document["round_schema_version"])
        self.assertEqual(4, ROUND_SCHEMA_VERSION)

    def test_every_written_round_records_the_slice_it_belongs_to(self) -> None:
        """Rounds opened later must carry the identity too, not only round 1."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [_blocking("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            record_builder("item-1", 2, "base-sha", {"validation": "ok"}, target=target)
            document = _read_state(target, "item-1")
        self.assertEqual(["item-1"], document["slices"])
        self.assertEqual(2, len(document["rounds"]))
        for round_entry in document["rounds"]:
            self.assertEqual("item-1", round_entry["slice_id"])

    def test_a_reopened_round_records_the_slice_too(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            reopen("item-1", "new-head", "continuing", target=target)
            document = _read_state(target, "item-1")
        self.assertEqual("item-1", document["rounds"][-1]["slice_id"])

    def test_loading_and_saving_a_v4_document_is_byte_identical(self) -> None:
        """No strip remains between memory and disk, so a load-then-save round
        trip must not move a single byte -- the gap the review of slice
        D-prep-1 flagged as untested."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head-sha", {"validation": "ok"}, target=target)
            path = _state_path(target, "item-1")
            before = path.read_bytes()
            _save("item-1", _load("item-1", target=target), target=target)
            after = path.read_bytes()
        self.assertEqual(before, after)

    def test_a_v3_document_is_upgraded_in_place_when_next_written(self) -> None:
        """The migration is a defaulted field on read plus an ordinary write:
        a legacy task becomes v4 the next time anything records against it."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            _rewrite_as_v3(target, "item-1")
            self.assertEqual(3, _read_state(target, "item-1")["round_schema_version"])
            record_builder("item-1", 1, "head-sha", {"validation": "ok"}, target=target)
            document = _read_state(target, "item-1")
        self.assertEqual(4, document["round_schema_version"])
        self.assertEqual(["item-1"], document["slices"])
        self.assertEqual("item-1", document["rounds"][0]["slice_id"])

    def test_a_version_three_task_reads_as_one_slice_named_for_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            self.assertEqual(["item-1"], slice_ids("item-1", target=target))

    def test_a_version_four_document_keeps_its_own_slice_identity(self) -> None:
        """A real v4 document is authoritative: defaulting its rounds would
        silently reassign ones belonging to a later slice."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            path = _state_path(target, "item-1")
            document = json.loads(path.read_text(encoding="utf-8"))
            document["round_schema_version"] = ROUND_SCHEMA_VERSION
            document["slices"] = ["item-1-a", "item-1-b"]
            document["rounds"][0]["slice_id"] = "item-1-b"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(
                ["item-1-a", "item-1-b"], slice_ids("item-1", target=target)
            )

    def test_an_unsupported_version_is_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            path = _state_path(target, "item-1")
            document = json.loads(path.read_text(encoding="utf-8"))
            document["round_schema_version"] = 2
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(TaskError):
                check("item-1", "base-sha", target=target)
        self.assertEqual((3, 4), SUPPORTED_ROUND_SCHEMA_VERSIONS)


class SchemaVersionFourReplayTests(unittest.TestCase):
    """Every `check` outcome must read identically from a v4 document and the
    v3 one a task recorded before this schema still has on disk."""

    def _ok_waiting_on_reviewer(self, target: Path) -> str:
        start("item-1", "base-sha", target=target)
        return "base-sha"

    def _ok_ready_for_pr(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, entry="direct-review")
        return "done-sha"

    def _stop_drift(self, target: Path) -> str:
        start("item-1", "base-sha", target=target)
        return "some-other-sha"

    def _ok_continue(self, target: Path) -> str:
        start("item-1", "base-sha", target=target)
        record_reviewer(
            "item-1",
            1,
            "base-sha",
            [_blocking("a.py:1", "correctness")],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        return "base-sha"

    def _stop_round_cap(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, max_rounds={"inner": 1, "outer": 2})
        record_reviewer(
            "item-1",
            1,
            "base-sha",
            [_blocking("a.py:1", "correctness")],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        return "base-sha"

    def _ok_waiting_on_triage(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, entry="direct-review")
        record_reviewer(
            "item-1",
            1,
            "head-sha",
            [_blocking("a.py:1", "correctness")],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        return "head-sha"

    def _ok_machine_review_complete_with_deferrals(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, entry="direct-review")
        finding = _blocking("a.py:1", "correctness")
        record_reviewer(
            "item-1",
            1,
            "head-sha",
            [finding],
            FULL_COVERAGE,
            "CHANGES_REQUIRED",
            target=target,
        )
        record_triage(
            "item-1",
            1,
            {
                "dispositions": {
                    finding["id"]: {
                        "disposition": "defer",
                        "override_reason": "not this release",
                    }
                }
            },
            target=target,
        )
        return "head-sha"

    def _stop_incomplete_coverage(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, entry="direct-review")
        record_reviewer(
            "item-1", 1, "head-sha", [], {}, "READY_FOR_HUMAN_APPROVAL", target=target
        )
        return "head-sha"

    def _ok_machine_review_complete(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, entry="direct-review")
        record_reviewer(
            "item-1",
            1,
            "head-sha",
            [],
            FULL_COVERAGE,
            "READY_FOR_HUMAN_APPROVAL",
            target=target,
        )
        return "head-sha"

    def _ok_blocked_missing_evidence(self, target: Path) -> str:
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
        return "base-sha"

    def _stop_repeated_finding(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, max_rounds={"inner": 4, "outer": 4})
        finding = _blocking("a.py:1", "correctness")
        record_reviewer(
            "item-1", 1, "base-sha", [finding], {}, "CHANGES_REQUIRED", target=target
        )
        record_builder("item-1", 2, "base-sha", {"validation": "ok"}, target=target)
        record_reviewer(
            "item-1", 2, "base-sha", [finding], {}, "CHANGES_REQUIRED", target=target
        )
        return "base-sha"

    def _stop_scope_expansion(self, target: Path) -> str:
        start("item-1", "base-sha", target=target, max_rounds={"inner": 4, "outer": 4})
        record_reviewer(
            "item-1",
            1,
            "base-sha",
            [_blocking("a.py:1", "correctness")],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        record_builder("item-1", 2, "base-sha", {"validation": "ok"}, target=target)
        record_reviewer(
            "item-1",
            2,
            "base-sha",
            [_blocking("b.py:9", "maintainability")],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        return "base-sha"

    def _ok_outer_loop_needs_reopen(self, target: Path) -> str:
        """Hand-built: record_reviewer refuses to create this shape fresh, so
        the reader's handling of it is defense-in-depth (ADR-0017)."""
        start("item-1", "base-sha", target=target)
        path = _state_path(target, "item-1")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["rounds"][0]["phase"] = "outer"
        document["rounds"][0]["reviewer"] = {
            "head_snapshot": "head-sha",
            "decision": "READY_FOR_OUTER_LOOP",
            "findings": [],
            "coverage": {},
        }
        path.write_text(json.dumps(document), encoding="utf-8")
        return "head-sha"

    def test_every_check_outcome_reads_identically_from_v3_and_v4(self) -> None:
        builders = {
            "ok_waiting_on_reviewer": self._ok_waiting_on_reviewer,
            "ok_ready_for_pr": self._ok_ready_for_pr,
            "stop_drift": self._stop_drift,
            "ok_continue": self._ok_continue,
            "stop_round_cap": self._stop_round_cap,
            "ok_waiting_on_triage": self._ok_waiting_on_triage,
            "ok_machine_review_complete_with_deferrals": (
                self._ok_machine_review_complete_with_deferrals
            ),
            "stop_incomplete_coverage": self._stop_incomplete_coverage,
            "ok_machine_review_complete": self._ok_machine_review_complete,
            "ok_blocked_missing_evidence": self._ok_blocked_missing_evidence,
            "stop_repeated_finding": self._stop_repeated_finding,
            "stop_scope_expansion": self._stop_scope_expansion,
            "ok_outer_loop_needs_reopen": self._ok_outer_loop_needs_reopen,
        }
        observed = set()
        for expected_reason, build in builders.items():
            with self.subTest(reason=expected_reason):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)
                    head = build(target)
                    from_v4 = check("item-1", head, target=target)
                    self.assertEqual(expected_reason, from_v4.reason)
                    _rewrite_as_v3(target, "item-1")
                    from_v3 = check("item-1", head, target=target)
                self.assertEqual(from_v4, from_v3)
                observed.add(from_v4.reason)
        self.assertEqual(set(builders), observed)


class StartTests(unittest.TestCase):
    def test_start_creates_round_one_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            path = start("item-1", "base-sha", target=target)
            self.assertTrue(path.exists())
            summary = describe("item-1", target=target)
            self.assertEqual(
                {
                    "task_id": "item-1",
                    "status": "in_progress",
                    "current_round": 1,
                    "current_phase": "inner",
                    "max_rounds": {"inner": 2, "outer": 2},
                    "latest_decision": None,
                    "link_ref": None,
                    "summary": None,
                    "description": None,
                    "owner": None,
                    "reviewer": None,
                    "entry": None,
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

    def test_start_accepts_entry_takeover_and_keeps_inner_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="takeover")
            summary = describe("item-1", target=target)
        self.assertEqual("takeover", summary["entry"])
        self.assertEqual("inner", summary["current_phase"])

    def test_start_accepts_entry_direct_review_and_opens_outer_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="direct-review")
            summary = describe("item-1", target=target)
        self.assertEqual("direct-review", summary["entry"])
        self.assertEqual("outer", summary["current_phase"])

    def test_start_default_entry_is_none_and_inner_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            summary = describe("item-1", target=target)
        self.assertIsNone(summary["entry"])
        self.assertEqual("inner", summary["current_phase"])

    def test_start_rejects_invalid_entry(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), entry="bogus")

    def test_start_rejects_empty_link(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), link_ref="   ")

    def test_start_rejects_empty_summary(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), summary="")

    def test_start_rejects_empty_owner(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), owner="")

    def test_start_refuses_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                start("item-1", "base-sha", target=target)

    def test_start_rejects_invalid_id(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("../escape", "base-sha", target=Path(directory))

    def test_start_rejects_non_positive_max_rounds(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), max_rounds=0)


class RoundOpeningTests(unittest.TestCase):
    def test_cannot_skip_a_round_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
                record_builder("item-1", 2, "head-2", {}, target=target)

    def test_cannot_double_record_same_role_in_a_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "base-sha", {"delivered": "x"}, target=target)
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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

    def test_direct_review_entry_is_ready_for_pr_without_a_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="direct-review")
            # A human's finished branch is already beyond base -- this would
            # be stop_drift for a cold-start item, but direct-review has no
            # inner-loop evidence to drift against.
            result = check("item-1", "humans-finished-commit", target=target)
        self.assertEqual(CheckResult(True, "ok_ready_for_pr", result.message), result)

    def test_direct_review_entry_with_recorded_round_behaves_normally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="direct-review")
            record_reviewer(
                "item-1",
                1,
                "humans-finished-commit",
                [self._blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            result = check("item-1", "humans-finished-commit", target=target)
        self.assertEqual("ok_waiting_on_triage", result.reason)

    def test_takeover_entry_waits_on_reviewer_like_cold_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, entry="takeover")
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
        self.assertEqual(
            CheckResult(True, "ok_machine_review_complete", result.message), result
        )

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
            with self.assertRaises(TaskError):
                record_builder("item-1", 1, "base-sha", {}, target=target)

    def test_cannot_close_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            with self.assertRaises(TaskError):
                close("item-1", "approved", target=target)

    def test_invalid_outcome_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                close("item-1", "maybe", target=target)


class ReopenTests(unittest.TestCase):
    def test_reopen_missing_item_raises(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
        ):
            reopen("item-1", "new-head", "human approved", target=Path(directory))

    def test_reopen_rejects_empty_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                reopen("item-1", "   ", "human approved", target=target)

    def test_reopen_rejects_empty_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                reopen("item-1", "new-head", "", target=target)

    def test_reopen_closed_item_returns_to_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "escalated", target=target)
            reopen("item-1", "new-head", "human approved a manual fix", target=target)
            summary = describe("item-1", target=target)
        self.assertEqual("in_progress", summary["status"])

    def test_reopen_rebaselines_base_snapshot_and_clears_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head1", {}, target=target)
            record_reviewer(
                "item-1", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            self.assertFalse(check("item-1", "drifted-head", target=target).ok)
            reopen(
                "item-1",
                "drifted-head",
                "approved post-convergence fix",
                target=target,
            )
            result = check("item-1", "drifted-head", target=target)
        self.assertTrue(result.ok)
        self.assertEqual("ok_waiting_on_reviewer", result.reason)

    def test_reopen_after_ready_for_outer_loop_opens_outer_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head1", {}, target=target)
            record_reviewer(
                "item-1", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            reopen(
                "item-1", "new-head", "approved fix after convergence", target=target
            )
            summary = describe("item-1", target=target)
        self.assertEqual("outer", summary["current_phase"])
        self.assertEqual(2, summary["current_round"])

    def test_reopen_otherwise_continues_same_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head1", {}, target=target)
            record_reviewer(
                "item-1",
                1,
                "head1",
                [_blocking_finding("a.py", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            reopen(
                "item-1",
                "new-head",
                "human authorized one more inner round",
                target=target,
            )
            summary = describe("item-1", target=target)
        self.assertEqual("inner", summary["current_phase"])

    def test_reopen_can_raise_max_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=1)
            reopen("item-1", "new-head", "cap was too low", target=target, max_rounds=3)
            summary = describe("item-1", target=target)
        self.assertEqual({"inner": 3, "outer": 3}, summary["max_rounds"])

    def test_reopen_rejects_lowering_max_rounds_below_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=2)
            record_builder("item-1", 1, "head1", {}, target=target)
            record_reviewer(
                "item-1",
                1,
                "head1",
                [_blocking_finding("a.py", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            record_builder("item-1", 2, "head2", {}, target=target)
            record_reviewer(
                "item-1",
                2,
                "head2",
                [_blocking_finding("a.py", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            with self.assertRaises(TaskError):
                reopen(
                    "item-1",
                    "head3",
                    "trying to shrink the cap",
                    target=target,
                    max_rounds=1,
                )

    def test_reopen_records_history_visible_in_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "escalated", target=target)
            reopen(
                "item-1",
                "new-head",
                "human approved continuing after escalation",
                target=target,
                by="octocat",
            )
            text = log_text("item-1", target=target)
        self.assertIn("reopened by octocat after round 1", text)
        self.assertIn("human approved continuing after escalation", text)

    def test_reopen_does_not_mutate_previous_round_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "head1", {"note": "original"}, target=target)
            record_reviewer(
                "item-1", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            reopen("item-1", "new-head", "approved fix", target=target)
            text = log_text("item-1", target=target)
        self.assertIn("builder @ head1", text)
        self.assertIn("reviewer @ head1: READY_FOR_OUTER_LOOP", text)


class RecordRestackTests(unittest.TestCase):
    def test_clears_drift_after_a_rebase_without_opening_a_new_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-2", "base-sha", target=target)
            record_builder("item-2", 1, "head1", {}, target=target)
            record_reviewer(
                "item-2", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            self.assertFalse(check("item-2", "rebased-head", target=target).ok)

            record_restack("item-2", "rebased-head", target=target)
            result = check("item-2", "rebased-head", target=target)
            summary = describe("item-2", target=target)

        self.assertTrue(result.ok)
        self.assertEqual("ok_ready_for_pr", result.reason)
        self.assertEqual(1, summary["current_round"])

    def test_updates_the_current_rounds_recorded_head_not_only_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-2", "base-sha", target=target)
            record_builder("item-2", 1, "head1", {"note": "original"}, target=target)
            record_reviewer(
                "item-2", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_restack("item-2", "rebased-head", target=target)
            text = log_text("item-2", target=target)
        self.assertIn("reviewer @ rebased-head: READY_FOR_OUTER_LOOP", text)

    def test_does_not_mutate_previous_round_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-2", "base-sha", target=target)
            record_builder("item-2", 1, "head1", {}, target=target)
            record_reviewer(
                "item-2", 1, "head1", [], {}, "CHANGES_REQUIRED", target=target
            )
            record_builder("item-2", 2, "head2", {}, target=target)
            record_reviewer(
                "item-2", 2, "head2", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_restack("item-2", "rebased-head", target=target)
            text = log_text("item-2", target=target)
        self.assertIn("builder @ head1", text)
        self.assertIn("reviewer @ head1: CHANGES_REQUIRED", text)
        self.assertIn("reviewer @ rebased-head: READY_FOR_OUTER_LOOP", text)

    def test_refuses_for_a_closed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-2", "base-sha", target=target)
            record_builder("item-2", 1, "head1", {}, target=target)
            record_reviewer(
                "item-2", 1, "head1", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            close("item-2", "abandoned", target=target)
            with self.assertRaises(TaskError):
                record_restack("item-2", "rebased-head", target=target)

    def test_rejects_empty_new_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-2", "base-sha", target=target)
            with self.assertRaises(TaskError):
                record_restack("item-2", "   ", target=target)


class DescribeAllTests(unittest.TestCase):
    def test_lists_every_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            start("item-2", "base-sha", target=target)
            ids = sorted(item["task_id"] for item in describe_all(target=target))
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
            self.assertRaises(TaskError),
        ):
            start("item-1", "base-sha", target=Path(directory), max_rounds={"inner": 2})

    def test_dict_with_unknown_phase_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(TaskError),
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
            self.assertRaises(TaskError),
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
        """ADR-0017: this decision only means "hand off to the outer loop",
        and only from an inner-phase round -- recording it on a round that is
        already `"outer"` (round 2 here, opened by round 1's own
        READY_FOR_OUTER_LOOP) is rejected at the write site, before it can
        produce a state `_round_slot` would later refuse to build on."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_builder("item-1", 2, "head-2", {}, target=target)
            with self.assertRaises(TaskError) as raised:
                record_reviewer(
                    "item-1",
                    2,
                    "head-2",
                    [],
                    {},
                    "READY_FOR_OUTER_LOOP",
                    target=target,
                )
        self.assertIn("already in the outer phase", str(raised.exception))

    def test_ok_outer_loop_needs_reopen_for_a_pre_existing_corrupted_state(
        self,
    ) -> None:
        """ADR-0017: defense in depth for a round-state.json that already
        carries the corrupted shape this same ADR's write-site guard now
        prevents from being created -- `record_reviewer` refuses it going
        forward, so this constructs it directly on disk, the same shape a
        pre-fix session (the real incident this ADR closes) actually
        produced."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_builder("item-1", 2, "head-2", {}, target=target)
            state_path = target / ".codev" / "task" / "item-1" / "round-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["rounds"][-1]["reviewer"] = {
                "head_snapshot": "head-2",
                "findings": [],
                "coverage": {},
                "decision": "READY_FOR_OUTER_LOOP",
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = check("item-1", "head-2", target=target)
        self.assertEqual(
            CheckResult(True, "ok_outer_loop_needs_reopen", result.message), result
        )
        self.assertIn("codev task reopen", result.message)

    def test_record_reviewer_write_once_message_names_the_fix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "CHANGES_REQUIRED", target=target
            )
            with self.assertRaises(TaskError) as raised:
                record_reviewer(
                    "item-1", 1, "base-sha", [], {}, "CHANGES_REQUIRED", target=target
                )
        self.assertIn("codev task reopen", str(raised.exception))

    def test_record_builder_write_once_message_names_the_fix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_builder("item-1", 1, "base-sha", {}, target=target)
            with self.assertRaises(TaskError) as raised:
                record_builder("item-1", 1, "base-sha", {}, target=target)
        self.assertIn("codev task reopen", str(raised.exception))


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
            with self.assertRaises(TaskError):
                record_triage("item-1", 2, {"dispositions": {}}, target=target)

    def test_deferring_a_blocking_finding_requires_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round_one_with_findings(
                target, [_blocking_finding("a.py:1", "concurrency")]
            )
            finding_id = "f-a.py:1-concurrency"
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            with self.assertRaises(TaskError):
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
            "note: octocat both owns this task and triaged this round", note
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


class AllBlockingDeferredTests(unittest.TestCase):
    """A triaged blocking finding -- deferred or addressed -- has already had
    its one required human look, so it should not keep tripping
    stop_scope_expansion/stop_repeated_finding forever, and an outer round
    whose triage defers every blocking finding has nothing left to build."""

    def _to_outer_round_two_with_new_finding(
        self,
        target: Path,
        round_one_finding: dict[str, object],
        round_two_findings: list[dict[str, object]],
        *,
        coverage: dict[str, Any] | None = None,
    ) -> None:
        start("item-1", "base-sha", target=target)
        record_reviewer(
            "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        record_builder("item-1", 2, "head-2", {}, target=target)
        record_reviewer(
            "item-1",
            2,
            "head-2",
            [round_one_finding],
            {},
            "CHANGES_REQUIRED",
            target=target,
        )
        record_triage(
            "item-1",
            2,
            {"dispositions": {round_one_finding["id"]: {"disposition": "address"}}},
            target=target,
        )
        record_builder("item-1", 3, "head-3", {"delivered": "fix"}, target=target)
        record_reviewer(
            "item-1",
            3,
            "head-3",
            round_two_findings,
            coverage if coverage is not None else {},
            "CHANGES_REQUIRED",
            target=target,
        )

    def test_new_finding_still_stops_before_triage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            self._to_outer_round_two_with_new_finding(
                target, _blocking_finding("a.py:1", "correctness"), [new_finding]
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual("stop_scope_expansion", result.reason)

    def test_deferring_the_new_finding_clears_scope_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [new_finding],
                coverage=FULL_COVERAGE,
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        new_finding["id"]: {
                            "disposition": "defer",
                            "override_reason": "tracked in issue #42",
                        }
                    }
                },
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual(
            CheckResult(
                True, "ok_machine_review_complete_with_deferrals", result.message
            ),
            result,
        )

    def test_deferring_a_repeated_finding_also_clears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            repeated = _blocking_finding("a.py:1", "correctness")
            self._to_outer_round_two_with_new_finding(
                target, repeated, [repeated], coverage=FULL_COVERAGE
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        repeated["id"]: {
                            "disposition": "defer",
                            "override_reason": "still not worth blocking on",
                        }
                    }
                },
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual("ok_machine_review_complete_with_deferrals", result.reason)

    def test_incomplete_coverage_still_blocks_after_deferral(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [new_finding],
                coverage={},
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        new_finding["id"]: {
                            "disposition": "defer",
                            "override_reason": "tracked separately",
                        }
                    }
                },
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual("stop_incomplete_coverage", result.reason)

    def test_addressing_instead_of_deferring_still_needs_a_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [new_finding],
                coverage=FULL_COVERAGE,
            )
            record_triage(
                "item-1",
                3,
                {"dispositions": {new_finding["id"]: {"disposition": "address"}}},
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        # round 3 is already the outer phase's one allowed correction round
        self.assertEqual("stop_round_cap", result.reason)

    def test_mixed_address_and_defer_is_not_all_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            addressed = _blocking_finding("c.py:3", "error_handling")
            deferred = _blocking_finding("d.py:4", "maintainability")
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [addressed, deferred],
                coverage=FULL_COVERAGE,
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        addressed["id"]: {"disposition": "address"},
                        deferred["id"]: {
                            "disposition": "defer",
                            "override_reason": "tracked separately",
                        },
                    }
                },
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual("stop_round_cap", result.reason)

    def test_zero_blocking_findings_counts_as_all_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            nit = {
                "id": "n1",
                "location": "c.py:3",
                "category": "style",
                "blocking": False,
                "rank": 3,
                "summary": "consider renaming",
            }
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [nit],
                coverage=FULL_COVERAGE,
            )
            record_triage("item-1", 3, {"dispositions": {}}, target=target)
            result = check("item-1", "head-3", target=target)
        self.assertEqual("ok_machine_review_complete_with_deferrals", result.reason)

    def test_deferred_finding_is_visible_in_log_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            self._to_outer_round_two_with_new_finding(
                target,
                _blocking_finding("a.py:1", "correctness"),
                [new_finding],
                coverage=FULL_COVERAGE,
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        new_finding["id"]: {
                            "disposition": "defer",
                            "override_reason": "tracked in issue #42",
                        }
                    }
                },
                target=target,
            )
            text = log_text("item-1", target=target)
        self.assertIn("CHANGES_REQUIRED", text)
        self.assertIn("defer (tracked in issue #42)", text)

    def test_inner_phase_gets_no_triage_hint_in_stop_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, max_rounds=5)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [_blocking_finding("a.py:1", "correctness")],
                {},
                "CHANGES_REQUIRED",
                target=target,
            )
            record_builder("item-1", 2, "base-sha", {"delivered": "fix"}, target=target)
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
        self.assertEqual("stop_scope_expansion", result.reason)
        self.assertNotIn("codev task triage", result.message)


class CoverageCarryForwardTests(unittest.TestCase):
    """A round only needs to record the dimensions it actually re-verified;
    `check` fills the rest in from whichever earlier round most recently
    established them. This is what makes coverage carry-forward -- documented
    since ADR-0008/0010 -- an invariant the tool enforces rather than
    bookkeeping the recording agent has to get right on its own. See
    docs/adr/0011-mechanize-coverage-carry-forward.md."""

    def test_ok_machine_review_complete_carries_forward_coverage_from_an_earlier_round(
        self,
    ) -> None:
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
            reopen(
                "item-1", "new-head", "human approved a PR-comment fix", target=target
            )
            record_reviewer(
                "item-1",
                2,
                "new-head",
                [],
                {"correctness": FULL_COVERAGE["correctness"]},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "new-head", target=target)
        self.assertEqual(
            CheckResult(True, "ok_machine_review_complete", result.message), result
        )

    def test_a_dimension_never_recorded_in_any_round_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                {"correctness": FULL_COVERAGE["correctness"]},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            reopen("item-1", "new-head", "human approved a fix", target=target)
            record_reviewer(
                "item-1",
                2,
                "new-head",
                [],
                {"correctness": FULL_COVERAGE["correctness"]},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "new-head", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_incomplete_coverage", result.reason)
        self.assertIn("rollout", result.message)

    def test_a_later_rounds_failing_verdict_overrides_an_earlier_pass(self) -> None:
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
            reopen("item-1", "new-head", "human approved a fix", target=target)
            record_reviewer(
                "item-1",
                2,
                "new-head",
                [],
                {"rollout": {"passed": False, "evidence": "rollback broke"}},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "new-head", target=target)
        self.assertFalse(result.ok)
        self.assertEqual("stop_incomplete_coverage", result.reason)
        self.assertIn("rollout", result.message)

    def test_ok_machine_review_complete_with_deferrals_also_carries_forward_coverage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            first_finding = _blocking_finding("a.py:1", "correctness")
            record_builder("item-1", 2, "head-2", {}, target=target)
            record_reviewer(
                "item-1",
                2,
                "head-2",
                [first_finding],
                FULL_COVERAGE,
                "CHANGES_REQUIRED",
                target=target,
            )
            record_triage(
                "item-1",
                2,
                {"dispositions": {first_finding["id"]: {"disposition": "address"}}},
                target=target,
            )
            record_builder("item-1", 3, "head-3", {"delivered": "fix"}, target=target)
            new_finding = _blocking_finding("c.py:3", "error_handling")
            record_reviewer(
                "item-1",
                3,
                "head-3",
                [new_finding],
                {
                    "error_handling": {
                        "passed": True,
                        "evidence": "re-verified only this",
                    }
                },
                "CHANGES_REQUIRED",
                target=target,
            )
            record_triage(
                "item-1",
                3,
                {
                    "dispositions": {
                        new_finding["id"]: {
                            "disposition": "defer",
                            "override_reason": "tracked in issue #9",
                        }
                    }
                },
                target=target,
            )
            result = check("item-1", "head-3", target=target)
        self.assertEqual(
            CheckResult(
                True, "ok_machine_review_complete_with_deferrals", result.message
            ),
            result,
        )


class WaiverTests(unittest.TestCase):
    """docs/adr/0016-human-selectable-specialist-dispatch-with-authorized-
    coverage-waivers.md: a human-authorized waiver satisfies
    `_incomplete_coverage` for a dimension no specialist ran, distinctly
    from an actual pass -- and participates in the same round-ordered,
    most-recent-wins merge `_effective_coverage` already applies to real
    coverage verdicts (ADR-0011)."""

    def test_rejects_empty_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                waive("item-1", "rollout", "  ", target=target)

    def test_rejects_unknown_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                waive("item-1", "not-a-real-dimension", "reason", target=target)

    def test_rejects_when_not_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            with self.assertRaises(TaskError):
                waive("item-1", "rollout", "reason", target=target)

    def test_waived_dimension_resolves_machine_review_complete_with_no_specialist_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            partial = {
                dimension: entry
                for dimension, entry in FULL_COVERAGE.items()
                if dimension != "rollout"
            }
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                partial,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            # Confirm it's genuinely incomplete before waiving.
            self.assertEqual(
                "stop_incomplete_coverage",
                check("item-1", "base-sha", target=target).reason,
            )
            waive(
                "item-1", "rollout", "doc-only change, no rollout risk", target=target
            )
            result = check("item-1", "base-sha", target=target)
        self.assertEqual(
            CheckResult(True, "ok_machine_review_complete", result.message), result
        )

    def test_later_real_verdict_overrides_an_earlier_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            partial = {
                dimension: entry
                for dimension, entry in FULL_COVERAGE.items()
                if dimension != "rollout"
            }
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                partial,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            waive("item-1", "rollout", "assumed low risk", target=target)
            reopen(
                "item-1",
                "new-head",
                "human asked for a rollout check after all",
                target=target,
            )
            record_reviewer(
                "item-1",
                2,
                "new-head",
                [],
                {"rollout": {"passed": False, "evidence": "found a real issue"}},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "new-head", target=target)
        self.assertEqual("stop_incomplete_coverage", result.reason)
        self.assertIn("rollout: not passed", result.message)

    def test_later_waiver_overrides_an_earlier_failing_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            coverage = dict(FULL_COVERAGE)
            coverage["rollout"] = {"passed": False, "evidence": "found an issue"}
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                coverage,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            self.assertEqual(
                "stop_incomplete_coverage",
                check("item-1", "base-sha", target=target).reason,
            )
            reopen(
                "item-1", "new-head", "human decided it doesn't matter", target=target
            )
            waive("item-1", "rollout", "reconsidered, out of scope", target=target)
            record_reviewer(
                "item-1",
                2,
                "new-head",
                [],
                {},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            result = check("item-1", "new-head", target=target)
        self.assertEqual(
            CheckResult(True, "ok_machine_review_complete", result.message), result
        )

    def test_log_text_renders_waivers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            waive("item-1", "rollout", "doc-only change", target=target, by="Alice")
            text = log_text("item-1", target=target)
        self.assertIn("waived by Alice at round 1: rollout", text)
        self.assertIn("doc-only change", text)


class RelinkTests(unittest.TestCase):
    """docs/adr/0020: link_ref is write-once at `start()` (ADR-0004), but a
    human routinely catches a missing/wrong GitHub issue link only after
    round-state already exists -- `relink` is the recovery path, modeled on
    `waive()`'s append-only, never-silently-overwriting shape."""

    def test_rejects_empty_link_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            with self.assertRaises(TaskError):
                relink("item-1", "  ", target=target)

    def test_rejects_when_not_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            close("item-1", "abandoned", target=target)
            with self.assertRaises(TaskError):
                relink(
                    "item-1",
                    "https://github.com/o/r/issues/7",
                    target=target,
                )

    def test_updates_link_ref_visible_through_describe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                link_ref="docs/codev/work/item-1/implementation-plan.md",
            )
            relink(
                "item-1",
                "https://github.com/o/r/issues/7",
                target=target,
                by="urban233",
            )
            description = describe("item-1", target=target)
        self.assertEqual("https://github.com/o/r/issues/7", description["link_ref"])

    def test_a_later_relink_overrides_an_earlier_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target)
            relink("item-1", "https://github.com/o/r/issues/7", target=target)
            relink("item-1", "https://github.com/o/r/issues/9", target=target)
            description = describe("item-1", target=target)
        self.assertEqual("https://github.com/o/r/issues/9", description["link_ref"])

    def test_log_text_renders_the_correction_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                link_ref="docs/codev/work/item-1/implementation-plan.md",
            )
            relink(
                "item-1",
                "https://github.com/o/r/issues/7",
                target=target,
                by="urban233",
            )
            text = log_text("item-1", target=target)
        self.assertIn(
            "relinked by urban233: "
            "docs/codev/work/item-1/implementation-plan.md -> "
            "https://github.com/o/r/issues/7",
            text,
        )
        self.assertIn("link: https://github.com/o/r/issues/7", text)


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
        self.assertEqual("item-1", records[0]["task_id"])
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
        self.assertEqual(["item-1", "item-2"], [r["task_id"] for r in records])

    def test_unknown_trigger_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(TaskError):
                record_escalation("item-1", "not_a_real_trigger", "why", target=target)

    def test_empty_cause_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(TaskError):
                record_escalation("item-1", "stop_drift", "   ", target=target)

    def test_invalid_phase_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(TaskError):
                record_escalation(
                    "item-1", "stop_drift", "why", target=target, phase="sideways"
                )

    def test_read_filters_by_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            record_escalation("item-1", "stop_drift", "a", target=target)
            record_escalation("item-2", "stop_drift", "b", target=target)
            records = read_escalations(target=target, task_id="item-2")
        self.assertEqual(1, len(records))
        self.assertEqual("item-2", records[0]["task_id"])

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


class SpecialistSelectionTests(unittest.TestCase):
    """docs/adr/0018-specialist-selection-audit-record.md: an optional,
    validated audit record of which outer-loop specialists actually ran a
    round -- deliberately optional (mirroring `coverage`), since a
    comment-sourced round (ADR-0010) legitimately dispatches none of the
    five."""

    def _to_outer_round(self, target: Path) -> None:
        start("item-1", "base-sha", target=target)
        record_reviewer(
            "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
        )
        record_builder("item-1", 2, "head-2", {}, target=target)

    def test_accepts_a_valid_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            record_reviewer(
                "item-1",
                2,
                "head-2",
                [],
                {},
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
                specialist_selection={
                    "specialists": [
                        "correctness-tests-specialist",
                        "rollout-specialist",
                    ]
                },
            )
            text = log_text("item-1", target=target)
        self.assertIn(
            "specialists: correctness-tests-specialist, rollout-specialist", text
        )

    def test_accepts_an_empty_selection_for_a_comment_sourced_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            record_reviewer(
                "item-1",
                2,
                "head-2",
                [],
                {},
                "CHANGES_REQUIRED",
                target=target,
                specialist_selection={"specialists": []},
            )
            text = log_text("item-1", target=target)
        self.assertIn("specialists: none", text)

    def test_omitted_selection_renders_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            record_reviewer(
                "item-1", 2, "head-2", [], {}, "CHANGES_REQUIRED", target=target
            )
            text = log_text("item-1", target=target)
        self.assertNotIn("specialists:", text)

    def test_rejects_unknown_specialist_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            with self.assertRaises(TaskError):
                record_reviewer(
                    "item-1",
                    2,
                    "head-2",
                    [],
                    {},
                    "CHANGES_REQUIRED",
                    target=target,
                    specialist_selection={"specialists": ["not-a-real-specialist"]},
                )

    def test_rejects_a_repeated_specialist_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            with self.assertRaises(TaskError):
                record_reviewer(
                    "item-1",
                    2,
                    "head-2",
                    [],
                    {},
                    "CHANGES_REQUIRED",
                    target=target,
                    specialist_selection={
                        "specialists": [
                            "rollout-specialist",
                            "rollout-specialist",
                        ]
                    },
                )

    def test_rejects_non_object_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._to_outer_round(target)
            with self.assertRaises(TaskError):
                record_reviewer(
                    "item-1",
                    2,
                    "head-2",
                    [],
                    {},
                    "CHANGES_REQUIRED",
                    target=target,
                    specialist_selection=["rollout-specialist"],
                )


class PrDescriptionTests(unittest.TestCase):
    def test_renders_a_waived_dimension_distinctly_from_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="x")
            partial = {
                dimension: entry
                for dimension, entry in FULL_COVERAGE.items()
                if dimension != "rollout"
            }
            record_reviewer(
                "item-1",
                1,
                "base-sha",
                [],
                partial,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            waive("item-1", "rollout", "doc-only change", target=target, by="Alice")
            body = pr_description("item-1", target=target)
        self.assertIn("rollout: waived (by Alice) -- doc-only change", body)
        self.assertNotIn("rollout: passed", body)

    def test_falls_back_to_summary_when_description_unset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="a small fix")
            body = pr_description("item-1", target=target)
        self.assertIn("a small fix", body)

    def test_prefers_description_over_summary_when_both_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                summary="short",
                description="the fuller why and what, discussed and approved",
            )
            body = pr_description("item-1", target=target)
        self.assertIn("the fuller why and what, discussed and approved", body)

    def test_reports_review_in_progress_before_any_reviewer_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="x")
            body = pr_description("item-1", target=target)
        self.assertIn("still in progress", body)

    def test_reports_all_dimensions_pass_on_full_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="x")
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            record_builder("item-1", 2, "base-sha", {}, target=target)
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [],
                FULL_COVERAGE,
                "READY_FOR_HUMAN_APPROVAL",
                target=target,
            )
            body = pr_description("item-1", target=target)
        expected = f"All {len(REQUIRED_COVERAGE_DIMENSIONS)} review dimensions pass"
        self.assertIn(expected, body)

    def test_names_missing_dimensions_individually_when_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="x")
            record_reviewer(
                "item-1", 1, "base-sha", [], {}, "READY_FOR_OUTER_LOOP", target=target
            )
            partial = {"correctness": {"passed": True, "evidence": "checked"}}
            record_builder("item-1", 2, "base-sha", {}, target=target)
            record_reviewer(
                "item-1",
                2,
                "base-sha",
                [],
                partial,
                "CHANGES_REQUIRED",
                target=target,
            )
            body = pr_description("item-1", target=target)
        self.assertIn("correctness: passed", body)
        self.assertIn("rollout: not yet reviewed", body)

    def test_never_includes_the_round_by_round_trail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start("item-1", "base-sha", target=target, summary="x")
            finding = {
                "id": "f1",
                "location": "a.py:1",
                "category": "correctness",
                "blocking": True,
                "rank": 1,
                "summary": "a bug",
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
            body = pr_description("item-1", target=target)
        self.assertNotIn("a bug", body)
        self.assertNotIn("round 1:", body)
        self.assertIn("codev task log", body)

    def test_includes_the_task_id_and_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            start(
                "item-1",
                "base-sha",
                target=target,
                summary="x",
                link_ref="docs/plan.md",
            )
            body = pr_description("item-1", target=target)
        self.assertIn("item-1", body)
        self.assertIn("docs/plan.md", body)


if __name__ == "__main__":
    unittest.main()
