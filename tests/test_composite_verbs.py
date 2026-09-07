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
"""The composite lifecycle verbs, driven against a real repository.

Each verb here replaces one numbered step in a role file that issued several
commands with conditional flags between them. The point of the tier is that
they are exercised the way an agent invokes them -- through `cli.main` with an
argv, not by calling the functions they compose -- because the argv is the
contract ADR-0036 says the CLI owes an agent.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from typing import Any

from codev_workflow import cli, git_ops, task
from tests.integration_support import Sandbox, run_git

_GH_BODY_UNSUPPORTED = os.name == "nt"


def run(*argv: str) -> tuple[int, dict[str, Any]]:
    """Invoke the CLI as an agent does, and parse what it promises to emit."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main([*argv, "--json"])
    printed = buffer.getvalue().strip().splitlines()
    return code, json.loads(printed[-1]) if printed else {}


@unittest.skipIf(
    _GH_BODY_UNSUPPORTED,
    "the gh stub cannot carry a multi-line --body through a cmd.exe wrapper",
)
class SliceBeginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = str(self.sandbox.work)

    def test_begin_creates_branch_issue_and_round_state_in_one_call(self) -> None:
        """The step that was six commands and four conditional flags."""
        code, payload = run(
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--title",
            "a title",
            "--body",
            "a body",
            "--target",
            self.work,
        )
        self.assertEqual(0, code)
        self.assertEqual("codev/feat", payload["branch"])
        self.assertEqual("feat", payload["slice_id"])
        self.assertEqual(1, payload["issue_number"])
        self.assertEqual(1, payload["round"])
        # Round state exists and carries the issue, rather than the caller
        # having to follow up with `codev task relink`.
        self.assertEqual(
            "https://github.com/o/r/issues/1",
            task.describe("feat", target=self.sandbox.work)["link_ref"],
        )

    def test_begin_declares_the_whole_slice_list(self) -> None:
        _, payload = run(
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--title",
            "t",
            "--body",
            "b",
            "--slice",
            "one",
            "--slice",
            "two",
            "--target",
            self.work,
        )
        self.assertEqual(["one", "two"], payload["slices"])
        self.assertEqual("one", payload["slice_id"])

    def _begin_from_plan(self, body: str, *slices: str) -> dict[str, Any]:
        """Begin a slice from a committed plan, based on the commit that
        carries it.

        Committed rather than merely written, and used as the base: the branch
        is cut from `--base`, so a plan committed after that snapshot is not on
        the branch that is supposed to be built against it.
        """
        self.sandbox.write("docs/plans/the-plan.md", f"# Plan\n\n{body}")
        run_git(["add", "-A"], cwd=self.sandbox.work)
        run_git(["commit", "-qm", "the plan"], cwd=self.sandbox.work)
        argv = ["slice", "begin", "--id", "feat", "--base", self.sandbox.head()]
        for name in slices:
            argv += ["--slice", name]
        _, payload = run(*argv, "--title", "t", "--body", "b", "--target", self.work)
        return payload

    def test_begin_warns_when_an_accepted_plan_names_more_slices(self) -> None:
        """Every task in this repository's own history recorded exactly one
        slice, including one whose accepted plan named seven -- whose seven
        slices then landed in a single pull request. `--slice` is optional and
        stays optional, because a one-slice task is real; forgetting it is
        what needed to stop being silent.
        """
        payload = self._begin_from_plan(
            "**Status:** Accepted\n\n"
            + "\n".join(f"### Slice {n} -- thing\n" for n in range(1, 8))
        )
        self.assertEqual(["feat"], payload["slices"])
        self.assertIn("names 7 slices", payload["slice_warning"])

    def test_begin_is_quiet_when_the_slice_list_matches_the_plan(self) -> None:
        payload = self._begin_from_plan(
            "**Status:** Accepted\n\n### Slice 1 -- a\n\n### Slice 2 -- b\n",
            "one",
            "two",
        )
        self.assertIsNone(payload["slice_warning"])

    def test_begin_is_quiet_for_a_genuinely_single_slice_plan(self) -> None:
        payload = self._begin_from_plan("**Status:** Accepted\n\n**Slices:** One PR\n")
        self.assertIsNone(payload["slice_warning"])

    def test_begin_does_not_read_a_plan_nobody_accepted(self) -> None:
        payload = self._begin_from_plan(
            "**Status:** Draft\n\n### Slice 1 -- a\n\n### Slice 2 -- b\n"
        )
        self.assertIsNone(payload["slice_warning"])

    def test_begin_puts_the_first_slice_on_its_own_branch(self) -> None:
        """`create_branch` runs before round state exists, so it fell back to
        the task id and filed slice one's branch under a slice that does not
        exist -- which is why `start_slice_branch` then refused every later
        slice with "no earlier slice has a branch to stack it on"."""
        payload = self._begin_from_plan(
            "**Status:** Accepted\n\n### Slice 1 -- a\n\n### Slice 2 -- b\n",
            "one",
            "two",
        )
        self.assertEqual("codev/feat--one", payload["branch"])
        self.assertEqual(
            "codev/feat--one",
            git_ops.branch_for_slice("feat", "one", target=self.sandbox.work),
        )

    def test_begin_refuses_to_invent_an_issue_it_was_not_told_how_to_write(
        self,
    ) -> None:
        code, _ = run(
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--target",
            self.work,
        )
        self.assertEqual(2, code)

    def test_begin_reuses_an_existing_issue_without_creating_another(self) -> None:
        _, payload = run(
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--github-issue",
            "7",
            "--target",
            self.work,
        )
        self.assertEqual(7, payload["issue_number"])
        self.assertEqual({}, self.sandbox.gh.read().get("prs", {}))


@unittest.skipIf(
    _GH_BODY_UNSUPPORTED,
    "the gh stub cannot carry a multi-line --body through a cmd.exe wrapper",
)
class RoundAndPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = str(self.sandbox.work)
        self.evidence = self.sandbox.work / "evidence.json"
        run(
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--title",
            "t",
            "--body",
            "b",
            "--target",
            self.work,
        )

    def _evidence(self) -> str:
        self.evidence.write_text(json.dumps({"validation": "ran"}), encoding="utf-8")
        return str(self.evidence)

    def test_round_close_commits_and_records_against_the_resulting_head(self) -> None:
        """The head is the point: a builder cannot know it before the commit
        exists, which is why it never records its own round."""
        self.sandbox.write("built.py", "value = 1\n")
        code, payload = run(
            "round",
            "close",
            "--id",
            "feat",
            "--role",
            "builder",
            "--evidence",
            self._evidence(),
            "--target",
            self.work,
        )
        self.assertEqual(0, code)
        self.assertEqual(self.sandbox.head(), payload["head"])
        self.assertEqual(1, payload["round"])

    def test_round_close_derives_the_round_number_from_state(self) -> None:
        """Not asked for, because the state file already holds it and a
        caller that guesses wrong writes into the wrong slot."""
        self.sandbox.write("built.py", "value = 1\n")
        _, first = run(
            "round",
            "close",
            "--id",
            "feat",
            "--role",
            "builder",
            "--evidence",
            self._evidence(),
            "--target",
            self.work,
        )
        self.assertEqual(1, first["round"])

    def test_publish_pushes_and_opens_a_draft_in_one_call(self) -> None:
        self.sandbox.write("built.py", "value = 1\n")
        run(
            "round",
            "close",
            "--id",
            "feat",
            "--role",
            "builder",
            "--evidence",
            self._evidence(),
            "--target",
            self.work,
        )
        task.record_reviewer(
            "feat",
            1,
            self.sandbox.head(),
            [],
            {},
            "READY_FOR_OUTER_LOOP",
            target=self.sandbox.work,
        )
        code, payload = run(
            "slice",
            "publish",
            "--id",
            "feat",
            "--title",
            "a title",
            "--target",
            self.work,
        )
        self.assertEqual(0, code)
        self.assertTrue(payload["draft"])
        self.assertEqual(1, payload["number"])
        record = self.sandbox.gh.read()["prs"]["codev/feat"]
        # The template body, never a caller-supplied one -- the caveat that
        # said "never pass --body" is gone because there is no --body.
        self.assertIn("Closes #1", record["body"])


@unittest.skipIf(
    _GH_BODY_UNSUPPORTED,
    "the gh stub cannot carry a multi-line --body through a cmd.exe wrapper",
)
class SliceLandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)
        self.work = str(self.sandbox.work)

    def _begin(self, *slices: str) -> None:
        argv = [
            "slice",
            "begin",
            "--id",
            "feat",
            "--base",
            self.sandbox.base,
            "--title",
            "t",
            "--body",
            "b",
            "--target",
            self.work,
        ]
        for name in slices:
            argv += ["--slice", name]
        run(*argv)

    def test_land_advances_when_a_later_slice_remains(self) -> None:
        self._begin("one", "two")
        code, payload = run("slice", "land", "--id", "feat", "--target", self.work)
        self.assertEqual(0, code)
        self.assertFalse(payload["final"])
        self.assertEqual("two", payload["next_slice"])

    def test_land_puts_the_next_slice_on_its_own_branch(self) -> None:
        """ADR-0035: a slice is one pull request, so advancing is not
        complete until the next slice has somewhere of its own to live.

        `land` moved the round state and left the branch alone, so the work
        stayed on the previous slice's branch -- where `open_pr` then refused
        to open a second pull request and every later slice accumulated into
        the first one's. `codev task advance-slice` had always branched; the
        composite verb the navigator actually recommends did not.
        """
        self._begin("one", "two")
        code, payload = run("slice", "land", "--id", "feat", "--target", self.work)
        self.assertEqual(0, code)
        self.assertIsNone(payload["branch_error"])
        self.assertEqual("codev/feat--two", payload["branch"])
        self.assertEqual("codev/feat--two", git_ops.current_branch(self.sandbox.work))
        self.assertEqual(
            "codev/feat--two",
            git_ops.branch_for_slice("feat", "two", target=self.sandbox.work),
        )

    def test_land_reports_a_branch_it_could_not_create_rather_than_failing(
        self,
    ) -> None:
        """Best-effort by design: the round state has already moved by the
        time the branch is attempted, so a failure must be visible rather
        than either silent or fatal."""
        self._begin("one", "two")
        self.sandbox.write("product.py", "value = 1\n")
        code, payload = run("slice", "land", "--id", "feat", "--target", self.work)
        self.assertEqual(0, code)
        self.assertIsNone(payload["branch"])
        self.assertIn("uncommitted", payload["branch_error"])

    def test_land_closes_the_task_on_the_final_slice(self) -> None:
        """One command for both, because which one applies is a fact about
        the slice list -- not a decision the caller should be making."""
        self._begin()
        code, payload = run("slice", "land", "--id", "feat", "--target", self.work)
        self.assertEqual(0, code)
        self.assertTrue(payload["final"])
        self.assertEqual("approved", payload["outcome"])
        self.assertEqual(
            "closed", task.describe("feat", target=self.sandbox.work)["status"]
        )


if __name__ == "__main__":
    unittest.main()
