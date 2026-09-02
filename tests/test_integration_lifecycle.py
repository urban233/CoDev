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
"""The integration tier: one complete task lifecycle, driven end to end
against a real repository, a real bare remote, and a `gh` on PATH.

Every case here is one the unit suites structurally cannot cover, because
they mock `git_ops._run_gh` at the function boundary. The two regression
tests at the bottom pin defects that reached `main` exactly that way.
"""

from __future__ import annotations

import unittest

from codev_workflow import git_ops, task
from tests.integration_support import Sandbox, run_git


class LifecycleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = self.sandbox.work

    def _start(self, slices: list[str] | None = None, **kwargs: object) -> None:
        task.start(
            "feat",
            self.sandbox.base,
            target=self.work,
            link_ref="https://github.com/o/r/issues/1",
            slices=slices,
            **kwargs,  # type: ignore[arg-type]
        )
        git_ops.create_branch("feat", self.sandbox.base, target=self.work)

    def _commit(self, name: str) -> str:
        self.sandbox.write(f"{name}.py", f"{name} = 1\n")
        return git_ops.commit("feat", f"slice {name}", target=self.work)

    def test_a_single_slice_task_reaches_a_ready_pull_request(self) -> None:
        """The whole loop, with nothing patched: branch, commit, record,
        check, push, open, mark ready."""
        self._start()
        head = self._commit("a")
        task.record_reviewer(
            "feat", 1, head, [], {}, "READY_FOR_OUTER_LOOP", target=self.work
        )
        self.assertEqual(
            "ok_ready_for_pr", task.check("feat", head, target=self.work).reason
        )
        git_ops.push("feat", target=self.work)
        url = git_ops.open_pr("feat", "title", "body", target=self.work)
        self.assertTrue(url.startswith("https://github.com/o/r/pull/"))

        record = self.sandbox.gh.read()["prs"]["codev/feat"]
        self.assertTrue(record["draft"])
        self.assertEqual("main", record["base"])
        # A single-slice task closes its issue; there is nothing after it.
        self.assertIn("Closes #1", record["body"])

    def test_marking_ready_requests_review_and_states_ownership(self) -> None:
        # direct-review opens round 1 in the outer phase, which is where a
        # READY_FOR_HUMAN_APPROVAL verdict belongs -- open_pr refuses one
        # recorded against the inner phase.
        self._start(entry="direct-review")
        head = self._commit("a")
        coverage = {
            dimension: {"passed": True, "evidence": "checked"}
            for dimension in task.REQUIRED_COVERAGE_DIMENSIONS
        }
        task.record_reviewer(
            "feat", 1, head, [], coverage, "READY_FOR_HUMAN_APPROVAL", target=self.work
        )
        git_ops.push("feat", target=self.work)
        git_ops.open_pr("feat", "title", "body", target=self.work)
        git_ops.mark_ready("feat", target=self.work)

        record = self.sandbox.gh.read()["prs"]["codev/feat"]
        self.assertFalse(record["draft"])
        self.assertIn("I directed this change and I own it", record["body"])
        self.assertIn("not an approval", record["body"])

    def test_only_the_final_slice_closes_the_issue(self) -> None:
        self._start(slices=["a", "b"])
        head = self._commit("a")
        task.record_reviewer(
            "feat", 1, head, [], {}, "READY_FOR_OUTER_LOOP", target=self.work
        )
        git_ops.push("feat", target=self.work)
        git_ops.open_pr("feat", "first", "body", target=self.work)
        first = self.sandbox.gh.read()["prs"]["codev/feat--a"]
        self.assertIn("Part of #1", first["body"])
        self.assertNotIn("Closes #1", first["body"])

        task.advance_slice("feat", head, target=self.work)
        git_ops.start_slice_branch("feat", "b", target=self.work)
        second_head = self._commit("b")
        task.record_reviewer(
            "feat", 2, second_head, [], {}, "READY_FOR_OUTER_LOOP", target=self.work
        )
        git_ops.push("feat", target=self.work)
        git_ops.open_pr("feat", "second", "body", target=self.work)
        second = self.sandbox.gh.read()["prs"]["codev/feat--b"]

        self.assertIn("Closes #1", second["body"])
        # The child targets its predecessor while that is still open.
        self.assertEqual("codev/feat--a", second["base"])

    def test_a_human_approval_is_read_from_the_pull_request(self) -> None:
        self._start()
        head = self._commit("a")
        task.record_reviewer(
            "feat", 1, head, [], {}, "READY_FOR_OUTER_LOOP", target=self.work
        )
        git_ops.push("feat", target=self.work)
        git_ops.open_pr("feat", "title", "body", target=self.work)

        approval = git_ops.human_approval(
            "codev/feat", owner="@alice", target=self.work
        )
        assert approval is not None
        self.assertFalse(approval.satisfied)

        self.sandbox.gh.approve("codev/feat", "@alice")  # the owner
        self.sandbox.gh.approve("codev/feat", "review-bot[bot]")
        approval = git_ops.human_approval(
            "codev/feat", owner="@alice", target=self.work
        )
        assert approval is not None
        self.assertFalse(approval.satisfied, "owner and bot must not count")

        self.sandbox.gh.approve("codev/feat", "@bob")
        approval = git_ops.human_approval(
            "codev/feat", owner="@alice", target=self.work
        )
        assert approval is not None
        self.assertTrue(approval.satisfied)
        self.assertEqual(("@bob",), approval.approvals)


class RestackCascadeRegressionTests(unittest.TestCase):
    """Both defects here reached `main` and passed the whole unit suite."""

    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = self.sandbox.work
        task.start(
            "feat",
            self.sandbox.base,
            target=self.work,
            link_ref="https://github.com/o/r/issues/1",
            slices=["a", "b", "c"],
        )
        git_ops.create_branch("feat", self.sandbox.base, target=self.work)
        for name in ("a", "b", "c"):
            self.sandbox.write(f"{name}.py", f"{name} = 1\n")
            head = git_ops.commit("feat", f"slice {name}", target=self.work)
            git_ops.push("feat", target=self.work)
            if name != "c":
                task.advance_slice("feat", head, target=self.work)
                git_ops.start_slice_branch("feat", name_next(name), target=self.work)

    def _stand_on_slice(self, slice_id: str) -> None:
        state = task._load("feat", target=self.work)
        state["current_slice"] = slice_id
        task._save("feat", state, target=self.work)
        run_git(["add", "-A"], cwd=self.work)
        run_git(["commit", "-qm", "pin slice"], cwd=self.work)
        run_git(["checkout", "-q", f"codev/feat--{slice_id}"], cwd=self.work)

    def test_amending_the_first_slice_propagates_through_the_stack(self) -> None:
        """Regression: the cascade could not find the later slices at all.

        `git-state.json` is committed, so slice a's branch carries the
        version written before b and c existed -- and amending slice a means
        standing on exactly that branch.
        """
        self._stand_on_slice("a")
        self.sandbox.write("a.py", "a = 1\na = 2\n")
        run_git(["commit", "-qam", "amend a"], cwd=self.work)

        rebased = git_ops.restack("feat", target=self.work)

        self.assertEqual(["b", "c"], rebased)
        self.assertIn("a = 2", self.sandbox.file_on("codev/feat--b", "a.py"))
        self.assertIn("a = 2", self.sandbox.file_on("codev/feat--c", "a.py"))
        # ...and every slice's own work survived the rebase.
        self.assertIn("b = 1", self.sandbox.file_on("codev/feat--c", "b.py"))

    def test_a_dirty_worktree_is_refused_before_anything_is_rebased(self) -> None:
        """Regression: the cascade checked out each slice in turn and died
        partway with a raw git error, leaving some rebased and some not."""
        self._stand_on_slice("a")
        before = self.sandbox.file_on("codev/feat--c", "a.py")
        self.sandbox.write("uncommitted.py", "x = 1\n")

        with self.assertRaises(git_ops.GitOpsError) as caught:
            git_ops.restack("feat", target=self.work)

        self.assertIn("uncommitted changes", str(caught.exception))
        self.assertEqual(before, self.sandbox.file_on("codev/feat--c", "a.py"))

    def test_the_cascade_refuses_once_the_predecessor_has_merged(self) -> None:
        self._stand_on_slice("a")
        self.sandbox.gh.set_pr_state("codev/feat--a", "MERGED")
        with self.assertRaises(git_ops.GitOpsError) as caught:
            git_ops.restack("feat", target=self.work)
        self.assertIn("already merged", str(caught.exception))


def name_next(name: str) -> str:
    return {"a": "b", "b": "c"}[name]


if __name__ == "__main__":
    unittest.main()
