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

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codev_workflow import git_ops, task
from codev_workflow.navigator import _BY_CHECK_REASON, NextAction, next_action


def _init_repo(target: Path) -> str:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=target, check=True, capture_output=True, text=True
        ).stdout.strip()

    run("init", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (target / "seed.txt").write_text("seed\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-m", "seed")
    return run("rev-parse", "HEAD")


class RoutingTableTests(unittest.TestCase):
    """The thirteen check outcomes already are the routing table; a missing
    entry must be a visible failure, not a silent fallthrough."""

    def test_every_check_outcome_has_exactly_one_next_step(self) -> None:
        from codev_workflow.task import DEPRECATED_REASON_ALIASES

        expected = {
            "ok_waiting_on_reviewer",
            "ok_ready_for_pr",
            "ok_continue",
            "ok_waiting_on_triage",
            "ok_machine_review_complete",
            "ok_machine_review_complete_with_deferrals",
            "ok_blocked_missing_evidence",
            "ok_outer_loop_needs_reopen",
            "stop_drift",
            "stop_round_cap",
            "stop_repeated_finding",
            "stop_scope_expansion",
            "stop_incomplete_coverage",
        }
        self.assertEqual(expected, set(_BY_CHECK_REASON))
        self.assertEqual(13, len(_BY_CHECK_REASON))
        # Both renamed reasons route; neither old name leaks into the table.
        for renamed in DEPRECATED_REASON_ALIASES.values():
            self.assertNotIn(renamed, _BY_CHECK_REASON)

    def test_every_stop_outcome_is_marked_blocked(self) -> None:
        for reason, (_, _, _, blocked) in _BY_CHECK_REASON.items():
            if reason.startswith("stop_"):
                self.assertTrue(blocked, f"{reason} must block")


class LocalPositionTests(unittest.TestCase):
    def test_a_branch_with_no_task_recommends_starting_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _init_repo(target)
            action = next_action(target=target, check_github=False)
        self.assertEqual("no task on this branch", action.position)
        self.assertFalse(action.blocked)

    def test_a_task_branch_without_round_state_recommends_task_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            action = next_action(target=target, check_github=False)
        self.assertEqual("branch exists, no round state", action.position)
        self.assertEqual("item-1", action.task_id)
        self.assertEqual("codev task start", action.command)

    def test_a_fresh_task_waits_on_the_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            task.start("item-1", base, target=target, link_ref="x")
            action = next_action(target=target, check_github=False)
        self.assertEqual("ok_waiting_on_reviewer", action.check_reason)
        self.assertEqual("review the round", action.recommendation)
        self.assertEqual("item-1", action.slice_id)
        self.assertFalse(action.blocked)

    def test_a_stop_outcome_reports_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            task.start("item-1", "a-different-base", target=target, link_ref="x")
            action = next_action(target=target, check_github=False)
        self.assertEqual("stop_drift", action.check_reason)
        self.assertTrue(action.blocked)

    def test_a_closed_task_recommends_the_next_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            base = _init_repo(target)
            git_ops.create_branch("item-1", base, target=target)
            task.start("item-1", base, target=target, link_ref="x")
            task.close("item-1", "approved", target=target)
            action = next_action(target=target, check_github=False)
        self.assertIn("task closed", action.position)


class GitHubPositionTests(unittest.TestCase):
    """The positions only GitHub knows about (ADR-0036, slice B2)."""

    def _ready_task(self, target: Path, slices: list[str] | None = None) -> None:
        base = _init_repo(target)
        git_ops.create_branch("item-1", base, target=target)
        task.start(
            "item-1",
            base,
            target=target,
            link_ref="x",
            entry="direct-review",
            slices=slices,
        )
        coverage = {
            dimension: {"passed": True, "evidence": "checked"}
            for dimension in task.REQUIRED_COVERAGE_DIMENSIONS
        }
        head = git_ops.current_head(target)
        task.record_reviewer(
            "item-1",
            1,
            head,
            [],
            coverage,
            "READY_FOR_HUMAN_APPROVAL",
            target=target,
        )

    def _open_pr(
        self, target: Path, approval: git_ops.HumanApproval | None
    ) -> NextAction:
        with (
            patch.object(git_ops, "pull_request_state", return_value="OPEN"),
            patch.object(git_ops, "human_approval", return_value=approval),
        ):
            return next_action(target=target)

    def test_an_open_pull_request_waits_on_a_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            action = self._open_pr(target, git_ops.HumanApproval((), 1, "@alice"))
        self.assertIn("awaiting human review", action.position)
        self.assertIn("is not an approval", action.reason)

    def test_an_independent_approval_satisfies_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            action = self._open_pr(
                target, git_ops.HumanApproval(("@bob",), 1, "@alice")
            )
        self.assertEqual("approved by a human", action.position)
        self.assertEqual("ok_human_approved", action.check_reason)

    def test_two_required_approvals_are_not_met_by_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            action = self._open_pr(
                target, git_ops.HumanApproval(("@bob",), 2, "@alice")
            )
        self.assertIn("awaiting human review", action.position)
        self.assertIn("1 of 2", action.reason)

    def test_unreachable_github_reports_unknown_not_unapproved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            action = self._open_pr(target, None)
        self.assertIn("review state unknown", action.position)

    def test_a_waived_review_is_reported_as_waived_not_approved(self) -> None:
        """Nothing may conflate "nobody reviewed this" with "someone
        approved it"."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            task.waive_review("item-1", "solo maintainer", target=target)
            action = self._open_pr(target, None)
        self.assertEqual("independent review waived", action.position)
        self.assertEqual("ok_human_review_waived", action.check_reason)
        self.assertIn("solo maintainer", action.reason)
        self.assertNotEqual("ok_human_approved", action.check_reason)

    def test_a_merged_final_slice_recommends_closing_the_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            with patch.object(git_ops, "pull_request_state", return_value="MERGED"):
                action = next_action(target=target)
        self.assertEqual("final slice merged", action.position)
        self.assertEqual("codev task close --outcome approved", action.command)

    def test_a_merged_slice_with_more_remaining_recommends_advancing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target, slices=["a", "b"])
            with patch.object(git_ops, "pull_request_state", return_value="MERGED"):
                action = next_action(target=target)
        self.assertEqual("slice merged, more remain", action.position)
        self.assertEqual("codev task advance-slice", action.command)

    def test_github_silence_falls_back_to_the_local_recommendation(self) -> None:
        """None means "cannot tell" -- never report a guess as fact."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._ready_task(target)
            with patch.object(git_ops, "pull_request_state", return_value=None):
                action = next_action(target=target)
        self.assertEqual("ok_machine_review_complete", action.check_reason)
        self.assertEqual("request human review", action.recommendation)


if __name__ == "__main__":
    unittest.main()
